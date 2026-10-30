"""Tests for signed backend → frontend calls (services/frontend_client.py) and
the frontend credentials in the admin API.

Run inside the backend container:
    cd /app && python -m unittest src.tests.test_frontend_signing -v
"""

import asyncio
import os
import tempfile
import unittest

_TMP = tempfile.TemporaryDirectory()
os.environ["LAIUNI_DATA_DIR"] = _TMP.name
os.environ.pop("TRANSLATOR_FRONTEND_SECRET", None)

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from src.services import frontend_client  # noqa: E402
from src.services import frontend_registry as reg  # noqa: E402
from src.api.v1.admin import frontends as fe  # noqa: E402

SECRET = "k" * 48
GLOBAL = "g" * 48


class _GlobalSecret:
    """Context manager: set/unset TRANSLATOR_FRONTEND_SECRET for one test."""

    def __init__(self, value: str | None):
        self.value = value

    def __enter__(self):
        self.saved = os.environ.pop("TRANSLATOR_FRONTEND_SECRET", None)
        if self.value is not None:
            os.environ["TRANSLATOR_FRONTEND_SECRET"] = self.value

    def __exit__(self, *a):
        os.environ.pop("TRANSLATOR_FRONTEND_SECRET", None)
        if self.saved is not None:
            os.environ["TRANSLATOR_FRONTEND_SECRET"] = self.saved


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Capture:
    """httpx MockTransport that records the last request."""

    def __init__(self, status: int = 200):
        self.requests: list[httpx.Request] = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": True})


class SignTest(unittest.TestCase):
    def test_shared_vector(self):
        # Same vector as src/frontend/sidecar/tests/test_backend_surface.py
        body = b'{"token":"AB12-CD34","status":"not_found","data":null}'
        sig = frontend_client.sign("0123456789abcdef0123456789abcdef", "1767225600", "n-0001", "POST",
                                   "/backend/v1/session/AB12-CD34/recovery-data", body)
        self.assertEqual(sig, "v1=c8cfb97d1391eebf7dab6c476c36fd64c7594c11204ef2ef1411b478e23c5a02")


