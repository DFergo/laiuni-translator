"""Tests for the two sidecar surfaces and the backend-surface signature.

Run inside the frontend container (or any Python 3.11 env with the sidecar deps + httpx):
    cd /app && python -m unittest sidecar.tests.test_backend_surface -v
"""

import os
import secrets as pysecrets
import time
import unittest

SECRET = "s" * 40
PREVIOUS = "p" * 40
os.environ["TRANSLATOR_BACKEND_SECRET"] = SECRET
os.environ["TRANSLATOR_BACKEND_SECRET_PREVIOUS"] = PREVIOUS
os.environ.pop("ALLOW_UNSIGNED_BACKEND_SURFACE", None)
os.environ.pop("BACKEND_SURFACE_AUTH", None)

from fastapi import FastAPI, Form  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sidecar import backend_auth  # noqa: E402
from sidecar import main as sidecar_main  # noqa: E402
from sidecar.main import app, backend_app  # noqa: E402


def signed_headers(method: str, path_qs: str, body: bytes = b"", secret: str = SECRET,
                   ts: int | None = None, nonce: str | None = None) -> dict[str, str]:
    ts_s = str(int(time.time()) if ts is None else ts)
    nonce = nonce or pysecrets.token_urlsafe(18)
    return {
        "X-HRDD-Timestamp": ts_s,
        "X-HRDD-Nonce": nonce,
        "X-HRDD-Signature": backend_auth.sign(secret, ts_s, nonce, method, path_qs, body),
    }


class SignatureVectorTest(unittest.TestCase):
    """Shared vector — the backend client and the forks must produce the same value."""

    def test_vector(self):
        body = b'{"token":"AB12-CD34","status":"not_found","data":null}'
        sig = backend_auth.sign("0123456789abcdef0123456789abcdef", "1767225600", "n-0001", "POST",
                                "/backend/v1/session/AB12-CD34/recovery-data", body)
        self.assertEqual(sig, "v1=c8cfb97d1391eebf7dab6c476c36fd64c7594c11204ef2ef1411b478e23c5a02")


