"""Editing a frontend's URL in place (preserving id + campaign config).

Run inside the backend container:
    cd /app && python -m unittest src.tests.test_frontends_update -v
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from src.api.v1.admin import frontends as frontends_api
from src.services.frontend_registry import FrontendRegistry


def _fake_registry(entries):
    reg = FrontendRegistry.__new__(FrontendRegistry)
    reg._frontends = dict(entries)
    reg._save = lambda: None  # no disk I/O in tests
    return reg


class _FakeResponse:
    def __init__(self, ok=True):
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("unreachable")


class _FakeClient:
    def __init__(self, ok=True):
        self._ok = ok

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if not self._ok:
            raise RuntimeError("connection failed")
        return _FakeResponse(ok=True)


class UpdateFrontendUrlTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = _fake_registry({
            "fid1": {"id": "fid1", "url": "http://10.0.0.1:8091", "name": "one",
                      "enabled": True, "status": "online", "last_seen": None, "created_at": "x"},
            "fid2": {"id": "fid2", "url": "http://10.0.0.2:8091", "name": "two",
                      "enabled": True, "status": "online", "last_seen": None, "created_at": "x"},
        })
        self._patcher = patch.object(frontends_api, "registry", self.registry)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    async def _call(self, fid, req_kwargs, verify=True):
        req = frontends_api.UpdateRequest(**req_kwargs)
        return await frontends_api.update_frontend(fid, req, verify=verify, _={})

    async def test_success_preserves_id_and_normalises_url(self):
        with patch.object(frontends_api, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = _FakeClient(ok=True)
            result = await self._call("fid1", {"url": "http://10.0.0.99:8091/"})
        self.assertEqual(result["frontend"]["id"], "fid1")
        self.assertEqual(result["frontend"]["url"], "http://10.0.0.99:8091")
        self.assertEqual(result["frontend"]["name"], "one")  # untouched

    async def test_unreachable_raises_400(self):
        with patch.object(frontends_api, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = _FakeClient(ok=False)
            with self.assertRaises(HTTPException) as ctx:
                await self._call("fid1", {"url": "http://10.0.0.99:8091"})
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_verify_false_skips_reachability(self):
        with patch.object(frontends_api, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = _FakeClient(ok=False)  # would fail if called
            result = await self._call("fid1", {"url": "http://10.0.0.99:8091"}, verify=False)
        self.assertEqual(result["frontend"]["url"], "http://10.0.0.99:8091")
        mock_httpx.AsyncClient.assert_not_called()

    async def test_collision_raises_409(self):
        with patch.object(frontends_api, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = _FakeClient(ok=True)
            with self.assertRaises(HTTPException) as ctx:
                await self._call("fid1", {"url": "http://10.0.0.2:8091"})
        self.assertEqual(ctx.exception.status_code, 409)
        mock_httpx.AsyncClient.assert_not_called()  # collision checked before reachability

    async def test_collision_raises_409_even_with_verify_false(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call("fid1", {"url": "http://10.0.0.2:8091"}, verify=False)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_name_only_update_unaffected(self):
        with patch.object(frontends_api, "httpx") as mock_httpx:
            result = await self._call("fid1", {"name": "renamed"})
        self.assertEqual(result["frontend"]["name"], "renamed")
        self.assertEqual(result["frontend"]["url"], "http://10.0.0.1:8091")  # unchanged
        mock_httpx.AsyncClient.assert_not_called()

    async def test_unknown_id_raises_404(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call("missing", {"name": "x"})
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
