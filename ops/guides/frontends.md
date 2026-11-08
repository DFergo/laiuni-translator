# Frontends: register, configure, brand, whitelist

A frontend = one website for one audience. Deploy it first (guide `install`, step 4), then:

## Register (the backend starts polling it)
```
admin_api POST /admin/frontends
  {"url": "<backend-port URL>", "name": "Staff portal", "auth_mode": "signed",
   "public_url": "https://translate.example.org"}
```
- URL by topology: T3 `http://translator-frontend:8080` · T1 `http://<LAN IP>:8081` · T2 with Tailscale `http://<VPS tailscale IP>:8081` · T2 without Tailscale `https://<private hostname>` plus `"extra_headers": {"CF-Access-Client-Id": "env:...", "CF-Access-Client-Secret": "env:..."}`.
- `public_url` is the address users open. The one-time download link in the result email points to it, so set it for every frontend that is not on the old single-port layout.
- With the installation secret (`TRANSLATOR_FRONTEND_SECRET` on the backend = `TRANSLATOR_BACKEND_SECRET` on the frontend) nothing else is needed. For a frontend on someone else's server, an own secret is safer: generate one, put it in that frontend's `.env` and send `"signing_secret": "env:<that .env>#TRANSLATOR_BACKEND_SECRET"` (at least 32 characters).
- `auth_mode`: `signed` (default), `unsigned` (trusted network — only if nothing but the backend can reach port 8080) or `legacy` (frontends from before the two-port layout).
- The backend checks the frontend before saving; read the error if it fails (unreachable, signature rejected → secret or clock, wrong port, not a backend port).
- The answer contains the frontend's `id`. `admin_api GET /admin/frontends` shows it **online** within a few seconds. Change address/mode later with `PUT /admin/frontends/<id>` (also verified before it is stored).

## Configure
A new frontend is **unconfigured**. Read, change, write back the whole object:
```
admin_api GET /admin/frontends/<id>/config
admin_api PUT /admin/frontends/<id>/config  {"configured": true, "app_language": "en", "auth_mode": "token"}
```
- `app_language`: language of the portal's own interface (blank = the global default in Settings).
- `auth_mode`: `token` (email → code → session; the normal choice) or `email-only` (no code — **only on a private network**; anyone who can type a whitelisted address gets in).
- A frontend may override the scheduling window and mode: `schedule_window_start_hour`, `schedule_window_duration_hours`, `schedule_mode` (`scheduled` · `immediate` · `both`), `batch_max` (max documents per submission, up to 10). Anything left out follows the global Settings (guide `configure`).

## Who may sign in (the whitelist)
Only listed addresses receive a code. There is a global list and an optional list per frontend that either **replaces** or **appends to** it.
```
admin_api GET /admin/contacts
admin_api PUT /admin/contacts/global
  {"contacts": [{"email": "ana@union.org", "first_name": "Ana", "organization": "Union", "country": "ES"}]}
admin_api PUT /admin/contacts/frontend/<id>
  {"mode": "append", "contacts": [{"email": "guest@other.org"}]}
```
Each contact can carry `schedule_override` (may choose immediate or scheduled whatever the setting) and `priority` (their jobs jump the queue). Spreadsheet import/export: `POST /admin/contacts/import` (`admin_upload`), `GET /admin/contacts/export` (personal data: `confirm_content=true`). Note that `PUT .../global` replaces the whole list — read it first and send it back with the additions.

## Branding
```
admin_api GET /admin/frontends/<id>/branding
admin_api PUT /admin/frontends/<id>/branding  {"app_title": "Staff translations", "logo_url": "https://…/logo.png"}
```
The logo is a URL the browser can load. Visual design rules: `DESIGN.md` in the repo.

## Per-frontend model, prompts, glossary
- Model only for this frontend: `PUT /admin/frontends/<id>/llm-settings` (only the fields that differ from the global ones; `DELETE` goes back to global).
- Prompts: guide `configure` (Prompts).
- Glossary: `PUT /admin/knowledge/glossary/frontend/<id>/config {"mode": "append"|"replace"}` and a per-frontend upload (guide `configure`).

## Check
`check_frontend` against the frontend's public address (and the backend-port URL if reachable from here), then `test_smoke frontend_id=<id>`.
