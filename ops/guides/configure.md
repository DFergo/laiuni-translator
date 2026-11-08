# Configuration areas (admin panel ↔ API)

Log in first (`backend_connect`, `login`). `admin_api_reference filter="<area>"` lists the exact endpoints and fields of the running version. Read the current value before changing it, show the change, ask, apply.

| Area | Endpoints (prefix `/admin`) | Notes |
|---|---|---|
| Frontends | `/frontends`, `/frontends/{id}`, `/{id}/config`, `/{id}/branding` | guide `frontends`. `DELETE /frontends/{id}` moves it to *deleted* (restorable: `/frontends/deleted`, `/{id}/restore`). |
| Model | `/llm/connections` (+ `/{id}/models`), `/llm/settings`, `/llm/health`, `/llm/models`, `/llm/capabilities`, `/llm/usage`, `/frontends/{id}/llm-settings` | guide `inference`. Parallel jobs are a property of the connection. |
| Glossary | `/knowledge/glossary`, `/knowledge/glossary/upload`, `/knowledge/glossary/coverage`, `/knowledge/glossary/frontend/{id}/config`, `/knowledge/glossary/frontend/{id}` | See below. |
| Organisations | `/knowledge/organizations` | Reference directory added to the prompts. |
| Prompts | `/prompts`, `/prompts/{name}`, `/prompts/{name}/reset`, `/prompts/mode`, `/prompts/custom-frontends`, `/prompts/copy-to-frontend/{id}`, `/prompts/frontend/{id}`, `/prompts/reset-global`, `/llm/translation-prompt` | The translator's instructions (draft, review, context, plain, document). Change only with care; `reset` restores the default. Mode `global` or per-frontend copies. |
| Settings | `/settings` | `retention_hours` (when documents and results are hard-deleted), `app_language`, `schedule_window_start_hour`, `schedule_window_duration_hours`, `schedule_mode` (`scheduled` · `immediate` · `both`), `batch_max`, `format_engine` (`python` · `okapi` · `okapi_noopt`: how .docx/.pptx/.rtf are read and rebuilt; `python` unless fidelity needs the Okapi engine). |
| Email | `/smtp`, `/smtp/test`, `/smtp/authorized-emails`, `/smtp/frontend-notifications/{id}` | guide `email`. |
| Whitelist | `/contacts`, `/contacts/global`, `/contacts/frontend/{id}`, `/contacts/frontend/{id}/copy-from/{src}`, `/contacts/export`, `/contacts/import` | Who may sign in; guide `frontends`. |
| Queue | `/queue` (list), `/queue/{id}/retry`, `/queue/{id}/cancel`, `/queue/{id}/prioritise`, `/queue/{id}/move`, `DELETE /queue/{id}` | See below. |
| Usage | `/usage` | Per user (email, documents, languages, dates); never file names or content; survives retention. |
| API tokens | `/api-tokens` | guide `api`. |
| Portability | `/export/global`, `/export/frontend/{id}`, `/import/global`, `/import/frontend/{id}` | Backups and moving configuration between installations (exports contain provider keys: `confirm_content=true`; imports are destructive). |

## Glossary
The base glossary has 230 terms in 17 languages; a frontend can **append** its own terms or **replace** the base with them (`mode`). `POST /knowledge/glossary/upload` (`admin_upload`, optional `?frontend_id=`) **replaces** the whole glossary with a JSON file — ask first. `/glossary/coverage` shows how many terms exist per language. The languages users can choose are the ones present in the base glossary, so removing a language from it removes it from the portal. Users can also attach their own terms to a document.

## Queue
Jobs run in order of priority, then request time. Scheduled jobs wait for the night window; immediate ones start as soon as their connection has a free slot (guide `inference`, parallel jobs). `GET /queue` shows each running job's progress, its connection and the failed jobs with their reason. `retry` re-queues a failed job; `cancel` stops a waiting or running job (portal jobs end up in the failed list as "Cancelled by the admin", jobs from the API as `cancelled`); `move` (`up|down`) and `prioritise` reorder waiting jobs. Submitting the same file with the same options while it is still queued or running is refused as a duplicate.

## Typical requests
- "Run translations immediately, not at night" → `PUT /settings {"schedule_mode": "immediate"}` (or `both` to let users choose).
- "Keep results for a week" → `PUT /settings {"retention_hours": 168}` — longer retention keeps users' documents on disk longer; say so.
- "Use another model" → connection if new, then `PUT /llm/settings {"translation_connection": ..., "translation_model": ...}`, `GET /llm/health`.
- "How much are we spending?" → `GET /llm/usage` (tokens per model; prices are on the provider's site) and `GET /usage`.
- "Add a user" → read `/contacts`, add to the list, `PUT /contacts/global`.
