"""Tests for ops/translator_mcp.py — standard library only.

    python3 -m unittest discover -s ops/tests -v

A fake backend (http.server) records every request, so the gates can be checked:
nothing reaches the server without apply / confirmations, and no secret comes back
to the chat.
"""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_HOME = tempfile.TemporaryDirectory()
os.environ["TRANSLATOR_OPS_HOME"] = _HOME.name
OPS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(OPS))

import translator_mcp as m  # noqa: E402

API_KEY = "sk-real-key-0123456789abcdef"
TEMP_TOKEN = "lt_temporary-smoke-token-0123456789"


class Fake(BaseHTTPRequestHandler):
    requests: list = []
    admin_exists = False
    translate_status = 200
    job_final = "done"

    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        Fake.requests.append((self.command, self.path, body, dict(self.headers)))
        return body

    def do_GET(self):
        self._record()
        if self.path == "/admin/status":
            return self._send(200, {"setup_complete": Fake.admin_exists})
        if self.path.startswith("/api/v1/jobs/"):
            if self.headers.get("Authorization") != f"Bearer {TEMP_TOKEN}":
                return self._send(401, {"detail": "no"})
            return self._send(200, {"job_id": "J1", "status": Fake.job_final, "error": None})
        if self.headers.get("Authorization") != "Bearer TOKEN":
            return self._send(401, {"detail": "no"})
        if self.path == "/admin/llm/connections":
            return self._send(200, {"connections": [{"id": "x", "api_key": API_KEY}]})
        return self._send(200, {"ok": True, "path": self.path})

    def do_POST(self):
        body = self._record()
        if self.path == "/admin/setup":
            Fake.admin_exists = True
            return self._send(200, {"status": "ok"})
        if self.path == "/admin/login":
            return self._send(200, {"token": "TOKEN", "expires_in": 3600})
        if self.path == "/admin/api-tokens":
            return self._send(200, {"token": TEMP_TOKEN, "id": "t1", "name": "smoke", "scope": "translate"})
        if self.path == "/api/v1/translate":
            if self.headers.get("Authorization") != f"Bearer {TEMP_TOKEN}":
                return self._send(401, {"detail": "no"})
            if Fake.translate_status != 200:
                return self._send(Fake.translate_status, {"detail": "boom"})
            return self._send(200, {"translated_text": "# Prueba de instalación", "model": "m1",
                                    "usage": {"calls": 1}, "warnings": []})
        if self.path == "/api/v1/jobs":
            return self._send(200, {"job_id": "J1", "status": "queued", "estimate_s": 1, "duplicate": False})
        if "multipart/form-data" in self.headers.get("Content-Type", ""):
            return self._send(200, {"uploaded": True})
        return self._send(200, {"received": json.loads(body or b"{}")})

    do_PUT = do_POST

    def do_DELETE(self):
        self._record()
        self._send(200, {"deleted": True})


class McpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Fake.requests.clear()
        Fake.translate_status, Fake.job_final = 200, "done"
        self.tmp = Path(tempfile.mkdtemp())

    def call(self, name, **args):
        out = m._call_tool(name, args)
        return out["isError"], out["content"][0]["text"]

    def _login(self):
        self.assertFalse(self.call("backend_connect", url=self.url)[0])
        m._save_state({**m._state(), "tokens": {self.url: "TOKEN"}})

    # ------------------------------------------------------------ protocol

    def test_stdio_protocol(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "start"}},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "translator://guides/overview"}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"},
        ]
        r = subprocess.run([sys.executable, str(OPS / "translator_mcp.py")], input="\n".join(json.dumps(x) for x in msgs),
                           capture_output=True, text=True, timeout=30, env={**os.environ})
        replies = [json.loads(line) for line in r.stdout.splitlines()]
        self.assertEqual([x["id"] for x in replies], [1, 2, 3, 4, 5])          # no reply to the notification
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "laiuni-translator")
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertTrue({"check_machine", "deploy_prepare", "admin_api", "test_smoke", "guide"} <= names)
        self.assertIn("guide('overview')", replies[2]["result"]["messages"][0]["content"]["text"])
        self.assertIn("Ask before every change", replies[3]["result"]["contents"][0]["text"])
        self.assertEqual(replies[4]["error"]["code"], -32601)

    def test_every_guide_named_in_the_tools_exists(self):
        guides = {p.stem for p in (OPS / "guides").glob("*.md")}
        text = json.dumps(m.PROMPTS) + (OPS.parent / "SETUP-AGENT.md").read_text()
        text += " ".join(p.read_text() for p in (OPS / "guides").glob("*.md"))
        named = set(re.findall(r"guides? ?\(?['`]([a-z-]+)['`]", text))
        self.assertTrue(named)
        self.assertEqual(named - guides, set())

    def test_guides_do_not_leak_the_sister_app(self):
        for p in (OPS / "guides").glob("*.md"):
            text = p.read_text()
            self.assertNotRegex(text, r"HRDD_|hrdd-|/admin/rag|/admin/sessions|embedding", p.name)

    def test_topologies_have_their_deployment_folders(self):
        for name in m.TOPOLOGIES:
            self.assertTrue((m.DEPLOY / name / "docker-compose.yml").exists(), name)
            self.assertTrue((m.DEPLOY / name / ".env.example").exists(), name)

    # ------------------------------------------------------------ deployments

    def test_deploy_prepare_plans_then_writes_private_env_without_echoing_secrets(self):
        folder = self.tmp / "backend"
        err, plan = self.call("deploy_prepare", topology="backend", folder=str(folder))
        self.assertFalse(err)
        self.assertIn("planned", plan)
        self.assertFalse(folder.exists())                                   # nothing written without apply
        err, out = self.call("deploy_prepare", topology="backend", folder=str(folder), apply=True)
        self.assertFalse(err, out)
        env = m._read_env(folder / ".env")
        self.assertEqual(len(env["TRANSLATOR_FRONTEND_SECRET"]), 64)
        self.assertNotIn(env["TRANSLATOR_FRONTEND_SECRET"], out)            # never returned
        self.assertEqual(stat.S_IMODE((folder / ".env").stat().st_mode), 0o600)
        # A frontend can take the backend's secret by reference, without it entering the chat
        fe = self.tmp / "front"
        err, out = self.call("deploy_prepare", topology="t2-vps-tailscale", folder=str(fe), apply=True, values={
            "TAILSCALE_IP": "100.64.0.9", "TUNNEL_TOKEN": "tok",
            "TRANSLATOR_BACKEND_SECRET": f"env:{folder}/.env#TRANSLATOR_FRONTEND_SECRET"})
        self.assertFalse(err, out)
        self.assertEqual(m._read_env(fe / ".env")["TRANSLATOR_BACKEND_SECRET"], env["TRANSLATOR_FRONTEND_SECRET"])
        self.assertNotIn(env["TRANSLATOR_FRONTEND_SECRET"], out)
        # A folder with a deployment is never overwritten
        self.assertTrue(self.call("deploy_prepare", topology="backend", folder=str(folder), apply=True)[0])

    def test_t3_generates_one_shared_secret(self):
        folder = self.tmp / "t3"
        err, out = self.call("deploy_prepare", topology="t3-same-host", folder=str(folder), apply=True)
        self.assertFalse(err, out)
        self.assertEqual(len(m._read_env(folder / ".env")["TRANSLATOR_BACKEND_SECRET"]), 64)

    def test_build_from_source_points_at_the_repository(self):
        folder = self.tmp / "src-build"
        err, plan = self.call("deploy_prepare", topology="backend", folder=str(folder), build_from_source=True)
        self.assertIn("build-from-source.yml", plan)
        err, out = self.call("deploy_prepare", topology="backend", folder=str(folder), apply=True, build_from_source=True)
        self.assertFalse(err, out)
        override = (folder / "build-from-source.yml").read_text()
        self.assertIn(f"context: {m.REPO}", override)
        self.assertNotIn("context: ../..", override)
        self.assertTrue((m.REPO / "Dockerfile.backend").exists())
        self.assertTrue(self.call("deploy_prepare", topology="t1-lan", folder=str(self.tmp / "no"),
                                  build_from_source=True)[0])                # only the backend builds from source

    def test_unknown_env_keys_are_refused(self):
        err, out = self.call("deploy_prepare", topology="t1-lan", folder=str(self.tmp / "x"), values={"NOPE": "1"})
        self.assertTrue(err)
        self.assertIn("NOPE", out)

    def test_secret_reveal_needs_confirmation(self):
        self.call("deploy_prepare", topology="backend", folder=str(self.tmp / "b"), apply=True)
        self.assertTrue(self.call("secret_reveal", folder=str(self.tmp / "b"), key="TRANSLATOR_FRONTEND_SECRET")[0])
        err, out = self.call("secret_reveal", folder=str(self.tmp / "b"), key="TRANSLATOR_FRONTEND_SECRET",
                             confirm_reveal=True)
        self.assertFalse(err)
        self.assertEqual(len(out), 64)

    def test_compose_changes_need_apply(self):
        self.call("deploy_prepare", topology="backend", folder=str(self.tmp / "c"), apply=True)
        err, out = self.call("compose", folder=str(self.tmp / "c"), action="down")
        self.assertFalse(err)
        self.assertIn("planned", out)
        self.assertNotIn("-v", json.loads(out)["planned"].split())          # never removes volumes

    # ------------------------------------------------------------ admin API

    def test_admin_create_keeps_password_off_the_chat(self):
        Fake.admin_exists = False
        self.call("backend_connect", url=self.url)
        err, plan = self.call("admin_create")
        self.assertIn("planned", plan)
        self.assertFalse(any(r[1] == "/admin/setup" for r in Fake.requests))
        err, out = self.call("admin_create", apply=True)
        self.assertFalse(err, out)
        pw_file = Path(json.loads(out)["password_file"])
        password = pw_file.read_text().strip()
        self.assertNotIn(password, out)
        self.assertEqual(stat.S_IMODE(pw_file.stat().st_mode), 0o600)
        self.assertEqual(json.loads([r for r in Fake.requests if r[1] == "/admin/login"][0][2])["password"], password)

    def test_changes_are_planned_until_apply(self):
        self._login()
        err, out = self.call("admin_api", method="PUT", path="/admin/llm/settings", body={"translation_model": "m"})
        self.assertIn("planned", out)
        self.assertFalse(any(r[0] == "PUT" for r in Fake.requests))
        err, out = self.call("admin_api", method="PUT", path="/admin/llm/settings", body={"translation_model": "m"},
                             apply=True)
        self.assertFalse(err, out)
        self.assertTrue(any(r[0] == "PUT" for r in Fake.requests))

    def test_destructive_needs_confirmation(self):
        self._login()
        for method, path in (("DELETE", "/admin/frontends/abc"), ("POST", "/admin/queue/J1/cancel"),
                             ("POST", "/admin/prompts/reset-global"), ("POST", "/admin/import/global"),
                             ("DELETE", "/admin/api-tokens/t1")):
            err, out = self.call("admin_api", method=method, path=path, apply=True)
            self.assertTrue(err, path)
        self.assertEqual([r for r in Fake.requests if r[0] != "GET"], [])
        err, _ = self.call("admin_api", method="DELETE", path="/admin/frontends/abc", apply=True,
                           confirm_destructive=True)
        self.assertFalse(err)

    def test_exports_and_whitelist_export_need_content_confirmation(self):
        self._login()
        for path in ("/admin/export/global", "/admin/export/frontend/abc", "/admin/contacts/export"):
            self.assertTrue(self.call("admin_api", method="GET", path=path)[0], path)
        self.assertFalse(self.call("admin_api", method="GET", path="/admin/contacts")[0])
        self.assertFalse(self.call("admin_api", method="GET", path="/admin/queue")[0])
        self.assertFalse(self.call("admin_api", method="GET", path="/admin/export/global", confirm_content=True)[0])

    def test_admin_paths_only(self):
        self._login()
        self.assertTrue(self.call("admin_api", method="GET", path="/api/v1/jobs")[0])    # users' documents stay out of reach
        self.assertTrue(self.call("admin_api", method="GET", path="/etc/passwd")[0])

    def test_upload_gates_replacing_data(self):
        self._login()
        f = self.tmp / "glossary.json"
        f.write_text('{"terms": []}')
        err, plan = self.call("admin_upload", path="/admin/knowledge/glossary/upload", file=str(f))
        self.assertIn("planned", plan)
        err, out = self.call("admin_upload", path="/admin/knowledge/glossary/upload", file=str(f), apply=True)
        self.assertTrue(err)                                                  # replaces the glossary
        self.assertEqual([r for r in Fake.requests if r[0] == "POST"], [])
        err, out = self.call("admin_upload", path="/admin/knowledge/glossary/upload", file=str(f), apply=True,
                             confirm_destructive=True)
        self.assertFalse(err, out)
        sent = [r for r in Fake.requests if r[0] == "POST"][-1]
        self.assertIn(b'filename="glossary.json"', sent[2])
        self.assertIn("multipart/form-data", sent[3]["Content-Type"])

    def test_env_references_are_resolved_locally_and_secrets_masked(self):
        self._login()
        keys = self.tmp / "keys.env"
        keys.write_text(f"MISTRAL_API_KEY={API_KEY}\n")
        body = {"id": "mistral", "type": "openai", "base_url": "https://api.mistral.ai/v1",
                "api_key": f"env:{keys}#MISTRAL_API_KEY"}
        err, plan = self.call("admin_api", method="POST", path="/admin/llm/connections", body=body)
        self.assertNotIn(API_KEY, plan)
        err, out = self.call("admin_api", method="POST", path="/admin/llm/connections", body=body, apply=True)
        self.assertFalse(err, out)
        sent = json.loads([r for r in Fake.requests if r[0] == "POST"][-1][2])
        self.assertEqual(sent["api_key"], API_KEY)                          # the backend got the real key
        self.assertNotIn(API_KEY, out)                                      # the chat did not
        err, out = self.call("admin_api", method="GET", path="/admin/llm/connections")
        self.assertNotIn(API_KEY, out)

    def test_not_logged_in_is_explained(self):
        self.call("backend_connect", url=self.url)
        m._save_state({**m._state(), "tokens": {}})
        err, out = self.call("admin_api", method="GET", path="/admin/frontends")
        self.assertTrue(err)
        self.assertIn("login", out)

    # ------------------------------------------------------------ smoke test

    def test_smoke_translates_runs_a_job_and_revokes_its_token(self):
        self._login()
        Fake.requests.clear()
        err, out = self.call("test_smoke", frontend_id="fe1", target_lang="es", timeout_s=20)
        self.assertFalse(err, out)
        result = json.loads(out)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["reply"], "# Prueba de instalación")
        self.assertEqual(result["job_status"], "done")
        self.assertNotIn(TEMP_TOKEN, out)                                   # the throw-away token never reaches the chat
        sent = [(r[0], r[1]) for r in Fake.requests]
        self.assertEqual(sent[0], ("POST", "/admin/api-tokens"))
        self.assertIn(("POST", "/api/v1/translate"), sent)
        self.assertIn(("POST", "/api/v1/jobs"), sent)
        self.assertEqual(sent[-1], ("DELETE", "/admin/api-tokens/t1"))      # revoked at the end
        translate = json.loads([r for r in Fake.requests if r[1] == "/api/v1/translate"][0][2])
        self.assertEqual((translate["frontend_id"], translate["target_lang"]), ("fe1", "es"))
        created = json.loads(Fake.requests[0][2])
        self.assertEqual(created["scope"], "translate")                     # least privilege

    def test_smoke_revokes_the_token_even_when_translation_fails(self):
        self._login()
        Fake.requests.clear()
        Fake.translate_status = 500
        err, out = self.call("test_smoke", timeout_s=20)
        self.assertTrue(err)
        self.assertIn("admin/llm/health", out)
        self.assertEqual([(r[0], r[1]) for r in Fake.requests][-1], ("DELETE", "/admin/api-tokens/t1"))

    def test_smoke_reports_a_failed_job(self):
        self._login()
        Fake.job_final = "failed"
        err, out = self.call("test_smoke", timeout_s=20)
        self.assertFalse(err, out)
        result = json.loads(out)
        self.assertFalse(result["ok"])
        self.assertIn("queue", result["hint"].lower())


    # ------------------------------------------------------------ remote hosts (fake ssh / scp / tailscale)

    def _shims(self, ssh_out="", tailscale_out=""):
        """Put fake ssh, scp and tailscale first in PATH; they log their arguments and print canned output.
        ssh_out may be a dict {text in the command: output} to answer each remote command differently."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        self.log = self.tmp / "calls.log"
        for name, out in (("ssh", ssh_out), ("scp", ""), ("tailscale", tailscale_out)):
            f = bin_dir / name
            if isinstance(out, dict):
                cases = "".join(f"  *'{k}'*) cat <<'EOF'\n{v}\nEOF\n  ;;\n" for k, v in out.items())
                body = f"case \"$*\" in\n{cases}esac\n"
            else:
                body = f"cat <<'EOF'\n{out}\nEOF\n"
            f.write_text(f"#!/bin/sh\necho \"{name} $*\" >> '{self.log}'\n{body}")
            f.chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{old}"
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))

    def _calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_remote_host_must_look_like_user_at_address(self):
        self._shims()
        for bad in ("-oProxyCommand=x@y", "root@a;rm -rf /", "justhost", "root@"):
            err, _ = self.call("remote_check", host=bad)
            self.assertTrue(err, bad)
        self.assertEqual(self._calls(), [])

    def test_remote_check_reads_the_machine_and_flags_exposed_ports(self):
        self._shims("os=Ubuntu 24.04\narch=x86_64\nuser=root\nsudo=yes\ndocker=Docker version 27\ncompose=\n"
                    "tailscale=\ntailscale_ip=\nmem_mb=3900\nlistening=0.0.0.0:22 0.0.0.0:8081 127.0.0.53:53")
        err, out = self.call("remote_check", host="root@203.0.113.7")
        self.assertFalse(err, out)
        info = json.loads(out)
        self.assertEqual(info["listening_ports"], ["22", "53", "8081"])
        self.assertEqual(info["listening_beyond_ssh_and_private"], ["0.0.0.0:8081"])
        self.assertIn("remote_install tailscale", info["next"])
        self.assertIn("BatchMode=yes", self._calls()[0])

    def test_remote_install_is_planned_until_apply_and_runs_only_fixed_scripts(self):
        self._shims("Docker installed")
        err, out = self.call("remote_install", host="ubuntu@203.0.113.7", action="docker")
        self.assertFalse(err)
        self.assertIn("planned", out)
        self.assertEqual(self._calls(), [])
        self.assertTrue(self.call("remote_install", host="ubuntu@203.0.113.7", action="rm -rf /", apply=True)[0])
        err, out = self.call("remote_install", host="ubuntu@203.0.113.7", action="docker", apply=True)
        self.assertFalse(err, out)
        self.assertIn("get.docker.com | sudo sh", self._calls()[0])            # not root → sudo
        self.call("remote_install", host="root@203.0.113.7", action="firewall", port=2222, apply=True)
        self.assertIn("ufw allow 2222/tcp", self._calls()[-1])
        self.assertNotIn("sudo", self._calls()[-1])

    def test_tailscale_login_returns_the_link(self):
        self._shims("To authenticate, visit:\n\n\thttps://login.tailscale.com/a/abc123def\n")
        err, out = self.call("remote_install", host="root@203.0.113.7", action="tailscale_login", apply=True)
        self.assertFalse(err, out)
        self.assertEqual(json.loads(out)["login_link"], "https://login.tailscale.com/a/abc123def")

    def test_remote_deploy_sends_files_directly_and_never_shows_secrets(self):
        self._shims("")
        folder = self.tmp / "fe"
        self.call("deploy_prepare", topology="t2-vps-tailscale", folder=str(folder),
                  values={"TAILSCALE_IP": "100.64.0.5", "TRANSLATOR_BACKEND_SECRET": "s" * 40, "TUNNEL_TOKEN": "eyJ-tunnel-token"},
                  apply=True)
        err, out = self.call("remote_deploy", host="root@203.0.113.7", folder=str(folder), remote_folder="translator/fe")
        self.assertFalse(err, out)
        self.assertIn("planned", out)
        self.assertNotIn("eyJ-tunnel-token", out)
        self.assertFalse(any(c.startswith("scp") for c in self._calls()))
        err, out = self.call("remote_deploy", host="root@203.0.113.7", folder=str(folder), remote_folder="translator/fe",
                             apply=True)
        self.assertFalse(err, out)
        calls = self._calls()
        self.assertEqual(sum(c.startswith("scp") for c in calls), 2)
        self.assertTrue(any("chmod 600 translator/fe/.env" in c for c in calls))
        self.assertNotIn("eyJ-tunnel-token", out)

    def test_remote_folder_has_no_default_and_must_be_a_plain_path(self):
        self._shims("")
        folder = self.tmp / "fe0"
        self.call("deploy_prepare", topology="t2-vps", folder=str(folder), values={"TUNNEL_TOKEN": "t"}, apply=True)
        self.assertTrue(self.call("remote_deploy", host="root@h.example", folder=str(folder))[0])
        self.assertTrue(self.call("remote_compose", host="root@h.example", action="ps")[0])
        for bad in ("../etc", "a b", "x;rm -rf /", "$(id)"):
            self.assertTrue(self.call("remote_deploy", host="root@h.example", folder=str(folder),
                                      remote_folder=bad, apply=True)[0], bad)
        self.assertEqual(self._calls(), [])
        self.assertFalse(self.call("remote_compose", host="root@h.example", action="ps",
                                   remote_folder="/home/admin/stacks/translator")[0])   # absolute paths are fine

    def test_remote_deploy_refuses_to_replace_an_existing_stack(self):
        self._shims("docker-compose.yml\n.env")
        folder = self.tmp / "fe2"
        self.call("deploy_prepare", topology="t2-vps-tailscale", folder=str(folder),
                  values={"TAILSCALE_IP": "100.64.0.5", "TRANSLATOR_BACKEND_SECRET": "s" * 40, "TUNNEL_TOKEN": "t"}, apply=True)
        err, out = self.call("remote_deploy", host="root@203.0.113.7", folder=str(folder), remote_folder="fe",
                             apply=True)
        self.assertTrue(err)
        self.assertIn("already holds a stack", out)
        self.assertFalse(any(c.startswith("scp") for c in self._calls()))

    def test_remote_deploy_keeps_the_machine_s_compose_file_name(self):
        self._shims("compose.yaml\n.env")
        folder = self.tmp / "fe3"
        self.call("deploy_prepare", topology="t2-vps", folder=str(folder), values={"TUNNEL_TOKEN": "t"}, apply=True)
        err, out = self.call("remote_deploy", host="root@h.example", folder=str(folder), remote_folder="stacks/translator",
                             replace_existing=True, apply=True)
        self.assertTrue(err)
        self.assertIn("uses compose.yaml", out)

    def test_replacing_a_stack_shows_the_changes_masked_and_keeps_a_backup(self):
        old = "services:\n  fe-a:\n    image: x\n"
        self._shims({"for f in": "compose.yaml\n.env", "cat ": old + "    environment:\n      - API_KEY=sk-old-literal\n"})
        folder = self.tmp / "fetched"
        folder.mkdir()
        (folder / "compose.yaml").write_text(old + "  fe-b:\n    image: x\n    environment:\n"
                                             "      - TRANSLATOR_BACKEND_SECRET=${TRANSLATOR_BACKEND_SECRET}\n"
                                             "      - TUNNEL_TOKEN=eyJ-literal-in-compose\n")
        m._write_private(folder / ".env", "TRANSLATOR_BACKEND_SECRET=" + "z" * 40 + "\n")
        err, out = self.call("remote_deploy", host="admin@h.example", folder=str(folder), remote_folder="stacks/translator",
                             replace_existing=True)
        self.assertFalse(err, out)
        changes = json.loads(out)["details"]["compose_changes"]
        self.assertIn("+  fe-b:", changes)
        self.assertIn("${TRANSLATOR_BACKEND_SECRET}", changes)                       # variables are kept
        for secret in ("eyJ-literal-in-compose", "sk-old-literal", "z" * 40):
            self.assertNotIn(secret, out)
        self.assertIn("(set, 40 chars)", out)                                  # masked once, true length
        self.assertFalse(any(c.startswith("scp") for c in self._calls()))
        err, out = self.call("remote_deploy", host="admin@h.example", folder=str(folder), remote_folder="stacks/translator",
                             replace_existing=True, apply=True)
        self.assertFalse(err, out)
        self.assertTrue(any("cp -p compose.yaml compose.yaml.bak-" in c and "cp -p .env .env.bak-" in c
                            for c in self._calls()))
        self.assertTrue(any(c.startswith("scp") and "compose.yaml" in c for c in self._calls()))

    def test_remote_fetch_copies_a_stack_locally_without_showing_secrets(self):
        self._shims({"for f in": "compose.yaml\n.env"})
        dest = self.tmp / "copy"
        err, out = self.call("remote_fetch", host="admin@h.example", remote_folder="stacks/translator", folder=str(dest))
        self.assertFalse(err, out)
        self.assertIn("planned", out)
        self.assertFalse(dest.exists())
        err, out = self.call("remote_fetch", host="admin@h.example", remote_folder="stacks/translator", folder=str(dest),
                             apply=True)
        self.assertFalse(err, out)
        scps = [c for c in self._calls() if c.startswith("scp")]
        self.assertEqual(len(scps), 2)
        self.assertIn("admin@h.example:stacks/translator/.env", scps[1])
        self.assertEqual(stat.S_IMODE((dest / ".env").stat().st_mode), 0o600)
        self.assertTrue(self.call("remote_fetch", host="admin@h.example", remote_folder="stacks/translator",
                                  folder=str(dest), apply=True)[0])               # never into a non-empty folder

    def test_remote_inventory_describes_the_machine_s_layout(self):
        ps = [
            {"Names": "edge-cloudflared-1", "Image": "cloudflare/cloudflared:latest", "State": "running",
             "Networks": "net-a,net-b", "Labels": "com.docker.compose.project=edge,com.docker.compose.service=cloudflared,"
                                                  "com.docker.compose.project.config_files=/srv/stacks/edge/compose.yaml"},
            {"Names": "translator-fe-a-1", "Image": "ghcr.io/dfergo/laiuni-translator-frontend:latest", "State": "running",
             "Networks": "net-a", "Labels": "com.docker.compose.project=translator,com.docker.compose.service=fe-a"},
            {"Names": "translator-fe-c-1", "Image": "ghcr.io/dfergo/laiuni-translator-frontend:latest", "State": "running",
             "Networks": "translator_default", "Labels": "com.docker.compose.project=translator,com.docker.compose.service=fe-c"},
            {"Names": "hrdd-fe-1", "Image": "ghcr.io/dfergo/laiuni-frontend:latest", "State": "running",
             "Networks": "net-b", "Labels": "com.docker.compose.project=hrdd,com.docker.compose.service=fe"},
            {"Names": "portainer", "Image": "portainer/portainer-ce", "State": "running", "Networks": "bridge",
             "Labels": ""},
        ]
        ls = [{"Name": "edge", "Status": "running(1)", "ConfigFiles": "/srv/stacks/edge/compose.yaml"},
              {"Name": "translator", "Status": "running(2)", "ConfigFiles": "/srv/stacks/translator/compose.yaml"},
              {"Name": "hrdd", "Status": "running(1)", "ConfigFiles": "/srv/stacks/hrdd/compose.yaml"}]
        nets = [{"Name": "bridge", "Labels": ""}, {"Name": "net-a", "Labels": ""},
                {"Name": "translator_default", "Labels": "com.docker.compose.network=default,com.docker.compose.project=translator"}]
        self._shims(json.dumps(ls) + "\n@@\n" + "\n".join(json.dumps(r) for r in ps) + "\n@@\n"
                    + "\n".join(json.dumps(n) for n in nets))
        err, out = self.call("remote_inventory", host="admin@h.example")
        self.assertFalse(err, out)
        inv = json.loads(out)
        self.assertEqual([s["folder"] for s in inv["stacks"]], ["/srv/stacks/edge", "/srv/stacks/translator",
                                                                "/srv/stacks/hrdd"])
        self.assertEqual(inv["tunnel"][0]["stack"], "edge")
        self.assertEqual({f["service"]: f["reachable_by_tunnel"] for f in inv["app_frontends"]},
                         {"fe-a": True, "fe-c": False})                         # HRDD's image is not this app's
        self.assertEqual([c["container"] for c in inv["containers_outside_stacks"]], ["portainer"])
        self.assertEqual({n["name"]: n["created_by"] for n in inv["networks"]},
                         {"net-a": "by hand (external)", "translator_default": "stack translator"})
        self.assertIn("reuse it", inv["next"])
        self.assertIn("/srv/stacks", inv["next"])

    def test_remote_inventory_of_an_empty_machine_points_to_the_templates(self):
        self._shims("[]\n@@\n@@\n")
        inv = json.loads(self.call("remote_inventory", host="root@h.example")[1])
        self.assertIn("deploy_prepare", inv["next"])

    def test_local_compose_finds_the_folder_s_own_compose_file(self):
        folder = self.tmp / "own"
        folder.mkdir()
        (folder / "compose.yaml").write_text("services: {}\n")
        err, out = self.call("compose", folder=str(folder), action="up")
        self.assertFalse(err, out)
        self.assertIn("-f compose.yaml", json.loads(out)["planned"])

    def test_remote_compose_changes_need_apply(self):
        self._shims("ok")
        err, out = self.call("remote_compose", host="root@203.0.113.7", action="up", remote_folder="fe")
        self.assertFalse(err)
        self.assertIn("planned", out)
        self.assertEqual(self._calls(), [])
        self.call("remote_compose", host="root@203.0.113.7", action="ps", remote_folder="fe")
        self.assertIn("cd fe && docker compose ps", self._calls()[0])
        self.assertTrue(self.call("remote_compose", host="root@203.0.113.7", action="ps", remote_folder="fe",
                                  service="x; rm -rf /")[0])
        err, out = self.call("remote_compose", host="root@203.0.113.7", action="down", remote_folder="fe")
        self.assertNotIn(" -v", json.loads(out)["planned"])                   # never removes volumes

    def test_tailscale_status_lists_peers(self):
        self._shims(tailscale_out=json.dumps({
            "BackendState": "Running",
            "Self": {"HostName": "studio", "TailscaleIPs": ["100.64.0.1", "fd7a::1"], "Online": True},
            "Peer": {"k": {"HostName": "vps", "TailscaleIPs": ["100.64.0.5"], "Online": True, "OS": "linux"}}}))
        err, out = self.call("tailscale_status")
        self.assertFalse(err, out)
        st = json.loads(out)
        self.assertEqual(st["this_machine"]["ip"], "100.64.0.1")
        self.assertEqual(st["peers"][0]["ip"], "100.64.0.5")

    def test_check_public_site_rejects_odd_names_and_reports_unresolved(self):
        self.assertTrue(self.call("check_public_site", hostname="x; curl evil")[0])
        err, out = self.call("check_public_site", hostname="no-such-host.invalid")
        self.assertFalse(err)
        self.assertFalse(json.loads(out)["resolves"])


if __name__ == "__main__":
    unittest.main()
