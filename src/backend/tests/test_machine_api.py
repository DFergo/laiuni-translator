"""Sprint 22: machine API (SPEC §16) — tokens, auth, /translate, /jobs, Markdown guarantees.

Run inside the backend container:
    cd /app && python -m unittest src.tests.test_machine_api -v
"""

import asyncio
import os
import tempfile
import unittest

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

        async def fake_chat(messages, chain):
            if "ISO 639-1" in messages[0]["content"]:
                return "es"
            text = messages[-1]["content"].split("--- Text to translate ---\n", 1)[-1]
            return text.replace("Titulo", "Title").replace("Ver", "See")
        llm.chat_with_fallback = fake_chat

    @classmethod
    def tearDownClass(cls):
        llm.chat_with_fallback = cls._orig_chat

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
        res = self.client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
        self.assertEqual(res.headers["content-type"], "application/zip")
        usage = {u["email"]: u for u in jq.usage_summary()}
        self.assertEqual(usage["api:skill"]["origin"], "api")

        # another token cannot see it
        other, _ = api_tokens.create("other")
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"}).status_code, 404)

    def test_job_rejects_bad_input(self):
        r = self.client.post("/api/v1/jobs", headers=self.auth, data={"target_langs": "en"},
                             files={"file": ("a.exe", b"x")})
        self.assertEqual(r.status_code, 415)

    def test_openapi_lists_contract(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for p in ("/api/v1/translate", "/api/v1/languages", "/api/v1/jobs", "/api/v1/jobs/{job_id}",
                  "/api/v1/jobs/{job_id}/result", "/admin/api-tokens"):
            self.assertIn(p, paths)


if __name__ == "__main__":
    unittest.main()