class BackendSurfaceTest(unittest.TestCase):
    def setUp(self):
        # The middleware is built lazily per TestClient app instance; force a fresh one
        # (fresh nonce cache, start time) for each test.
        backend_app.middleware_stack = None
        self.client = TestClient(backend_app)
        # Build the middleware now (records its start time) so every signature
        # made inside a test is not "signed before the process started".
        self.client.get("/backend/v1/health")

    def test_unsigned_rejected(self):
        r = self.client.get("/backend/v1/queue")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"detail": "Unauthorized"})

    def test_signed_get_ok(self):
        r = self.client.get("/backend/v1/queue", headers=signed_headers("GET", "/backend/v1/queue"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["surface_auth"], "signed")  # reported to the backend admin

    def test_signed_with_query_ok(self):
        h = signed_headers("GET", "/backend/v1/config?probe=1")
        r = self.client.get("/backend/v1/config?probe=1", headers=h)
        self.assertEqual(r.status_code, 200)

    def test_query_not_covered_rejected(self):
        h = signed_headers("GET", "/backend/v1/config")
        r = self.client.get("/backend/v1/config?probe=1", headers=h)
        self.assertEqual(r.status_code, 401)

    def test_replay_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue")
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)

    def test_stale_timestamp_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue", ts=int(time.time()) - 600)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)

    def test_wrong_secret_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue", secret="x" * 40)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)

    def test_previous_secret_accepted(self):
        h = signed_headers("GET", "/backend/v1/queue", secret=PREVIOUS)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 200)

    def test_tampered_body_rejected(self):
        body = b'{"ref":"R-1","status":"queued"}'
        h = signed_headers("POST", "/backend/v1/jobs/R-1/status", body)
        r = self.client.post("/backend/v1/jobs/R-1/status", content=b'{"ref":"R-1","status":"done"}',
                             headers={**h, "content-type": "application/json"})
        self.assertEqual(r.status_code, 401)

    def test_signed_json_post_ok(self):
        body = b'{"ref":"R-1","status":"queued"}'
        h = signed_headers("POST", "/backend/v1/jobs/R-1/status", body)
        r = self.client.post("/backend/v1/jobs/R-1/status", content=body,
                             headers={**h, "content-type": "application/json"})
        self.assertEqual(r.status_code, 200)

    def test_signed_artifact_post_ok(self):
        body = b"PK\x03\x04" + bytes(range(256)) * 64  # raw zip body, read via request.body()
        h = signed_headers("POST", "/backend/v1/jobs/R-2/artifact", body)
        r = self.client.post("/backend/v1/jobs/R-2/artifact", content=body,
                             headers={**h, "content-type": "application/zip"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(sidecar_main._artifacts.pop("R-2"), body)

    def test_oversize_body_413(self):
        saved = backend_auth.MAX_BODY_BYTES
        backend_auth.MAX_BODY_BYTES = 1024
        try:
            body = b"x" * 2048
            h = signed_headers("POST", "/backend/v1/jobs/R-3/artifact", body)
            r = self.client.post("/backend/v1/jobs/R-3/artifact", content=body,
                                 headers={**h, "content-type": "application/zip"})
            self.assertEqual(r.status_code, 413)
        finally:
            backend_auth.MAX_BODY_BYTES = saved

    def test_signed_before_start_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue", ts=int(time.time()) - 30)  # inside the window
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)


class PublicSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_browser_routes_work(self):
        self.assertEqual(self.client.get("/internal/config").status_code, 200)
        self.assertEqual(self.client.get("/internal/health").status_code, 200)
        self.assertEqual(self.client.get("/languages").status_code, 200)
        self.assertEqual(self.client.post("/request-token", json={"email": "a@example.org"}).status_code, 200)
        self.assertEqual(self.client.get("/jobs/R-9").json()["status"], "pending")

    def test_download_reports_too_large(self):
        sidecar_main._jobs["R-4"] = {"ref": "R-4", "status": "done",
                                     "download_error": {"size_mb": 600, "limit_mb": 512}}
        r = self.client.get("/jobs/R-4/download")
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json()["detail"], {"error": "too_large", "size_mb": 600, "limit_mb": 512})
        sidecar_main._jobs["TOKEN-1"] = {"download_error": {"size_mb": 600, "limit_mb": 512}}
        r = self.client.get("/d/TOKEN-1")
        self.assertEqual(r.status_code, 413)
        self.assertIn("600 MB", r.json()["detail"])

    def test_removed_routes_absent(self):
        # Inherited routes with no caller in Translator are gone from both surfaces
        for method, path in [
            ("POST", "/internal/queue"), ("GET", "/internal/stream/T-1"),
            ("POST", "/internal/session/recover"), ("GET", "/internal/session/T-1/recover"),
            ("POST", "/internal/auth/request-code"), ("POST", "/internal/auth/verify-code"),
            ("GET", "/internal/auth/status/T-1"), ("POST", "/internal/upload/T-1"),
            ("DELETE", "/internal/evidence/T-1/x.pdf"),
        ]:
            r = self.client.request(method, path, json={} if method == "POST" else None)
            self.assertIn(r.status_code, (404, 405), f"{method} {path} -> {r.status_code}")

    def test_backend_routes_absent_on_public_app(self):
        # Old backend-only routes are gone from the public surface
        for method, path in [
            ("GET", "/internal/queue"), ("GET", "/internal/uploads"),
            ("POST", "/internal/frontend-config"), ("POST", "/internal/branding"),
            ("POST", "/internal/languages"), ("POST", "/internal/jobs/R-1/status"),
            ("POST", "/internal/jobs/R-1/artifact"), ("POST", "/internal/session/AB12-CD34/recovery-data"),
            ("POST", "/internal/stream/AB12-CD34/chunk"), ("POST", "/internal/auth/AB12-CD34/result"),
            ("GET", "/internal/upload/AB12-CD34/x.pdf"), ("DELETE", "/internal/upload/AB12-CD34/x.pdf"),
            ("GET", "/backend/v1/queue"), ("GET", "/backend/v1/config"),
        ]:
            r = self.client.request(method, path, json={} if method == "POST" else None)
            self.assertIn(r.status_code, (404, 405), f"{method} {path} -> {r.status_code}")