class RegistryAuthTest(unittest.TestCase):
    def setUp(self):
        reg.registry._frontends = {}
        frontend_client._warned.clear()

    def tearDown(self):
        reg.registry._frontends = {}

    def _client(self, cap: _Capture) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(cap), auth=frontend_client._RegistryAuth())

    def test_signed_frontend_rewritten_and_signed(self):
        f = reg.registry.register("https://fe1-backend.example.org", "VPS")
        reg.registry.update(f["id"], signing_secret=SECRET,
                            extra_headers={"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "sec"})
        cap = _Capture()

        async def go():
            async with self._client(cap) as c:
                await c.post("https://fe1-backend.example.org/internal/jobs/R-1/status", json={"ref": "R-1", "status": "queued"})
        _run(go())

        req = cap.requests[0]
        self.assertEqual(req.url.path, "/backend/v1/jobs/R-1/status")
        self.assertEqual(req.headers["CF-Access-Client-Id"], "id.access")
        expected = frontend_client.sign(SECRET, req.headers["X-HRDD-Timestamp"], req.headers["X-HRDD-Nonce"],
                                        "POST", "/backend/v1/jobs/R-1/status", req.content)
        self.assertEqual(req.headers["X-HRDD-Signature"], expected)

    def test_multipart_body_is_signed(self):
        f = reg.registry.register("http://10.0.0.20:8081", "LAN")
        reg.registry.update(f["id"], signing_secret=SECRET)
        cap = _Capture()

        async def go():
            async with self._client(cap) as c:
                await c.post("http://10.0.0.20:8081/internal/branding-logo", data={"mode": "white"},
                             files={"color": ("logo.png", b"\x89PNG...", "image/png")})
        _run(go())
        req = cap.requests[0]
        expected = frontend_client.sign(SECRET, req.headers["X-HRDD-Timestamp"], req.headers["X-HRDD-Nonce"],
                                        "POST", "/backend/v1/branding-logo", req.content)
        self.assertEqual(req.headers["X-HRDD-Signature"], expected)

    def test_unsigned_frontend_left_untouched(self):
        reg.registry.register("http://10.0.0.30:8090", "legacy")
        cap = _Capture()

        async def go():
            async with self._client(cap) as c:
                await c.get("http://10.0.0.30:8090/internal/queue")
        _run(go())
        req = cap.requests[0]
        self.assertEqual(req.url.path, "/internal/queue")
        self.assertNotIn("X-HRDD-Signature", req.headers)

    def test_unknown_url_untouched(self):
        cap = _Capture()

        async def go():
            async with self._client(cap) as c:
                await c.get("http://elsewhere:1234/internal/queue")
        _run(go())
        self.assertNotIn("X-HRDD-Signature", cap.requests[0].headers)

    def test_prefix_match_does_not_cross_ports(self):
        f = reg.registry.register("http://h:808", "A")
        reg.registry.update(f["id"], signing_secret=SECRET)
        cap = _Capture()

        async def go():
            async with self._client(cap) as c:
                await c.get("http://h:8081/internal/queue")
        _run(go())
        self.assertNotIn("X-HRDD-Signature", cap.requests[0].headers)


class ModeTest(unittest.TestCase):
    """Global secret fallback, trusted-network (unsigned) and legacy modes."""

    def setUp(self):
        reg.registry._frontends = {}
        frontend_client._warned.clear()

    def tearDown(self):
        reg.registry._frontends = {}

    def _send(self, url: str, method: str = "GET", **kw) -> httpx.Request:
        cap = _Capture()

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(cap), auth=frontend_client._RegistryAuth()) as c:
                await c.request(method, url, **kw)
        _run(go())
        return cap.requests[0]

    def test_signed_uses_global_secret_when_no_own(self):
        f = reg.registry.register("http://fe:8080", "A")
        reg.registry.update(f["id"], auth_mode="signed")
        with _GlobalSecret(GLOBAL):
            req = self._send("http://fe:8080/internal/queue")
        self.assertEqual(req.url.path, "/backend/v1/queue")
        expected = frontend_client.sign(GLOBAL, req.headers["X-HRDD-Timestamp"], req.headers["X-HRDD-Nonce"],
                                        "GET", "/backend/v1/queue", b"")
        self.assertEqual(req.headers["X-HRDD-Signature"], expected)

    def test_own_secret_wins_over_global(self):
        f = reg.registry.register("http://fe:8080", "A")
        reg.registry.update(f["id"], auth_mode="signed", signing_secret=SECRET)
        with _GlobalSecret(GLOBAL):
            req = self._send("http://fe:8080/internal/queue")
        expected = frontend_client.sign(SECRET, req.headers["X-HRDD-Timestamp"], req.headers["X-HRDD-Nonce"],
                                        "GET", "/backend/v1/queue", b"")
        self.assertEqual(req.headers["X-HRDD-Signature"], expected)

    def test_signed_without_any_secret_fails_closed(self):
        f = reg.registry.register("http://fe:8080", "A")
        reg.registry.update(f["id"], auth_mode="signed")
        with _GlobalSecret(None):
            with self.assertRaises(frontend_client.MissingSigningSecret):
                self._send("http://fe:8080/internal/queue")

    def test_short_global_secret_ignored(self):
        with _GlobalSecret("short"):
            self.assertEqual(frontend_client.global_secret(), "")

    def test_unsigned_mode_rewrites_without_signature(self):
        f = reg.registry.register("http://fe:8080", "A")
        reg.registry.update(f["id"], auth_mode="unsigned", extra_headers={"X-Extra": "1"})
        with _GlobalSecret(GLOBAL):
            req = self._send("http://fe:8080/internal/jobs/R-1/status", "POST", json={"ref": "R-1", "status": "done"})
        self.assertEqual(req.url.path, "/backend/v1/jobs/R-1/status")
        self.assertNotIn("X-HRDD-Signature", req.headers)
        self.assertEqual(req.headers["X-Extra"], "1")

    def test_existing_entries_keep_their_behaviour_with_global_secret(self):
        # Registered before modes existed: no secret -> legacy (old image keeps working
        # even after TRANSLATOR_FRONTEND_SECRET is added); own secret -> signed.
        reg.registry.register("http://old:8090", "old")
        f = reg.registry.register("http://new:8080", "new")
        reg.registry.update(f["id"], signing_secret=SECRET)
        with _GlobalSecret(GLOBAL):
            old = self._send("http://old:8090/internal/queue")
            new = self._send("http://new:8080/internal/queue")
        self.assertEqual(old.url.path, "/internal/queue")
        self.assertNotIn("X-HRDD-Signature", old.headers)
        self.assertEqual(new.url.path, "/backend/v1/queue")
        self.assertIn("X-HRDD-Signature", new.headers)


class AdminCredentialsTest(unittest.TestCase):
    def setUp(self):
        reg.registry._frontends = {}
        self._orig_probe = fe._probe
        self.probed: list[tuple] = []

        async def fake_probe(url, entry):
            self.probed.append((url, dict(entry)))
        fe._probe = fake_probe

    def tearDown(self):
        fe._probe = self._orig_probe
        reg.registry._frontends = {}

    def test_register_with_credentials_hides_secret(self):
        res = _run(fe.register_frontend(fe.RegisterRequest(
            url="https://fe1-backend.example.org/", name="VPS", signing_secret=SECRET,
            extra_headers={"CF-Access-Client-Id": "a", "CF-Access-Client-Secret": "b"}), _={}))
        view = res["frontend"]
        self.assertTrue(view["signing_enabled"])
        self.assertEqual(view["extra_header_names"], ["CF-Access-Client-Id", "CF-Access-Client-Secret"])
        self.assertNotIn("signing_secret", view)
        self.assertNotIn("extra_headers", view)
        self.assertEqual(self.probed[0][1]["signing_secret"], SECRET)  # probe used the secret
        self.assertEqual(view["auth_mode"], "signed")
        self.assertEqual(view["signing_source"], "own")
        stored = reg.registry.get(view["id"])
        self.assertEqual(stored["signing_secret"], SECRET)
        listed = _run(fe.list_frontends(_={}))["frontends"][0]
        self.assertNotIn("signing_secret", listed)

    def test_short_secret_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            _run(fe.register_frontend(fe.RegisterRequest(url="http://a:8081", signing_secret="short"), _={}))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_legacy_entry_gets_secret_later(self):
        fid = reg.registry.register("http://10.0.0.30:8090", "legacy")["id"]
        self.assertFalse(fe._public_view(reg.registry.get(fid))["signing_enabled"])
        self.assertEqual(fe._public_view(reg.registry.get(fid))["auth_mode"], "legacy")
        res = _run(fe.update_frontend(fid, fe.UpdateRequest(url="http://10.0.0.30:8081", auth_mode="signed", signing_secret=SECRET), verify=True, _={}))
        self.assertTrue(res["frontend"]["signing_enabled"])
        url, entry = self.probed[-1]
        self.assertEqual(url, "http://10.0.0.30:8081")
        self.assertEqual((entry["auth_mode"], entry["signing_secret"]), ("signed", SECRET))

    def test_register_address_only_with_installation_secret(self):
        with _GlobalSecret(GLOBAL):
            res = _run(fe.register_frontend(fe.RegisterRequest(url="http://translator-frontend:8080"), _={}))
            listed = _run(fe.list_frontends(_={}))
        view = res["frontend"]
        self.assertEqual((view["auth_mode"], view["signing_source"], view["signing_enabled"]), ("signed", "global", True))
        self.assertTrue(listed["global_secret_configured"])

    def test_register_signed_without_any_secret_rejected(self):
        with _GlobalSecret(None):
            with self.assertRaises(HTTPException) as ctx:
                _run(fe.register_frontend(fe.RegisterRequest(url="http://a:8080"), _={}))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.probed, [])

    def test_register_trusted_network(self):
        with _GlobalSecret(None):
            res = _run(fe.register_frontend(fe.RegisterRequest(url="http://a:8080", auth_mode="unsigned"), _={}))
        self.assertEqual(res["frontend"]["auth_mode"], "unsigned")
        self.assertFalse(res["frontend"]["signing_enabled"])

    def test_bad_mode_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            _run(fe.register_frontend(fe.RegisterRequest(url="http://a:8080", auth_mode="open"), _={}))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_removing_own_secret_keeps_signed_mode(self):
        # Entry from before modes existed (secret, no auth_mode): removing the own secret
        # must fall back to the installation secret, not silently switch to legacy.
        fid = reg.registry.register("http://a:8080", "A")["id"]
        reg.registry.update(fid, signing_secret=SECRET)
        with _GlobalSecret(GLOBAL):
            res = _run(fe.update_frontend(fid, fe.UpdateRequest(signing_secret=""), verify=True, _={}))
        self.assertEqual((res["frontend"]["auth_mode"], res["frontend"]["signing_source"]), ("signed", "global"))

    def test_reconciler_url_edit_does_not_touch_mode(self):
        fid = reg.registry.register("http://a:8080", "A")["id"]
        _run(fe.update_frontend(fid, fe.UpdateRequest(url="http://b:8080"), verify=False, _={}))
        self.assertNotIn("auth_mode", reg.registry.get(fid))

    def test_public_url_saved_and_shown(self):
        with _GlobalSecret(GLOBAL):
            res = _run(fe.register_frontend(fe.RegisterRequest(
                url="http://10.0.0.5:8180", public_url="https://translate.example.org/"), _={}))
            fid = res["frontend"]["id"]
            self.assertEqual(res["frontend"]["public_url"], "https://translate.example.org")
            _run(fe.update_frontend(fid, fe.UpdateRequest(public_url=""), verify=True, _={}))
        self.assertEqual(reg.registry.get(fid)["public_url"], "")
        self.assertEqual(len(self.probed), 1)  # public_url alone does not re-probe

    def test_name_only_update_does_not_probe(self):
        fid = reg.registry.register("http://a:8081", "old")["id"]
        _run(fe.update_frontend(fid, fe.UpdateRequest(name="new"), verify=True, _={}))
        self.assertEqual(self.probed, [])


