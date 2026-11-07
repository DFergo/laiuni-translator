"""Sprint 22: machine API (SPEC §16) — tokens, auth, /translate, /jobs, Markdown guarantees.

Run inside the backend container:
    cd /app && python -m unittest src.tests.test_machine_api -v
"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["LAIUNI_DATA_DIR"] = _TMP.name

from fastapi.testclient import TestClient  # noqa: E402

from src.api.v1 import machine  # noqa: E402
from src.main import app  # noqa: E402
from src.services import api_tokens, job_queue as jq  # noqa: E402
from src.services.connection_registry import connections  # noqa: E402
from src.services.llm_provider import llm  # noqa: E402

SOURCE = "---\ntitle: Hola\ntags: [a]\n---\n\n# Titulo\n\nVer [[Nota X]] y https://example.com/a.\n\n```py\nx = 1\n```\n"


class SplitAndWarningsTest(unittest.TestCase):
    def test_frontmatter_split(self):
        fm, body = machine.split_frontmatter(SOURCE)
        self.assertTrue(fm.startswith("---\ntitle") and fm.endswith("---\n"))
        self.assertTrue(body.lstrip().startswith("# Titulo"))
        self.assertEqual(machine.split_frontmatter("# no fm\n"), ("", "# no fm\n"))

    def test_warnings(self):
        _, body = machine.split_frontmatter(SOURCE)
        self.assertEqual(machine.preservation_warnings(body, body), [])
        broken = body.replace("[[Nota X]]", "[[Note X]]").replace("x = 1", "x = 2")
        w = machine.preservation_warnings(body, broken)
        self.assertEqual(len(w), 2)
        self.assertTrue(any("wikilink" in x for x in w) and any("code block" in x for x in w))


class TokenStoreTest(unittest.TestCase):
    def test_create_verify_revoke(self):
        plaintext, entry = api_tokens.create("t1")
        self.assertTrue(plaintext.startswith("lt_"))
        self.assertNotIn("hash", entry)
        self.assertEqual(api_tokens.verify(plaintext)["name"], "t1")
        self.assertIsNone(api_tokens.verify(plaintext + "x"))
        self.assertNotIn(plaintext, api_tokens._PATH.read_text())  # only the hash is stored
        self.assertTrue(api_tokens.revoke(entry["id"]))
        self.assertIsNone(api_tokens.verify(plaintext))


class MachineApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jq.init_db()  # TestClient without a context manager does not run the lifespan
        cls.client = TestClient(app)
        cls.token, cls.entry = api_tokens.create("skill")
        cls.auth = {"Authorization": f"Bearer {cls.token}"}
        if not connections.get("test-conn"):
            connections.add({"id": "test-conn", "type": "openai", "base_url": "http://x/v1",
                             "api_key": "k", "model_ids": ["m1"], "enable": True})
        cls._orig_chat = llm.chat_with_fallback
        # TestClient runs each request in a throwaway loop, so background tasks started by
        # dispatch() would die with it; these tests drive process_job themselves.
        cls._orig_dispatch = jq.dispatch
        jq.dispatch = lambda *a, **k: 0

        async def fake_chat(messages, chain):
            if "ISO 639-1" in messages[0]["content"]:
                return "es"
            text = messages[-1]["content"].split("--- Text to translate ---\n", 1)[-1]
            return text.replace("Titulo", "Title").replace("Ver", "See")
        llm.chat_with_fallback = fake_chat

    @classmethod
    def tearDownClass(cls):
        llm.chat_with_fallback = cls._orig_chat
        jq.dispatch = cls._orig_dispatch

    def test_auth_required(self):
        self.assertEqual(self.client.get("/api/v1/languages").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/languages", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/translate", json={}).status_code, 401)

    def test_languages(self):
        r = self.client.get("/api/v1/languages", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["languages"]), 17)

    def test_translate_keeps_frontmatter_and_autodetects(self):
        r = self.client.post("/api/v1/translate", headers=self.auth,
                             json={"text": SOURCE, "target_lang": "en", "connection_id": "test-conn"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["translated_text"].startswith("---\ntitle: Hola\ntags: [a]\n---\n"))
        self.assertIn("# Title", d["translated_text"])
        self.assertEqual(d["source_lang"], "es")
        self.assertEqual(d["model"], "m1")  # connection's first allow-listed model
        self.assertEqual(d["warnings"], [])
        self.assertIn("calls", d["usage"])

    def test_translate_validation(self):
        h = self.auth
        self.assertEqual(self.client.post("/api/v1/translate", headers=h, json={"text": "a", "target_lang": "xx"}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/translate", headers=h,
                         json={"text": "a", "target_lang": "en", "frontend_id": "nope"}).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/translate", headers=h,
                         json={"text": "a", "target_lang": "en", "connection_id": "nope"}).status_code, 404)

    def test_job_flow_origin_api_no_email(self):
        r = self.client.post("/api/v1/jobs", headers=self.auth, data={"target_langs": "en,fr", "source_lang": "es",
                             "connection_id": "test-conn"}, files={"file": ("doc.md", b"# Titulo\n\nVer algo.\n")})
        self.assertEqual(r.status_code, 200, r.text)
        job_id = r.json()["job_id"]
        job = jq.get(job_id)
        self.assertEqual((job["origin"], job["owner_email"], job["mode"]), ("api", "api:skill", "immediate"))

        sent = []
        import src.services.smtp_service as smtp

        async def no_send(*a, **k):
            sent.append(a)
        orig = smtp.send_translation_ready
        smtp.send_translation_ready = no_send
        try:
            asyncio.run(jq.process_job(job))
        finally:
            smtp.send_translation_ready = orig
        self.assertEqual(sent, [])

        st = self.client.get(f"/api/v1/jobs/{job_id}", headers=self.auth).json()
        self.assertEqual((st["status"], st["langs_done"]), ("done", ["en", "fr"]))
        self.assertEqual(st["progress"], 1.0)
        res = self.client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
        self.assertEqual(res.headers["content-type"], "application/zip")
        usage = {u["email"]: u for u in jq.usage_summary()}
        self.assertEqual(usage["api:skill"]["origin"], "api")

        # library: listing, per-file download, same data in the status
        files = {f["name"]: f for f in st["files"]}
        self.assertEqual(sorted((f["kind"], f["lang"]) for f in files.values()),
                         [("source", None), ("translation", "en"), ("translation", "fr")])
        listed = {j["job_id"]: j for j in self.client.get("/api/v1/jobs", headers=self.auth).json()}
        self.assertEqual(listed[job_id]["filename"], "doc.md")
        self.assertEqual(listed[job_id]["files"], st["files"])
        one = self.client.get(f"/api/v1/jobs/{job_id}/files/doc.en.md", headers=self.auth)
        self.assertEqual((one.status_code, one.text.startswith("# Title")), (200, True))
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}/files/doc.md", headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}/files/..%2F..%2Fjobs.db", headers=self.auth).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}/files/nope.md", headers=self.auth).status_code, 404)
        flt = self.client.get("/api/v1/jobs?status=cancelled", headers=self.auth).json()
        self.assertTrue(all(j["status"] == "cancelled" for j in flt))

        # another token cannot see it
        other, _ = api_tokens.create("other")
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"}).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/jobs", headers={"Authorization": f"Bearer {other}"}).json(), [])
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}/files/doc.md", headers={"Authorization": f"Bearer {other}"}).status_code, 404)

    def test_duplicate_submission_and_force(self):
        data = {"target_langs": "en", "source_lang": "es", "connection_id": "test-conn"}
        files = lambda: {"file": ("dup.md", b"# Titulo\n\nDuplicado.\n")}  # noqa: E731
        first = self.client.post("/api/v1/jobs", headers=self.auth, data=data, files=files()).json()
        again = self.client.post("/api/v1/jobs", headers=self.auth, data=data, files=files()).json()
        self.assertFalse(first["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["job_id"], first["job_id"])
        forced = self.client.post("/api/v1/jobs", headers=self.auth, data={**data, "force": "true"}, files=files()).json()
        self.assertFalse(forced["duplicate"])
        self.assertNotEqual(forced["job_id"], first["job_id"])
        # different languages = different job
        other = self.client.post("/api/v1/jobs", headers=self.auth, data={**data, "target_langs": "fr"}, files=files()).json()
        self.assertFalse(other["duplicate"])
        # once finished, the same document can be translated again
        for jid in (first["job_id"], forced["job_id"]):  # both identical jobs must be finished
            asyncio.run(jq.process_job(jq.get(jid)))
        redo = self.client.post("/api/v1/jobs", headers=self.auth, data=data, files=files()).json()
        self.assertFalse(redo["duplicate"])

    def test_cancel_via_api(self):
        r = self.client.post("/api/v1/jobs", headers=self.auth, data={"target_langs": "de", "connection_id": "test-conn"},
                             files={"file": ("c.md", b"# Cancel me\n")}).json()
        res = self.client.delete(f"/api/v1/jobs/{r['job_id']}", headers=self.auth)
        self.assertEqual((res.status_code, res.json()["status"]), (200, "cancelled"))
        self.assertFalse((jq.DOCUMENTS_DIR / r["job_id"]).exists())
        self.assertEqual(self.client.get(f"/api/v1/jobs/{r['job_id']}", headers=self.auth).json()["status"], "cancelled")
        self.assertEqual(self.client.delete(f"/api/v1/jobs/{r['job_id']}", headers=self.auth).status_code, 409)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{r['job_id']}/result", headers=self.auth).status_code, 409)

    def test_job_rejects_bad_input(self):
        r = self.client.post("/api/v1/jobs", headers=self.auth, data={"target_langs": "en"},
                             files={"file": ("a.exe", b"x")})
        self.assertEqual(r.status_code, 415)

    def test_openapi_lists_contract(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for p in ("/api/v1/translate", "/api/v1/languages", "/api/v1/jobs", "/api/v1/jobs/{job_id}",
                  "/api/v1/jobs/{job_id}/result", "/api/v1/jobs/{job_id}/files/{filename}", "/admin/api-tokens"):
            self.assertIn(p, paths)


class SchedulerTest(unittest.TestCase):
    """SPEC §17: per-connection capacity, completion-triggered dispatch, cancel, progress."""

    @classmethod
    def setUpClass(cls):
        jq.init_db()
        for cid, parallel, mx in (("solo", False, 4), ("wide", True, 2)):
            if not connections.get(cid):
                connections.add({"id": cid, "type": "openai", "base_url": "http://x/v1", "api_key": "k",
                                 "model_ids": ["m"], "enable": True, "parallel": parallel, "max_concurrent": mx})
        cls.dir = Path(_TMP.name) / "sched"
        cls.dir.mkdir(exist_ok=True)

    def _job(self, conn_id, name):
        f = self.dir / f"{name}.md"
        f.write_text("# Hola\n\nTexto.\n")
        return jq.enqueue("t@x.org", "es", ["en"], "tier1", str(f), mode="immediate",
                          options={"connection_id": conn_id}, origin="api")

    def _with_slow_jobs(self, scenario):
        """Run ``scenario(gates)`` with process_job replaced by one that waits on a per-job gate."""
        async def main():
            gates: dict[str, asyncio.Event] = {}
            started: list[str] = []

            async def slow(job):
                started.append(job["id"])
                gates[job["id"]] = asyncio.Event()
                await gates[job["id"]].wait()
                jq.mark_done(job["id"], 0)
            orig = jq.process_job
            jq.process_job = slow
            try:
                await scenario(gates, started)
            finally:
                jq.process_job = orig
                for t, _ in list(jq._running.values()):
                    t.cancel()
                jq._running.clear()
        asyncio.run(main())

    def test_capacity_per_connection(self):
        solo = [self._job("solo", f"s{i}") for i in range(3)]
        wide = [self._job("wide", f"w{i}") for i in range(3)]

        async def scenario(gates, started):
            jq.dispatch()
            await asyncio.sleep(0.05)
            # solo: one at a time; wide: two; the connections do not block each other
            self.assertEqual(sorted(j["id"] for j in solo + wide if j["id"] in started),
                             sorted([solo[0]["id"], wide[0]["id"], wide[1]["id"]]))
            # finishing one frees a slot and the next starts without waiting for the tick
            gates[wide[0]["id"]].set()
            await asyncio.sleep(0.05)
            self.assertIn(wide[2]["id"], started)
            self.assertNotIn(solo[1]["id"], started)
            gates[solo[0]["id"]].set()
            await asyncio.sleep(0.05)
            self.assertIn(solo[1]["id"], started)
        self._with_slow_jobs(scenario)

    def test_cancel_running_frees_slot(self):
        a, b = self._job("solo", "ca"), self._job("solo", "cb")

        async def scenario(gates, started):
            jq.dispatch()
            await asyncio.sleep(0.05)
            self.assertIn(a["id"], started)
            self.assertNotIn(b["id"], started)
            self.assertTrue(jq.cancel(a["id"]))
            await asyncio.sleep(0.05)
            self.assertEqual(jq.get(a["id"])["status"], "cancelled")
            self.assertIn(b["id"], started)  # its slot went to the next job
            self.assertFalse(jq.cancel(a["id"]))  # already finished
        self._with_slow_jobs(scenario)

    def test_cancel_portal_job_is_recorded_as_failed(self):
        f = self.dir / "portal.md"
        f.write_text("# Hola\n")
        job = jq.enqueue("p@x.org", "es", ["en"], "tier1", str(f), mode="scheduled")
        self.assertTrue(jq.cancel(job["id"]))
        got = jq.get(job["id"])
        self.assertEqual((got["status"], got["error"]), ("failed", "Cancelled by the admin"))
        self.assertTrue(f.exists())  # source kept so the admin can relaunch it

    def test_progress_is_monotonic_and_reaches_one(self):
        f = self.dir / "prog.md"
        f.write_text("\n\n".join(f"# Seccion {i}\n\n" + "Texto largo. " * 600 for i in range(4)))
        job = jq.enqueue("t@x.org", "es", ["en", "fr"], "tier1", str(f), mode="immediate", origin="api",
                         options={"connection_id": "solo"})
        seen: list[float] = []
        orig_mark = jq.mark_progress
        jq.mark_progress = lambda jid, done, total, fraction=None: (seen.append(fraction), orig_mark(jid, done, total, fraction))[1]
        orig_chat = llm.chat_with_fallback

        async def fake(messages, chain):
            return messages[-1]["content"].split("--- Text to translate ---\n", 1)[-1]
        llm.chat_with_fallback = fake
        try:
            asyncio.run(jq.process_job(job))
        finally:
            jq.mark_progress = orig_mark
            llm.chat_with_fallback = orig_chat
        fractions = [x for x in seen if x is not None]
        self.assertEqual(fractions, sorted(fractions))
        self.assertTrue(any(0 < x < 1 for x in fractions), fractions)  # intermediate values, not just per-language
        self.assertEqual(jq.get(job["id"])["progress"]["fraction"], 1.0)

    def test_connection_capacity_setting(self):
        from src.services.connection_registry import capacity
        self.assertEqual(capacity(connections.get("solo")), 1)
        self.assertEqual(capacity(connections.get("wide")), 2)
        connections.update("wide", {"max_concurrent": 999})
        self.assertEqual(capacity(connections.get("wide")), 32)  # clamped
        connections.update("wide", {"max_concurrent": 2})


if __name__ == "__main__":
    unittest.main()
