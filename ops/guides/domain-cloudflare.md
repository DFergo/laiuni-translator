# Domain and Cloudflare Tunnel (public access)

A **Cloudflare Tunnel** publishes the frontend on the Internet with HTTPS without opening any port: `cloudflared` (a small container next to the frontend) connects out to Cloudflare, and Cloudflare forwards visitors through that connection.

## The domain: buy a new one for the app
For a tunnel hostname, the domain's DNS must be managed by Cloudflare, which means moving the whole domain's nameservers to Cloudflare. The organisation's existing domain almost always carries its website and email and is managed by someone else (provider, IT, a national office): **do not move it.** Recommend a **new, dedicated domain** for the app (e.g. `union-translate.org`), used only for the frontends (`translate.union-translate.org`).

Where to buy:
- **Cloudflare Registrar** (dash.cloudflare.com → Domain Registration) — simplest: the domain is on Cloudflare from the start; sold at cost. Not every extension is available.
- **Infomaniak** (or any registrar) — then add the domain to Cloudflare (free plan) and change its nameservers at the registrar to the two Cloudflare gives; activation takes from minutes to a few hours.
The user buys and pays; help them pick a name that is neutral and easy to type.

## Cloudflare account and the Cloudflare MCP
1. The user creates a free account at https://dash.cloudflare.com.
2. Recommended: install Cloudflare's own plugin in Claude Code so you can create the tunnel for them (each Cloudflare action is authorised by the user through Cloudflare's OAuth):
   ```
   /plugin marketplace add cloudflare/skills
   /plugin install cloudflare@cloudflare
   ```
   (run one at a time inside Claude Code; `/reload-plugins` if the tools do not appear). Other agents: Cloudflare API MCP server `https://mcp.cloudflare.com/mcp`. Details: https://developers.cloudflare.com/agent-setup/
3. Without it, guide the user through the dashboard (steps below; Zero Trust → Networks → Tunnels).

## Creating the tunnel (with the user's go-ahead for each step)
1. **Create a remotely-managed tunnel** (type *cloudflared*) named e.g. `translator-frontend-<site>`.
2. **Public hostname** → service:
   - topology B (`t2-vps-tailscale`) and `t2-vps`: `https://<hostname>` → `http://translator-frontend:80`
   - a frontend added to a machine's own layout (guide `existing-host`): `http://<its service name>:80`, in the tunnel that machine already has
   - cloudflared on the host next to a T1/T3 frontend: `http://localhost:<FRONTEND_PORT>`
   **Map only the public port (80).** Never the backend port.
   Adding the hostname creates the DNS record automatically when the domain is on Cloudflare.
3. **Connector token**: get the tunnel's token and put it in the frontend's `.env` as `TUNNEL_TOKEN` without showing it in chat — e.g. the user pastes it into the `.env` on the VPS, or you write it with `env_set` from a local file reference. Then `docker compose up -d` on the frontend machine.
4. Check: the tunnel shows **healthy** in Cloudflare; `check_frontend` with `https://<hostname>` passes.

## Optional hardening
- Cloudflare **Access** in front of internal frontends (organisers/officers): only listed email addresses can open the site.
- `t2-vps` without Tailscale needs a second hostname for the backend port, protected by Access with a service token — see `docs/INSTALL.md` section 5.4 (T2) and 6 (tunnel).
