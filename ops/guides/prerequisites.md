# Prerequisites: Docker, Tailscale

Check first with `check_machine`. Explain what each thing is before installing it. Ask before every install; on macOS, installers may ask for the user's password — tell them this is expected.

## Docker
Runs the app in containers (isolated packages with everything they need).

**macOS**
- **Docker Desktop** — https://www.docker.com/products/docker-desktop/ (choose Apple Silicon or Intel). Free for personal use, education and small organisations; larger organisations need a paid plan — tell the user to check Docker's licence terms.
- Alternatives: **OrbStack** (https://orbstack.dev — lighter; paid for commercial use) or **Colima** (free, open source: `brew install colima docker docker-compose && colima start --cpu 4 --memory 8`).
- After installing, open the app once so the engine starts. Check: `docker info`.

**Linux (Ubuntu/Debian, also on a VPS)**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # then log out and back in
docker compose version
```

**Windows**: Docker Desktop with WSL 2. Recommend running the app from a WSL Ubuntu terminal (and the agent inside WSL).

## Tailscale
A private network between the organisation's machines, encrypted, with no open ports. Used in topology B so the backend can reach the frontend's backend port on the VPS; also handy to open the admin panel remotely.

1. The user creates an account at https://tailscale.com (free plan is enough for this; sign in with Google, Microsoft or GitHub).
2. Install on each machine:
   - macOS: the Tailscale app (https://tailscale.com/download), sign in.
   - Linux/VPS: `curl -fsSL https://tailscale.com/install.sh | sh` then `sudo tailscale up` (opens a login link).
3. Check: `tailscale status` lists both machines; `tailscale ip -4` gives each machine's address (100.x.y.z).
4. Recommended: in the Tailscale admin console, disable **key expiry** for the server machines (otherwise they drop off after the expiry period). Optional: an ACL allowing only the backend machine to reach the VPS port 8081.

## Git and Python
The agent already used them to download the repo and run this MCP. On macOS, if missing: `xcode-select --install`.

## Local AI models (only if chosen)
See guide `inference`: Ollama (https://ollama.com), LM Studio (https://lmstudio.ai) or oMLX on Apple Silicon.
