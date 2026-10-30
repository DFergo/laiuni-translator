# LAIUNI Translator — Installation Guide

## 1. What you are installing

LAIUNI Translator has two kinds of containers:

- **Backend**: the admin panel, the job queue, the calls to the language model, the email sending, and all stored data (configuration, the whitelist, uploaded documents and their translations while they are retained).
- **Frontend**: the portal users see. A user signs in with their email, uploads a document, picks the languages and receives the translations by email. You can deploy **several frontends** (for example one per organisation or domain), each with its own address, branding and whitelist.

```
 Users' browsers                      Your infrastructure
 ───────────────                      ───────────────────────────────────────────
                    public port (80)           backend port (8080)
   browser  ─────────────►  FRONTEND  ◄───────────────────────────  BACKEND  ──► language model
                         (portal + queue)      backend polls          (admin, data)   (local or remote)
```

Three rules shape every deployment:

1. **The backend always initiates the connection** (it polls the frontends). A frontend never contacts the backend and does not know where it is. The backend therefore does not need to be reachable from the Internet.
2. **Each frontend has two ports.** The **public port** (container port `80`) serves the portal and the routes the users' browsers and the emailed download links use. The **backend port** (container port `8080`) is used only by the backend. **Never expose the backend port to the open Internet.**
3. **Requests on the backend port are signed by default** with a secret shared between the backend and the frontend; a request without a valid signature is rejected (`401`). An unsigned "trusted network" mode exists for networks where nothing but the backend can reach that port (section 5.1). The signature proves *who* is calling; it does not encrypt. On an untrusted network, use an encrypted path (HTTPS through a tunnel, a VPN or an SSH tunnel).

## 2. Choose a deployment

| | Where the frontend runs | How the backend reaches the frontend's backend port | Example |
|---|---|---|---|
| **T1 — Local network** | Another machine on the backend's network | `http://<LAN IP>:<port>` | [`deploy/t1-lan/`](../deploy/t1-lan/) |
| **T2 — Remote server (VPS)** | A server with no VPN to the backend | `https://<private hostname>` through a Cloudflare Tunnel protected by Cloudflare Access | [`deploy/t2-vps/`](../deploy/t2-vps/) |
| **T3 — Same machine** | The same machine as the backend, in separate isolated containers | `http://translator-frontend:8080` over an internal Docker network | [`deploy/t3-same-host/`](../deploy/t3-same-host/) |

One backend can serve frontends in all three topologies at once.

How to choose:

- **Trying it out or a small installation:** T3. One machine, one `docker compose up`.
- **A frontend on a different machine in the same office:** T1.
- **A public frontend you want away from your internal network:** T2. A compromised public frontend then sits outside your network, not inside it.
- **Sensitive documents:** prefer a separate machine for the frontends (T1 on an isolated network segment, or T2) over T3.

The translation model can run on the backend machine, on another machine you control, or at a cloud provider. See section 4.4.

## 3. Requirements

- A recent Docker Engine with the Docker Compose v2 plugin (`docker compose`).
- A Linux, macOS or Windows host. Both images are published for `amd64` and `arm64`.
- **Clocks in sync (NTP) on every machine** when frontends use signed mode: signatures more than 2 minutes off are rejected.
- Memory and disk (measured on a fresh installation; plan for your load):
  - Backend: about 50 MB of RAM idle and about 100 MB after a translation, more while the optional Okapi engine (Java) runs. The image is about 800 MB, plus your data.
  - Frontend: about 60 MB of RAM idle; the image is about 250 MB. While a result waits to be downloaded the frontend holds it in memory, peaking at about 2.5× its size during the transfer (section 5.1, *Result size*).
  - The language model needs its own resources on whatever machine runs it.
- Open only what you need: the public port of the frontends (or a tunnel), nothing else.

## 4. Install the backend

### 4.1 With the published image (recommended)

Create a folder, for example `translator-backend/`, with a `compose.yaml`:

