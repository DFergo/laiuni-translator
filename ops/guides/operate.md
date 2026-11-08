# Operating: updates, backups, secrets

## Updates
- Images: tag `latest` follows the main version; `sha-<commit>` pins one. Update (ask first): `compose action="pull" apply=true`, then `compose action="up" apply=true` in each folder (backend, frontends). Built-from-source backends: update the repo (`git pull` in the repo folder), then `compose up` (rebuilds).
- `t2-vps*` frontends run Watchtower: they update themselves at night.
- Update the repo too (`git pull`) so these guides and the MCP match the version.
- After updating: `status`, `test_smoke`. A backend older than the machine API answers 404 on `/api/v1`: update it.

## Backups
- Everything the backend stores is in the Docker volume (`translator-data`): configuration, the job database, documents in retention, connections (with keys), the admin password hash.
- Configuration only (no documents): `admin_api GET /admin/export/global` (contains provider keys: `confirm_content=true`, ask) — or from the admin panel.
- Full backup of the volume (ask first; the backend keeps running):
  ```bash
  docker run --rm -v <project>_translator-data:/data -v ~/translator-backups:/backup alpine \
    tar czf /backup/translator-data-$(date +%F).tar.gz -C /data .
  ```
  (`docker volume ls` shows the exact volume name.) The archive holds keys and possibly users' documents: keep it encrypted and access-controlled.

## What is deleted on its own
Results and uploaded originals are hard-deleted `retention_hours` after a job finishes (48 h by default); cancelled jobs the same. Tell the user, and do not raise it without a reason.

## Rotating the signing secret (no downtime)
1. On each frontend: `TRANSLATOR_BACKEND_SECRET_PREVIOUS` = current value, `TRANSLATOR_BACKEND_SECRET` = new value (`env_set`), restart.
2. On the backend: `TRANSLATOR_FRONTEND_SECRET` = new value, restart.
3. Later, empty `TRANSLATOR_BACKEND_SECRET_PREVIOUS` on the frontends.

## Admin password lost
Delete the admin hash in the volume and create a new account — `docs/INSTALL.md` section 7.5. Ask first.

## API tokens
Revoke any token that may have leaked (`DELETE /admin/api-tokens/{id}`, guide `api`).

## Moving to another machine
Export (`/admin/export/global`, `/admin/export/frontend/{id}`) and import on the new backend, or copy the volume archive. Re-register frontends if the backend's view of their addresses changed.
