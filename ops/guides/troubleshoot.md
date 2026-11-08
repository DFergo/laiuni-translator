# Troubleshooting

Read-only checks first, then explain, then propose a fix (and ask).

## First look
- `status` — frontends (online/offline, mode badge), model health, queue, settings, email.
- `compose action="ps"` / `action="logs"` in the backend folder (and the frontend's, if local).
- `check_frontend` with the public URL (and backend-port URL if reachable from here).

## Symptoms
| Symptom | Likely cause | Check / fix |
|---|---|---|
| Admin panel does not open | Container not running; wrong address; `ADMIN_BIND` | `compose ps`, `compose logs`; open `http://127.0.0.1:8000` on the backend machine. |
| Frontend **offline** in the admin | Backend cannot reach the backend port | From the backend machine: `curl -s -o /dev/null -w '%{http_code}' <url>/backend/v1/health` → 401 means reachable (signed). Timeout: IP/port, `BACKEND_BIND`, Tailscale (`tailscale status`, key expiry), firewall. |
| Registration: "signature rejected" | Different secrets, or clocks out of sync (±120 s) | Same value in backend `TRANSLATOR_FRONTEND_SECRET` and frontend `TRANSLATOR_BACKEND_SECRET` (compare masked lengths with `env_show`; never print). Enable NTP on both machines. |
| "frontend accepts unsigned" badge | Frontend runs with `BACKEND_SURFACE_AUTH=trusted-network` | Set `signed` and the secret, restart. |
| Site shows "not configured" | Config not saved | guide `frontends` → `configured: true`. |
| User gets no sign-in code | SMTP not configured/failing; address not on the whitelist | `POST /admin/smtp/test`; `GET /admin/contacts` (guide `frontends`). |
| Job stays *queued* or *scheduled* | Waiting for the night window; or its connection is at its limit (one job at a time unless **parallel** is on) | `GET /admin/queue`: status, position, connection; `schedule_mode` in `/admin/settings`; guide `inference` (parallel jobs). |
| Job **failed** | Model down, wrong key, no credit, 429 rate limit, output kept coming back incomplete | `GET /admin/queue` → `failed` has the reason; `GET /admin/llm/health`; lower `max_concurrent` on 429; `retry` once fixed. |
| Several jobs fail together with 429 / "too many requests" | `max_concurrent` above the provider's limit | `PUT /admin/llm/connections/<id> {"max_concurrent": 2}` and retry the failed ones. |
| Empty or truncated output | A reasoning model used up the token budget | `translation_reasoning` = `off` (or `default` if the model cannot switch it off); raise `translation_max_tokens`; the app retries and then fails rather than ship a hole. |
| Same file refused ("already being translated") | Duplicate protection: an identical job is still queued or running | Wait for it, cancel it, or (API) send `force=true`. |
| Result link in the email does not open | Frontend has no `public_url` | `PUT /admin/frontends/<id> {"public_url": "https://…"}` (guide `frontends`). |
| Tunnel site down (Cloudflare error 1033/502) | `cloudflared` not running or wrong service in the hostname | `compose ps` on the VPS; the hostname must point to `http://translator-frontend:80`. |
| T2 frontend container does not start after reboot | Tailscale IP not up yet when Docker started | `docker compose up -d` again; ensure Tailscale starts at boot (`systemctl enable tailscaled`). |
| `/api/v1` answers 404 | Backend image older than the machine API | Update the backend (guide `operate`). |
| Backend does not start / is killed | Not enough memory or disk | `compose logs`, `docker stats`; the app is light (about 100 MB idle) but needs ≈ 1 GB of disk for its image plus room for documents. |

## Never
- Call `GET /backend/v1/queue` on a frontend by hand (it consumes users' sign-in and job requests).
- Publish the frontend backend port or the admin port on the open Internet as a "fix".
- Delete volumes (`docker compose down -v`, `docker volume rm`) — that deletes all data.