```yaml
services:
  translator-backend:
    image: ghcr.io/dfergo/laiuni-translator-backend:latest
    pull_policy: always
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - translator-data:/app/data
    environment:
      - DEPLOYMENT_JSON_PATH=/app/config/deployment_backend.json
      # Installation secret for signed frontends (section 5.1). Optional.
      - TRANSLATOR_FRONTEND_SECRET=${TRANSLATOR_FRONTEND_SECRET:-}

volumes:
  translator-data:
```

If you use the installation secret, put it in a private `.env` file next to `compose.yaml` (`TRANSLATOR_FRONTEND_SECRET=<value>`, `chmod 600 .env`). Start the backend:

```bash
docker compose up -d
docker compose logs --tail 20
```

Notes:

- The admin panel listens on port `8000`. The example publishes it **only on `127.0.0.1`**: reach it from the same machine, or through a VPN, an SSH tunnel or a private network address. If you need a LAN address, bind to that specific address (for example `"192.168.1.10:8000:8000"`), never to every interface on an exposed host.
- Image tags: `latest` follows the `main` branch; `sha-<commit>` pins an exact version.
- The repository's `docker-compose.backend.yml` is the same service with a required `BACKEND_PORT`; it also shows how to build from source.

**With Portainer.** *Stacks → Add stack → Repository*, URL `https://github.com/DFergo/laiuni-translator`, branch `main`, compose path `docker-compose.backend.yml`, and the environment variables (`BACKEND_PORT`, optionally `TRANSLATOR_FRONTEND_SECRET`) in the stack form. To update: *Pull and redeploy*.

### 4.2 First run

1. Open `http://127.0.0.1:8000` (or the address you published). You will see **Create Admin Account**.
2. Choose a strong password (the minimum is 8 characters; use a long one). It is stored hashed in the data volume.
3. Log in.

### 4.3 Where the data lives

Everything the backend stores is under `/app/data` in the `translator-data` volume: global configuration (`config/`: connections, LLM settings, SMTP, prompts, glossary, whitelist, registered frontends), per-frontend settings (`campaigns/`), the job queue (`jobs.db`), uploaded documents and their translations (`documents/`, deleted after the retention period set in **Settings**), and the admin password hash. **Back this volume up** (section 7.2).

### 4.4 Connect the language model

Open **Admin → LLM**.

- **Provider Connections:** a connection is an address plus credentials. Types: any OpenAI-compatible server (for example oMLX, LM Studio, vLLM, OpenRouter or OpenAI itself), an Anthropic account, or an Ollama server.
- **Translation engine:** the connection and model used for every translation, with its temperature. The model field is a search box: type to filter the models the connection offers, or type an exact model ID.
- **Per-Frontend engine:** a frontend can override the global choice.
- Under each control the panel says whether it is sent, adjusted or ignored for the chosen connection and model, so no setting is a silent no-op. **Usage and prompt cache** shows prompt, cached, completion and reasoning tokens per model with the cache hit rate; each job logs its own totals when it finishes.

**What each provider supports.**

