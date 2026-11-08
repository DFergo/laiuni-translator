# The machine API and API tokens (for AI agents and scripts)

The backend also serves an API meant for machines, on the **same port as the admin panel** (`/api/v1`). It is how an AI agent or a script translates documents without the portal. The exact contract is always `GET <backend>/openapi.json`.

## Tokens
Created in Admin → **API tokens** (or `admin_api POST /admin/api-tokens {"name": "my-agent", "scope": "translate"}`). The plaintext (`lt_…`) is shown **once**; the backend keeps only a hash. Sent as `Authorization: Bearer lt_…`. Two scopes:
- **`translate`** (default): only `/api/v1` — translate, jobs, languages, frontends, connections.
- **`admin`**: also **every `/admin/*` route** (everything this MCP does, and more: it can read provider keys and create other tokens). Give it only to an agent the organisation trusts, and say so plainly. Every `/admin/*` call made with a token is logged (token name, method, path).
Revoke at once with `DELETE /admin/api-tokens/{id}`. Never put a token in the chat or in git: store it in a local file with mode 0600.

Because the API shares the admin port, keep `ADMIN_BIND` on `127.0.0.1` or a private (LAN/Tailscale) address and never publish the port to the Internet.

## What it does
- `GET /api/v1/languages`, `/frontends`, `/connections` — valid values for the calls below (no keys or URLs are returned).
- `POST /api/v1/translate` — synchronous text (Markdown or plain): `text`, `target_lang`, optional `source_lang` (auto-detected), `frontend_id` (uses that frontend's glossary, prompts and model), `connection_id`/`model` (this request only), `glossary`. YAML frontmatter comes back untouched; wikilinks, URLs and code blocks are checked and any difference is listed in `warnings`.
- `POST /api/v1/jobs` (multipart file) → `job_id`; `GET /jobs` (your library), `GET /jobs/{id}` (status, `progress` 0–1, `files`), `GET /jobs/{id}/result` (file or ZIP), `GET /jobs/{id}/files/{name}` (original or one language), `DELETE /jobs/{id}` (cancel). An identical file with the same options while the first is still active returns that job with `duplicate: true`; `force=true` overrides. Results are deleted after `retention_hours`, like every job. API jobs send no email and appear in Admin → Queue and Usage as `api`.

## For the agent that administers the system
`test_smoke` already uses a throw-away `translate` token. For anything else, prefer `admin_api` (password login, JWT kept by this MCP) over minting a long-lived `admin` token.
