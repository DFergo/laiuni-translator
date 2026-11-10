# Installing on a machine that already runs things

The templates in `deploy/` (guide `topologies`) are for a machine that runs nothing yet. Many organizations already have a server with its own way of working: one folder per stack, a tunnel shared by several sites, their own network and naming rules. There, do not drop a template next to what exists — fit the app into the machine's layout. The app needs a few things (below); where and how they live is the machine owner's choice.

## 1. Look first

`remote_inventory host=user@address` (read-only). Connect as the user that runs the containers — usually the one that owns the stack folders; if Docker answers *permission denied*, it is the wrong user. It shows:

- **stacks**: each compose project with its folder and files. Their parent folder is where stacks live on this machine.
- **tunnel**: a running `cloudflared`, which stack it belongs to and which networks it joins. If there is one, **reuse it**: a second `cloudflared` for the same machine is not needed.
- **app_frontends**: this app's frontends already there, and whether the tunnel reaches each one.
- **networks**: created by a stack, or by hand (external networks, shared between stacks).

Describe the layout to the user in two or three sentences and ask how they want the new frontend placed. Typical answers: "another service in the existing Translator stack", or "its own stack, like the others". Save it with `profile_save {"host_layout": "..."}` so the next time you do not have to ask.

## 2. What a frontend needs (the contract)

Whatever the layout, a frontend is one container with:

| Need | Value |
|---|---|
| Image | `ghcr.io/dfergo/laiuni-translator-frontend:<tag>` (`latest` follows `main`; `sha-<commit>` pins a version) |
| Environment | `BACKEND_SURFACE_AUTH=signed`; `TRANSLATOR_BACKEND_SECRET` = the backend's `TRANSLATOR_FRONTEND_SECRET` (pass it as `env:` reference, never in the chat); `TRANSLATOR_BACKEND_SECRET_PREVIOUS` empty |
| Data | a named volume mounted at `/app/data` (one per frontend; never shared) |
| Memory | at least `1536m`: result ZIPs (up to 512 MB) are held in memory |
| Public port | `80` inside the container (site for users): the tunnel's public hostname points to `http://<service name>:80` |
| Backend port | `8080` inside the container (only the Translator backend): over Tailscale, publish it on the machine's Tailscale IP only (`"<tailscale ip>:<port>:8080"`); without Tailscale, a second hostname protected by Cloudflare Access (guide `domain-cloudflare`) pointing to `http://<service name>:8080` |
| No other ports | never publish `80` or `8080` on a public address |
| Hardening | copy from the template (`deploy/t2-vps/docker-compose.yml`): `no-new-privileges`, `cap_drop: [ALL]` with the `cap_add` list, CPU/pids limits, `restart: unless-stopped`, and the Watchtower label if the machine uses Watchtower |

Use the machine's names: if its frontends are called `fe-<site>` on networks `net-<site>`, the new one follows the same pattern. The service name matters: the tunnel reaches the container by it.

## 3. Add it

**To an existing stack** (the usual case):
1. `remote_fetch host=… remote_folder="<stack folder>" folder="~/translator/<stack>-copy"` → plan → ask → `apply=true`. The compose file and `.env` are copied here (the `.env` with mode 0600, values never shown).
2. Edit the compose file in that folder: add the service and its volume following the existing entries; if the machine gives each frontend its own network, add it the same way. New variables: `env_set` (secrets as `env:` references).
3. Networks shared between stacks are external: if the new frontend needs one that does not exist yet, tell the user the exact command (`docker network create <name>`) — or, if the tunnel's stack must join the new network, the tunnel's compose file changes too (repeat 1–2 for that stack).
4. `remote_deploy host=… folder="~/translator/<stack>-copy" remote_folder="<stack folder>" replace_existing=true` → the plan shows the compose changes (secrets masked) → ask → `apply=true`. The current files are kept on the machine as `<file>.bak-<date>`.
5. `remote_compose host=… remote_folder="<stack folder>" action="up"` → plan → ask → `apply=true`. Compose only recreates what changed. Then `action="ps"`.

**As a new stack**: create a local folder with a compose file named like the machine's others (`compose.yaml` or `docker-compose.yml`) and a `.env`, then `remote_deploy` to a new folder next to the other stacks and `remote_compose up`.

## 4. Route and register

1. Tunnel: add the public hostname → `http://<service name>:80` to the **existing** tunnel (guide `domain-cloudflare`, step "public hostname"), and the backend hostname if you use one.
2. `check_public_site`, `check_frontend`, then register it in the backend with its public address (guide `frontends`).

## Never

- Start a second `cloudflared` on a machine that already has a tunnel.
- Change other services, networks or volumes of the machine without the user's yes for that exact change.
- Rename existing services: tunnels and other machines reach them by name.