| | Temperature, Max Tokens | Context window | Reasoning control | Prompt cache |
|---|---|---|---|---|
| **Mistral API** | sent | shown, not sent | `mistral-large-4`: low/medium/high, cannot be switched off; `mistral-small`/`-medium`: off/high | automatic (best effort on short prompts) |
| **OpenRouter** | sent (some models ignore them: the panel says which, from OpenRouter's model list) | shown, not sent | off/low/medium/high where the model supports it | depends on the provider OpenRouter routes to |
| **OpenAI** | sent; reasoning models (o-series, gpt-5) take no temperature | not sent | low/medium/high on reasoning models | automatic |
| **Anthropic** | sent; Max Tokens required (4096 if blank); no temperature while thinking | not sent | low/medium/high = thinking budget; off is the default | breakpoints set automatically |
| **oMLX, LM Studio, vLLM** | sent | not sent | on/off for Qwen-family models only (`enable_thinking`); other models have no switch | server-side, if enabled |
| **Ollama** | sent | sent (`num_ctx`) | on/off (`think`) | not reported |

- **Reasoning is off by default for translation.** A reasoning pass is billed, counts against Max Tokens and can leave a unit empty (the completeness guard then retries and, if it persists, fails the job instead of shipping a hole). Where a model cannot switch it off (e.g. `mistral-large-4`), translations still work but cost more output tokens; leave Max Tokens blank or generous for such models.
- **Provider options** (connection editor, OpenAI-compatible connections, optional): *Provider profile* when it cannot be inferred from the address; *Send a per-job prompt cache key* (a hash, never the job id); *OpenRouter routing* (`provider` object, e.g. `{"order": ["alibaba"], "allow_fallbacks": false}`).
- If a provider rejects an optional field (reasoning setting, cache key, usage request), the call is retried once without it and the backend logs which field was dropped.

**Where the model can run.** Anywhere the backend container can reach: the same machine, another machine on your network or VPN, or a cloud provider. Inside the container:

- On Docker Desktop (macOS, Windows) and OrbStack, the host machine is `host.docker.internal`.
- On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service, or use the host's IP address.

**Privacy.** When the engine uses a cloud provider, the text of every uploaded document is sent to that provider. Choose providers and regions that satisfy your data-protection obligations. If documents must stay on your infrastructure, use a local or private model.

### 4.5 Email and settings

- **Admin → Settings → Email server (SMTP)** is required: users sign in with a code sent by email, and the translations are delivered as a one-time download link by email.
- **Admin → Settings** also sets the app language, the retention period, the scheduling window (when scheduled jobs run) and the document engine.
- **Admin → Registered Users** is the whitelist: only listed emails can sign in.
- **Admin → Glossary** holds the base glossary, which also defines the languages offered to users.

## 5. Install a frontend

Do these steps once per frontend. The example files are in the [`deploy/`](../deploy/) folder of this repository: clone it, or download the folder you need.

### 5.1 Access modes and secrets

The backend talks to each frontend's backend port in one of these modes, chosen per frontend when you register it (section 5.5):

| Mode | On the frontend | On the backend | When to use it |
|---|---|---|---|
| **Signed — installation secret** (default) | `TRANSLATOR_BACKEND_SECRET=<installation secret>` | `TRANSLATOR_FRONTEND_SECRET=<same value>`; register with **the address only** | Most installations |
| **Signed — own secret** | `TRANSLATOR_BACKEND_SECRET=<this frontend's secret>` | The same secret in that frontend's registration | To isolate one frontend, e.g. on a server run by a third party |
| **Trusted network — unsigned** | `BACKEND_SURFACE_AUTH=trusted-network` (no secret) | Mode *Trusted network* | Only when nothing but the backend can reach the frontend's backend port: the internal Docker network of T3, or a closed network segment |

Generate a secret (at least 32 characters):

```bash
openssl rand -hex 32
```

Keep secrets in private `.env` files (`chmod 600 .env`), never in the repository or in images. The variable names start with `TRANSLATOR_` so they do not collide with other applications on the same machine.

**What each mode gives up:**

| | Installation secret | Own secret | Trusted network |
|---|---|---|---|
| Someone who can reach the backend port without the secret | Rejected (`401`) | Rejected (`401`) | **Full access**: reads and consumes queued sign-in and job requests, downloads the uploaded documents, changes the frontend's configuration and branding, sends job status and result files to users |
| A captured request replayed, or modified in transit | Rejected | Rejected | **Accepted** |
| One secret leaks | **Every** frontend that shares the installation secret is exposed until it is rotated everywhere | Only that frontend | — |
| Rotation | Backend and every frontend | One frontend | — |
| Clocks in sync | Needed | Needed | Not needed |
| Protection rests on | The secret | The secret | **The network alone** |

The admin panel shows each frontend's mode as a badge (**signed**, **trusted network · unsigned**). Each frontend also reports its own mode: if a frontend registered as signed is running with `BACKEND_SURFACE_AUTH=trusted-network`, the panel shows **frontend accepts unsigned**, because the signature then protects nothing. A trusted-network frontend logs a warning at startup and every hour.

*If you lose a secret:* nothing is lost. A secret only proves who is calling; it protects no stored data. Generate a new one and put it in both places (section 7.4).

**Result size.** The result the backend sends to a frontend is a ZIP with the original and one file per target language; Office files barely compress, so a 25 MB document into 16 languages is about 414 MB. The backend port accepts up to **512 MB** per request. A larger result is not sent: the user's portal shows its size and the limit, and the backend logs it. The examples give the frontend `mem_limit: 1536m` for this reason; a frontend that only handles small documents can run with less.

### 5.2 T3 — same machine as the backend

The T3 example runs **both** the backend and one frontend.

```bash
cd deploy/t3-same-host
cp .env.example .env
```

Edit `.env`: set `FRONTEND_PORT` and `TRANSLATOR_BACKEND_SECRET` (and the image tags if you want to pin them). The example passes that same value to the backend as its installation secret. Then:

```bash
docker compose up -d
```

The backend and the frontend run in separate containers. The frontend's backend port is **not published** on the host; the backend reaches it over an internal network that only the two share, and the frontend has no route to the backend. Register it with the URL `http://translator-frontend:8080` and the public address users open.

Here the trusted-network mode is acceptable (`BACKEND_SURFACE_AUTH=trusted-network` in `.env`, then register in mode *Trusted network*), since only the backend shares that network; signed mode remains the default.

Residual risk: on that internal network the frontend container can open a connection to the backend's admin port, which is protected only by the admin login. Keep the admin password strong, or place the frontends on another machine for sensitive deployments.

### 5.3 T1 — another machine on the same network

```bash
cd deploy/t1-lan
cp .env.example .env
```

Edit `.env`:

- `FRONTEND_PORT`: the public port on this machine.
- `PUBLIC_BIND`: `127.0.0.1` if users arrive through a tunnel on this machine; the machine's LAN address if office users connect directly.
- `BACKEND_BIND`: **this machine's LAN address**, the one the backend can reach. Do not use `0.0.0.0` on a machine with other interfaces.
- `FRONTEND_BACKEND_PORT`: the backend port on this machine.
- `TRANSLATOR_BACKEND_SECRET`: the installation secret or this frontend's own secret.

```bash
docker compose up -d
```

Register it with the URL `http://<BACKEND_BIND>:<FRONTEND_BACKEND_PORT>`. Allow that port in the machine's firewall **only from the backend's address**. Use signed mode: other devices on the LAN can usually reach that port.

### 5.4 T2 — a remote server (VPS)

On the server (Docker installed, only SSH open to the Internet):

```bash
cd deploy/t2-vps
cp .env.example .env
```

Edit `.env`: `TRANSLATOR_BACKEND_SECRET` and `TUNNEL_TOKEN` (from the Cloudflare tunnel you create in section 6), and `FRONTEND_TAG`. Then:

```bash
docker compose up -d
```

The server opens no incoming ports: a Cloudflare Tunnel makes an outgoing connection and publishes two hostnames, one for users and one private hostname for the backend. Section 6 explains how to create them. Register the frontend with the URL `https://<private hostname>`, the two Access headers, and the public address `https://<users hostname>`. Use signed mode; an own secret is a good choice for a server run by someone else.

The example also runs Watchtower to update the frontend nightly (section 7.1).

### 5.5 Register the frontend in the backend

In **Admin → Frontends → Add Frontend**:

- **URL:** the address of the frontend's **backend port** (not the public address). It depends on the topology, see above.
- **Name:** anything recognisable (optional).
- **Public address (emailed links):** the address users open, for example `https://translate.example.org`. The one-time download link in the result email points here. Leave it blank only for a frontend whose URL above is also what users open (legacy).
- **Backend access:** *Signed (recommended)*, *Trusted network — unsigned*, or *Legacy* (only for frontends deployed before the two-port layout; migrate them when you update them).
- **Own secret** (signed mode, optional): leave it blank to use the installation secret. The line under *Add Frontend* tells you whether the backend has one. Without an installation secret, an own secret is required.
- **Extra headers** (optional; T2): `CF-Access-Client-Id` and `CF-Access-Client-Secret`, from the Cloudflare Access service token.

When you register, the backend **checks that the frontend answers in the chosen mode** before storing it. If it fails, the message tells you why: unreachable, signature rejected (check the secret and the clocks), the frontend requires signing, or the URL is not a backend port.

A healthy frontend shows as **online** with its mode badge. To change the URL, public address, mode, secret or headers later, use the frontend's **Security** button; the change is checked against the frontend before it is saved.

A frontend starts **unconfigured**: set its app language and sign-in mode with **Configure**, and its look with **Branding**. Its whitelist is managed in **Registered Users**.

### 5.6 Check it (read-only)

- Public port: `GET /` returns `200`; `GET /internal/config` returns `200`; `GET /backend/v1/health` returns `404` (the public port does not serve the backend routes).
- Backend port, **without** a signature (signed mode): `GET /backend/v1/health` returns `401`.
- **Admin → Frontends:** the frontend appears **online** with the expected badge.
- Do not call `GET /backend/v1/queue` by hand on a frontend in use: it hands the queued sign-in and job requests to whoever calls it, and the backend then never sees them.

### 5.7 More frontends

Repeat section 5 with a different public port (and a different backend port if the machine is shared) and a different project name (`docker compose -p <name>`). With the installation secret every frontend uses the same `TRANSLATOR_BACKEND_SECRET`; with own secrets, a different one each. Each frontend has its own data volume.

**With Portainer:** a stack from the repository with compose path `docker-compose.frontend.yml` and, as environment variables, `FRONTEND_PORT`, `FRONTEND_BACKEND_PORT`, `BACKEND_BIND` (default `127.0.0.1`) and either `TRANSLATOR_BACKEND_SECRET` or `BACKEND_SURFACE_AUTH=trusted-network`.

### 5.8 Upgrading a frontend deployed before the two-port layout

Such a frontend keeps working with an upgraded backend: it shows as **legacy** and uses the old protocol, even after `TRANSLATOR_FRONTEND_SECRET` is set. To move it:

1. Upgrade the backend (and set `TRANSLATOR_FRONTEND_SECRET` if you use the installation secret).
2. Redeploy the frontend with the new image, `TRANSLATOR_BACKEND_SECRET` set (or `BACKEND_SURFACE_AUTH=trusted-network`) and the backend port published (`FRONTEND_BACKEND_PORT`, `BACKEND_BIND`). The public port and the tunnel do not change.
3. In **Admin → Frontends → Security**, set the backend-port URL, the public address and the mode in **one save**. The save is checked against the frontend before it is stored.

Do steps 2 and 3 back to back: the new image no longer serves the old routes, so between the two steps sign-ins and submissions wait in the frontend until the backend can poll it again. If a script re-points frontend URLs after a network change, it must keep the **backend port** in the URL it writes.

## 6. Public access with a Cloudflare Tunnel

A tunnel lets users reach a frontend without opening any incoming port. In the Cloudflare Zero Trust dashboard:

1. **Create a tunnel** (remotely managed, *Cloudflared*) and copy its token into the frontend's `TUNNEL_TOKEN`.
2. **Public hostname for users:** point `https://<users hostname>` to `http://translator-frontend:80` (the service name in the compose network), or to `http://localhost:<FRONTEND_PORT>` if `cloudflared` runs on the host. **Map only the public port here.** This hostname is the frontend's public address in the admin.
3. **Private hostname for the backend (T2):** point `https://<private hostname>` to `http://translator-frontend:8080`.
4. **Protect the private hostname with Cloudflare Access:** create a *service token*, then a self-hosted Access application for the private hostname with a single policy whose action is **Service Auth** and which includes only that token. Enable **Protect with Access** on that hostname in the tunnel so that `cloudflared` validates the Access credential. Copy the token's client ID and secret (the secret is shown once) into the frontend's extra headers in the backend.

When the domain is managed by Cloudflare, adding a hostname to the tunnel creates its DNS record. Cloudflare's proxy accepts uploads up to 100 MB on most plans, which covers the 25 MB upload limit.

If you do not use Cloudflare, any reverse proxy that terminates HTTPS in front of the **public port** works. Whatever you use, **never publish the backend port to the open Internet.**

## 7. Operate it

### 7.1 Updates

```bash
docker compose pull
docker compose up -d
```

To update automatically, add the label `com.centurylinklabs.watchtower.enable=true` to the service and run Watchtower with `--label-enable` on a nightly schedule, so only labelled containers are touched. With recent Docker Engines (checked on 29.4) the `containrrr/watchtower` image needs `DOCKER_API_VERSION` set to a supported API version such as `1.44`; otherwise it stops with "client version 1.25 is too old". The T2 example already does this.

Use `latest`, or pin `sha-<commit>` and update on purpose. To roll back, set the previous `sha-<commit>` tag in the compose file and run `docker compose up -d`.

### 7.2 Back up

- **The data volume** (everything). Compose prefixes volume names with the project name, so copy it through the running container:

  ```bash
  docker run --rm --volumes-from "$(docker compose ps -q translator-backend)" -v "$PWD":/backup alpine \
    tar czf /backup/translator-data.tgz -C /app/data .
  ```

  Stop the backend first (`docker compose stop`, then use the container ID from `docker compose ps -aq translator-backend`) if you need a perfectly consistent copy.
- **Configuration only:** Admin → Frontends → **Global Config Backup** → *Export global config* / *Import global config* (the whole `config/`). After importing, **restart the backend**. The file contains the SMTP password, provider API keys and the frontends' signing secrets and extra headers: store it like a password.
- **Frontends** hold only transient queues, results waiting to be downloaded, and a copy of what the backend pushed to them. If a frontend's volume is lost, recreate it and restart the backend, which then pushes that frontend's configuration, branding and languages again.

### 7.3 Logs and health

```bash
docker compose logs --tail 100
docker compose ps
```

- Backend: `GET /health` returns `{"status":"ok"}`.
- Frontend: `GET /nginx-health` on the public port returns `ok`.
- Admin → **Queue** lists running, waiting and failed jobs, with the recorded error of each failure.

### 7.4 Rotate a secret without downtime

**One frontend's own secret:**

1. On the frontend, put the new value in `TRANSLATOR_BACKEND_SECRET` and the old value in `TRANSLATOR_BACKEND_SECRET_PREVIOUS`, then `docker compose up -d`.
2. In **Admin → Frontends → Security**, enter the new secret and save.
3. Empty `TRANSLATOR_BACKEND_SECRET_PREVIOUS` and run `docker compose up -d` again.

**The installation secret:**

1. On every frontend that uses it, set the new value in `TRANSLATOR_BACKEND_SECRET` and the old one in `TRANSLATOR_BACKEND_SECRET_PREVIOUS`, then `docker compose up -d`.
2. On the backend, set the new `TRANSLATOR_FRONTEND_SECRET` and restart it.
3. On every frontend, empty `TRANSLATOR_BACKEND_SECRET_PREVIOUS` and run `docker compose up -d`.

### 7.5 Reset the admin password

```bash
docker compose exec translator-backend rm /app/data/.admin_hash
docker compose restart translator-backend
```

Then open the admin panel and create a new account.

## 8. Security checklist

- [ ] The backend's admin port is not published on an untrusted network.
- [ ] No frontend publishes its backend port to the open Internet.
- [ ] Frontends use signed mode unless only the backend can reach their backend port; secrets have at least 32 random characters, live in private `.env` files and are never committed.
- [ ] Users reach the frontends only through HTTPS, and each frontend's public address in the admin is that HTTPS address.
- [ ] Clocks are synchronised on all machines.
- [ ] The admin password is long and unique.
- [ ] The data volume is backed up, and configuration exports are stored like passwords.
- [ ] You know whether the translation model is local or at a cloud provider, and your data-protection obligations are met.
- [ ] On a remote server, only the administration port (SSH) is open, restricted to key-based login.
- [ ] Updates are applied regularly (or automated for labelled containers).

## 9. Troubleshooting

**The frontend is registered but shows offline, or the backend says "Cannot reach frontend".**
Check that the URL is the frontend's **backend port** address and that the backend machine can reach it (`curl` from the backend host). In T2, check the tunnel is running and the Access headers are correct.

**"Rejected the signature" (HTTP 401).**
The secret differs between the frontend and the backend (installation secret or own secret), or the clocks are more than about 2 minutes apart. Check both, and synchronise time (NTP).

**"Requires signed requests" when registering in trusted-network mode.**
The frontend runs in signed mode. Either register it as *Signed*, or start it with `BACKEND_SURFACE_AUTH=trusted-network`.

**"No backend surface at …".**
The URL points to the public port, or the frontend runs an image from before the two-port layout. Use the backend port; for an old frontend, choose mode *Legacy* or update it.

**Users do not receive the sign-in code, or the result email.**
Check **Admin → Settings → Email server (SMTP)** and the backend logs. Only emails in **Registered Users** receive a code; the portal answers the same way for any email, by design.

**The link in the result email does not open.**
The frontend has no public address, so the link points to its backend port. Set it in **Admin → Frontends → Security**; the backend logs a warning for each email sent without one.

**"The result is too large to download here".**
The ZIP of the original plus all translations is larger than the 512 MB a frontend accepts. Translate into fewer languages per job, or split the document.

**A job stays queued.**
Scheduled jobs run inside the scheduling window (Admin → Settings); immediate jobs run as soon as the queue is free, one at a time. Admin → Queue shows the order and lets you prioritise.

**The language model does not answer.**
Check the connection status in **Admin → LLM**. From inside the container, `host.docker.internal` only works on Docker Desktop and OrbStack, or on Linux with the `extra_hosts` entry.

## 10. Stop and remove

```bash
docker compose down
```

This keeps the data. To delete the data as well (irreversible), remove the volumes: `docker compose down -v`.

## Appendix: ports and variables

| Item | Container port | Default | Who uses it |
|---|---|---|---|
| Backend admin panel and API | `8000` | published on `127.0.0.1:8000` in the example | Administrator |
| Frontend public surface | `80` | `FRONTEND_PORT` / `PUBLIC_BIND` | Users' browsers, emailed links |
| Frontend backend surface | `8080` | `FRONTEND_BACKEND_PORT` / `BACKEND_BIND` | The backend only |

| Variable | Where | Meaning |
|---|---|---|
| `TRANSLATOR_FRONTEND_SECRET` | backend | Installation secret: signs requests to every signed frontend without its own secret (at least 32 characters) |
| `TRANSLATOR_BACKEND_SECRET` | frontend | Signing secret: the installation secret or this frontend's own secret (at least 32 characters) |
| `TRANSLATOR_BACKEND_SECRET_PREVIOUS` | frontend | Old secret, accepted while rotating |
| `BACKEND_SURFACE_AUTH` | frontend | `signed` (default) or `trusted-network` (no signature check; see section 5.1). `ALLOW_UNSIGNED_BACKEND_SURFACE=true` is an older name for `trusted-network` |
| `FRONTEND_PORT`, `PUBLIC_BIND` | frontend | Public port and the address it listens on |
| `FRONTEND_BACKEND_PORT`, `BACKEND_BIND` | frontend | Backend port and the address it listens on (default `127.0.0.1`) |
| `BACKEND_PORT` | backend (`docker-compose.backend.yml`) | Host port of the admin panel |
| `TUNNEL_TOKEN` | frontend (T2) | Cloudflare Tunnel token |
| `FRONTEND_TAG`, `BACKEND_TAG` | compose | Image tag to run |
| `DEPLOYMENT_JSON_PATH` | backend, frontend | Path of the deployment configuration file inside the container |