class ArtifactSizeTest(unittest.TestCase):
    """An oversize result is reported to the sidecar, never pushed (SPEC §14.4)."""

    def setUp(self):
        from src.services import job_channel
        self.jc = job_channel
        self.saved = job_channel.MAX_ARTIFACT_BYTES, job_channel.DOCUMENTS_DIR
        self.tmp = tempfile.TemporaryDirectory()
        job_channel.DOCUMENTS_DIR = __import__("pathlib").Path(self.tmp.name)
        (job_channel.DOCUMENTS_DIR / "J1").mkdir()
        (job_channel.DOCUMENTS_DIR / "J1" / "doc.es.docx").write_bytes(os.urandom(4096))
        self.job = {"id": "J1", "client_ref": "R-1", "status": "done", "progress": {}, "estimate_s": 0,
                    "run_at": None, "error": None}

    def tearDown(self):
        self.jc.MAX_ARTIFACT_BYTES, self.jc.DOCUMENTS_DIR = self.saved
        self.tmp.cleanup()

    def _push(self, status: int = 200) -> list[httpx.Request]:
        cap = _Capture(status)

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(cap)) as c:
                return await self.jc._push_artifact(c, "http://fe:8080", "R-1", self.job)
        self.assertTrue(_run(go()))
        return cap.requests

    def test_within_limit_pushes_zip(self):
        reqs = self._push()
        self.assertEqual(reqs[0].url.path, "/internal/jobs/R-1/artifact")

    def test_over_limit_reports_instead(self):
        self.jc.MAX_ARTIFACT_BYTES = 1024
        reqs = self._push()
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].url.path, "/internal/jobs/R-1/status")
        body = __import__("json").loads(reqs[0].content)
        self.assertEqual(body["download_error"]["limit_mb"], 0)
        self.assertEqual(body["status"], "done")

    def test_frontend_413_reported(self):
        reqs = self._push(status=413)
        self.assertEqual([r.url.path for r in reqs], ["/internal/jobs/R-1/artifact", "/internal/jobs/R-1/status"])


if __name__ == "__main__":
    unittest.main()