class ModeTest(unittest.TestCase):
    """Middleware configuration edge cases, on a minimal app."""

    def _client(self, **env):
        saved = {k: os.environ.get(k) for k in ("TRANSLATOR_BACKEND_SECRET", "TRANSLATOR_BACKEND_SECRET_PREVIOUS", "ALLOW_UNSIGNED_BACKEND_SURFACE", "BACKEND_SURFACE_AUTH")}
        try:
            for k in saved:
                os.environ.pop(k, None)
            os.environ.update(env)
            mini = FastAPI()
            mini.add_middleware(backend_auth.BackendSignatureMiddleware)

            @mini.post("/backend/v1/echo")
            async def echo(x: str = Form("")):
                return {"x": x}

            client = TestClient(mini)
            client.post("/backend/v1/echo")  # build the middleware with this env
            return client
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_no_secret_rejects_even_signed(self):
        c = self._client()
        self.assertEqual(c.post("/backend/v1/echo", headers=signed_headers("POST", "/backend/v1/echo")).status_code, 401)

    def test_short_secret_ignored(self):
        c = self._client(TRANSLATOR_BACKEND_SECRET="short")
        h = signed_headers("POST", "/backend/v1/echo", secret="short")
        self.assertEqual(c.post("/backend/v1/echo", headers=h).status_code, 401)

    def test_signed_multipart_post_ok(self):
        # Body is buffered by the middleware and replayed to the multipart parser.
        c = self._client(TRANSLATOR_BACKEND_SECRET=SECRET)
        boundary = "testboundary"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"x\"\r\n\r\nok\r\n"
                f"--{boundary}--\r\n").encode()
        h = signed_headers("POST", "/backend/v1/echo", body)
        r = c.post("/backend/v1/echo", content=body,
                   headers={**h, "content-type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"x": "ok"})

    def test_allow_unsigned_dev_switch(self):
        c = self._client(ALLOW_UNSIGNED_BACKEND_SURFACE="true")
        r = c.post("/backend/v1/echo", data={"x": "ok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"x": "ok"})

    def test_trusted_network_mode(self):
        c = self._client(BACKEND_SURFACE_AUTH="trusted-network")
        r = c.post("/backend/v1/echo", data={"x": "ok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"x": "ok"})

    def test_trusted_network_does_not_need_a_secret(self):
        c = self._client(BACKEND_SURFACE_AUTH="trusted-network", TRANSLATOR_BACKEND_SECRET="")
        self.assertEqual(c.post("/backend/v1/echo").status_code, 200)

    def test_unknown_mode_falls_back_to_signed(self):
        c = self._client(BACKEND_SURFACE_AUTH="yolo", TRANSLATOR_BACKEND_SECRET=SECRET)
        self.assertEqual(c.post("/backend/v1/echo").status_code, 401)

    def test_surface_mode_reporting(self):
        for env, expected in (({}, "signed"), ({"BACKEND_SURFACE_AUTH": "trusted-network"}, "trusted-network"),
                              ({"ALLOW_UNSIGNED_BACKEND_SURFACE": "true"}, "trusted-network"),
                              ({"BACKEND_SURFACE_AUTH": "signed", "ALLOW_UNSIGNED_BACKEND_SURFACE": "true"}, "signed")):
            saved = {k: os.environ.pop(k, None) for k in ("BACKEND_SURFACE_AUTH", "ALLOW_UNSIGNED_BACKEND_SURFACE")}
            try:
                os.environ.update(env)
                self.assertEqual(backend_auth.surface_mode(), expected, env)
            finally:
                for k in ("BACKEND_SURFACE_AUTH", "ALLOW_UNSIGNED_BACKEND_SURFACE"):
                    os.environ.pop(k, None)
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
