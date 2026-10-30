# Deployment topologies

Reference for the example compose files in this folder. Step-by-step installation: [`docs/INSTALL.md`](../docs/INSTALL.md).

The frontend container exposes two surfaces on two ports:

| Container port | Surface | Who uses it | Expose it to |
|---|---|---|---|
| `80` | Public: portal + browser routes (`/request-token`, `/verify`, `/jobs…`, `/d/{token}`, `/languages`, `/internal/config`) | Users' browsers, emailed download links | Users / a cloudflared public hostname |
| `8080` | Backend: `/backend/v1/*` (queue, uploaded documents, job status, result ZIPs, config, branding, languages) | The Translator backend only | Only a private path to the backend — never the open Internet |

The backend always initiates the connection (pull-inverse): the frontend never needs to know where the backend is. The backend registers the URL of the frontend's **backend port**, plus the frontend's **public address** (the one users open), which goes into emailed download links.

## Registering a frontend: just the address

Set one **installation secret** on the backend and give the same value to every frontend:

```bash
openssl rand -hex 32        # ≥ 32 characters
```

- Backend: `TRANSLATOR_FRONTEND_SECRET=<value>`
- Each frontend: `TRANSLATOR_BACKEND_SECRET=<value>`

Then **Admin → Frontends → Add Frontend** needs only the backend-port URL (access mode **Signed**, the default) and the public address. A frontend can still get its **own secret** (Security panel), which overrides the installation secret for that frontend only.

The variable names carry the `TRANSLATOR_` prefix so they never collide with HRDD Helper's on a shared host. The protocol (headers, canonical string) is the same in both apps.

## Access modes

| Mode (admin) | Frontend env | What the backend sends | Use it when |
|---|---|---|---|
| **Signed** — installation secret | `TRANSLATOR_BACKEND_SECRET` = backend's `TRANSLATOR_FRONTEND_SECRET` | HMAC-signed requests to `/backend/v1/*` | Default, any topology |
| **Signed** — own secret | `TRANSLATOR_BACKEND_SECRET` = that frontend's secret | Same | You want to isolate one frontend (e.g. on a third-party VPS) |
| **Trusted network — unsigned** | `BACKEND_SURFACE_AUTH=trusted-network` (no secret) | Unsigned requests to `/backend/v1/*` | Only nothing but the backend can reach port 8080 (same-host internal Docker network, closed LAN segment) |
| **Legacy** | — (frontend on the image from before the two-port split) | Old unsigned `/internal/*` routes on the single port | Transition only, until that frontend is updated |

### What each mode gives up

| | Installation secret | Own secret | Trusted network | Legacy |
|---|---|---|---|---|
| Someone who can reach port 8080 but has no secret | Rejected (401) | Rejected (401) | **Full access**: reads and consumes queued sign-in and job requests, downloads uploaded documents, pushes job status, result files, config and branding | Not signed — migrate to a current mode |
| Captured request replayed | Rejected (nonce + ±120 s window) | Rejected | **Accepted** | Not signed |
| Request modified in transit (no TLS) | Rejected (body is signed) | Rejected | **Accepted** | Not signed |
| One frontend's secret leaks | **All** frontends sharing the installation secret are exposed until it is rotated everywhere | Only that frontend | n/a | n/a |
| Rotation | Change `TRANSLATOR_FRONTEND_SECRET` on the backend and `TRANSLATOR_BACKEND_SECRET` on every frontend (use `TRANSLATOR_BACKEND_SECRET_PREVIOUS` on the frontends for a no-downtime switch) | One frontend + its Security panel | n/a | n/a |
| Clock sync needed | Yes (NTP, ±120 s) | Yes | No | No |
| Protection then rests on | The secret | The secret | **The network alone** (`BACKEND_BIND`, internal Docker network, firewall, Cloudflare Access) | Transition only |

The admin shows the mode as a badge on each frontend (**signed**, **trusted network · unsigned**, **legacy**). Frontends report their own mode on every poll: if a frontend registered as signed is running with `BACKEND_SURFACE_AUTH=trusted-network`, the admin shows **frontend accepts unsigned**, because signing then protects nothing. A trusted-network frontend logs a warning at startup and hourly.

## Topologies

| | Where the frontend runs | How the backend reaches port 8080 | Recommended mode | Example |
|---|---|---|---|---|
| **T1** | Another machine on the backend's LAN | `http://<LAN IP>:<FRONTEND_BACKEND_PORT>` (`BACKEND_BIND` = that LAN IP) | Signed (other LAN devices can reach the port) | [`t1-lan/`](t1-lan/) |
| **T2** | A VPS (no VPN) | `https://<backend hostname>` on a cloudflared tunnel, Cloudflare Access with a service token (sent as extra headers) | Signed (own or installation secret) | [`t2-vps/`](t2-vps/) |
| **T3** | Same machine as the backend, separate containers | `http://translator-frontend:8080` over an internal Docker network shared only by the two | Signed; trusted network is acceptable here | [`t3-same-host/`](t3-same-host/) |

One backend can serve frontends in all three topologies and modes at once.

## Result size and memory

The result ZIP holds the original plus one file per target language; Office files barely compress. A 25 MB document into 16 languages is about 414 MB. The backend surface accepts up to **512 MB** per request; a larger result is not sent and the user's portal shows the size and the limit. While a result waits to be downloaded the frontend holds it in memory, peaking at about 2.5× its size during the transfer — hence `mem_limit: 1536m` in the examples. A frontend that only serves small documents or few languages can run with less.

## Upgrading an existing frontend

Frontends registered before the two-port split keep working with an upgraded backend: they show as **legacy** and use the old protocol, even after `TRANSLATOR_FRONTEND_SECRET` is set. To move one:

1. Upgrade the backend (and set `TRANSLATOR_FRONTEND_SECRET` if you use the installation secret).
2. Redeploy the frontend with the new image, `TRANSLATOR_BACKEND_SECRET` set (or `BACKEND_SURFACE_AUTH=trusted-network`) and the backend port published (`FRONTEND_BACKEND_PORT`, `BACKEND_BIND`). The public port and the tunnel stay as they are.
3. In Admin → Frontends → **Security**, set the backend-port URL, the public address and the mode in **one save**. The save is verified against the frontend before it is stored.

Do steps 2 and 3 back to back: the new frontend image no longer serves the old routes, so between them the backend can't poll it (sign-ins and submissions wait in the frontend until it does; a browser waiting on a download gives up after 30 s).

If an IP reconciler re-points frontend URLs after a DHCP change, it must keep the **backend port** in the URL it writes.

## Checks (read-only)

- Public port: `GET /` → 200, `GET /internal/config` → 200, `GET /backend/v1/health` → 404.
- Backend port without a signature: `GET /backend/v1/health` → 401 (signed mode).
- Admin → Frontends shows the frontend **online** with the expected badge.
- Never call `GET /backend/v1/queue` by hand on a live frontend: it consumes queued sign-in and job requests.
