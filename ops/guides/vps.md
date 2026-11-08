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
2. If you can run commands locally, check access: `ssh <user>@<ip> 'uname -a'` (ask first).
3. On the VPS: system updates (`apt update && apt upgrade -y`), Docker (guide `prerequisites`), Tailscale (`tailscale up`), and automatic security updates (`apt install -y unattended-upgrades`).
4. Copy the frontend deployment: prepare it locally with `deploy_prepare` (`t2-vps-tailscale`) in a temporary folder, then copy it (`scp -r <folder> <user>@<ip>:~/translator-frontend`) — this keeps the secrets out of the chat. Then on the VPS: `cd ~/translator-frontend && docker compose up -d`.
5. If you have no shell access, give the user the exact commands, one block at a time, and ask what they see.
