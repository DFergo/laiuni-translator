# Installing — step by step with the tools

Every `apply=true` only after the user said yes to the plan you showed.

## 1. Backend
On the backend machine (this machine, normally):
```
deploy_prepare topology="backend" folder="~/translator/backend"      → show plan, ask
deploy_prepare ... apply=true                                         → TRANSLATOR_FRONTEND_SECRET generated
compose folder="~/translator/backend" action="up" apply=true           → pulls (or builds) and starts
compose folder="~/translator/backend" action="logs"                    → wait for "Backend started"
```
- For topology C use `t3-same-host` instead (backend + frontend in one folder, one shared secret `TRANSLATOR_BACKEND_SECRET`, and `FRONTEND_PORT` to set).
- To reach the admin panel from other machines, set `ADMIN_BIND` to this machine's LAN or Tailscale IP (never `0.0.0.0` on an exposed host). The same port serves the machine API.
- The first start downloads the images (backend ≈ 800 MB): a few minutes on a normal connection.
- If the repo is newer than the published image (for example the machine API or a feature you need is missing from it), prepare the backend with `build_from_source=true`: `compose up` then builds the image from the repository (a few minutes, needs the repo folder to stay in place).

## 2. Admin account and models
```
backend_connect url="http://127.0.0.1:8000"
admin_create apply=true            → tell the user where the password file is; they store it in their password manager
```
Then the model (guide `inference`): a connection and the translation engine, `GET /admin/llm/health`.

## 3. Glossary (optional, recommended)
The backend ships with a base glossary (230 terms in 17 languages, used by the review pass). The organisation can add its own: see guide `configure` (Glossary). Users can also attach a glossary per document.

## 4. Frontend(s)
- **T3**: already running in the same folder. Register `http://translator-frontend:8080` (guide `frontends`).
- **T1 (other office machine)**: `deploy_prepare topology="t1-lan"` with `TRANSLATOR_BACKEND_SECRET="env:~/translator/backend/.env#TRANSLATOR_FRONTEND_SECRET"` and `BACKEND_BIND=<that machine's LAN IP>`, prepared locally then copied (`scp -r`) to that machine and started there.
- **T2 (VPS)**: `t2-vps-tailscale`, same secret reference, `TAILSCALE_IP=<VPS tailscale IP>`, `TUNNEL_TOKEN` from the tunnel (guide `domain-cloudflare`). Prepare locally, copy to the VPS, start there (guide `vps`).
Then register and configure (guide `frontends`).

## 5. Email
Guide `email`. Without it nobody can sign in.

## 6. Verify
```
status
check_frontend public_url="http://127.0.0.1:8091"   (or https://<hostname>)
test_smoke frontend_id="<id>"
```
A passing smoke test means: backend → model → glossary → job queue → result all work (it uses a throw-away API token and creates one small job that is deleted with the normal retention). A reachable, **online** frontend (`/admin/frontends`) plus a passing `check_frontend` cover the portal side. The final proof is a real user: add one address to the whitelist, have them sign in and translate a small file.

## 7. Hand over
Summarise for the user: addresses (admin panel, each frontend), where the password file is, which model and costs apply, how to update and back up (guide `operate`), and that an AI agent can use the machine API with a token (guide `api`). Save `profile_save {"step": "installed"}`.
