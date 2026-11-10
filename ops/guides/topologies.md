# Choosing a topology

The deployment folders are in `deploy/` of the repo; `deploy_prepare` copies one and writes its `.env`. They are templates for a machine that runs nothing yet. If the machine already runs containers (`remote_inventory` shows them), do not add a template next to them: follow guide `existing-host`.

## Recommended

### A. Backend and frontend on separate local machines (`backend` + `t1-lan`)
- Backend on one machine at the organisation (always on), frontend on another machine of the same network.
- Everything stays in-house. For Internet access, the frontend machine runs a Cloudflare Tunnel (no open ports); without it, the site is only reachable in the office.
- The backend reaches the frontend's backend port at `http://<frontend LAN IP>:8081`. Set `BACKEND_BIND` to that LAN IP. Signed mode.
- Needs: two machines, Docker on both. Tailscale optional (useful to administer remotely).

### B. Backend local, frontend on a VPS (`backend` + `t2-vps-tailscale`) — public sites
- Documents are processed and stored on the organisation's machine; only the public website runs on the VPS. Uploaded files and result ZIPs pass through the VPS in memory while they are in transit.
- Users reach the frontend through a **Cloudflare Tunnel** (no inbound ports on the VPS). The backend reaches the frontend's backend port over **Tailscale** (a private network between your machines; only outgoing connections). Signed mode.
- Register the frontend with `http://<VPS Tailscale IP>:8081` and its public address (used in the emailed download links).
- Needs: a VPS (guide `vps`), a domain on Cloudflare (guide `domain-cloudflare`), Tailscale on both machines.
- Alternative without Tailscale: `t2-vps` (the backend reaches the frontend through a second, Cloudflare Access-protected hostname with a service token). More Cloudflare configuration; use only if Tailscale is not an option. See `docs/INSTALL.md` section 5.4.

## To try it out

### C. Everything on one machine (`t3-same-host`)
- Backend and one frontend on this machine, isolated containers. Quickest start; the site is at `http://127.0.0.1:8091`.
- Fine as a production setup only for a single server the organisation fully controls.

## How to recommend
- No public access needed and two machines available → A.
- Public access needed → B (A with a tunnel also works if the frontend machine can stay on and the office connection is reliable).
- First time, wants to see it working → C, then move to A or B (frontends can be added later; the backend stays).
- Backend machine: should stay on. The app itself is light (about 100 MB idle); a local AI model is what needs memory. Apple Silicon Macs and Intel/AMD PCs or servers both work (images for both).

## Ports (defaults)
| What | Where | Default |
|---|---|---|
| Admin panel and machine API (`/api/v1`) | backend machine | `127.0.0.1:8000` (`ADMIN_BIND` to allow a LAN/Tailscale address) |
| Frontend public port | frontend machine | `127.0.0.1:8091` (T1/T3) or only via the tunnel (T2) |
| Frontend backend port | frontend machine | `8081` on the LAN IP (T1) or Tailscale IP (T2) |

Anything that can reach the backend port can try the admin login and the API tokens. Keep `ADMIN_BIND` on `127.0.0.1` or a private address.
