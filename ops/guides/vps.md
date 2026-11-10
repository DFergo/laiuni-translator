# Renting a VPS (topology B)

The VPS only runs the public frontend: small is enough. Uploaded documents and result files pass through it in memory while in transit and are stored by the backend; still choose a provider and location that fit the organisation's data-protection obligations.

## Recommended providers
- **Infomaniak** (Switzerland) — https://www.infomaniak.com — VPS (e.g. *VPS Lite* / *VPS Cloud*), data centres in Switzerland, strong privacy, also sells domains. Good choice when Swiss/European data protection matters most.
- **Hetzner** (Germany) — https://www.hetzner.com/cloud — Hetzner Cloud servers; choose a location in **Germany or Finland** (EU). Simple, inexpensive. Both Intel/AMD (CX, CPX) and ARM (CAX) servers work for the frontend.

Check current plans and prices on their sites; do not quote them from memory.

## What to choose
- **Size**: 2 vCPU, 2–4 GB RAM, 20+ GB disk is plenty for a frontend. Large results are held in memory while they wait to be downloaded (the frontend container is limited to 1.5 GB), so avoid less than 2 GB.
- **OS**: Ubuntu LTS (latest) or Debian stable.
- **Access**: SSH key (help the user create one if needed: `ssh-keygen -t ed25519`, then paste the `.pub` file's content into the provider's form). Avoid password login.
- **Firewall** (provider's firewall or `ufw`): allow only SSH (22) inbound. The frontend needs no inbound port: users come through the Cloudflare Tunnel and the backend through Tailscale. Once Tailscale works you can restrict SSH to the tailnet too.

## Setting it up (with the user, step by step)
1. The user creates the account and the server, and gives you its IP address and the SSH user (often `root` on Hetzner).
2. `remote_check host=user@address` — read-only; shows OS, memory, Docker, Tailscale and listening ports.
3. Prepare the server with `remote_install` (one action per call, each after the user's yes): `updates`, `docker`, `tailscale`, `tailscale_login` (the user opens the returned link), optionally `firewall`. Run `remote_check` again after each.
4. `remote_inventory host=user@address` — is the server empty? If it already runs containers (another app, a tunnel, the organization's own stacks), follow guide `existing-host` instead of step 5.
5. Deploy the frontend: `deploy_prepare` (`t2-vps-tailscale`) locally, `remote_deploy` with the folder you and the user chose on the server (copies the `.env` straight to it, never through the chat), `remote_compose action="up"`. Then `check_public_site` and `check_frontend`.
6. If SSH from this machine is not possible (key not added, port blocked), give the user the exact commands from `remote_install`'s plan, one block at a time, and ask what they see. They can also run them in the provider's web console.
