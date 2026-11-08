# AI models: cloud providers or a local model

The app is provider-neutral: the user chooses. Explain the trade-offs, then help them get an account/key or set up a local model. Recommendations: guide `models`.

## What the app needs
One **translation engine**: a **connection** (address + key) plus a **model**. Every call — the draft, the glossary review, the context reading — goes through it. Create the connection once, then assign it (`translation_connection`, `translation_model`). A frontend can use another one (`PUT /admin/frontends/{id}/llm-settings`). Documents can also ask for a specific connection per request through the machine API (guide `api`).

## Privacy — say it plainly
With a cloud provider, the text of every uploaded document is sent to that provider. Ask what is acceptable (guide `onboarding`). Options, from most to least private: a model on the organisation's own machine · an EU provider (e.g. Mistral) · a provider via OpenRouter restricted to providers that do not retain data (OpenRouter privacy settings: zero data retention) · any provider.

## Cloud: getting a key (the user signs up and pays)
| Provider | Sign up | Connection (`type`, `base_url`) |
|---|---|---|
| Mistral (France, EU) | https://console.mistral.ai → API keys | `openai`, `https://api.mistral.ai/v1` |
| OpenRouter (many models, one key) | https://openrouter.ai → Keys; set privacy preferences | `openai`, `https://openrouter.ai/api/v1` |
| DeepSeek (own API) | https://platform.deepseek.com | `openai`, `https://api.deepseek.com/v1` |
| Any OpenAI-compatible service (including oMLX, vLLM) | its console | `openai`, its `/v1` address |
| OpenAI | https://platform.openai.com | `openai`, `https://api.openai.com/v1` |
| Anthropic | https://console.anthropic.com | `anthropic`, `https://api.anthropic.com` |
Most need prepaid credit. Suggest a spending limit in the provider's console.

Key handling: the user pastes the key into a local file (`~/.config/translator-ops/keys.env`, line `MISTRAL_API_KEY=...`), never in the chat. Then:
```
admin_api POST /admin/llm/connections
  {"id": "mistral", "type": "openai", "base_url": "https://api.mistral.ai/v1",
   "api_key": "env:~/.config/translator-ops/keys.env#MISTRAL_API_KEY"}
admin_api GET /admin/llm/connections/mistral/models      # check it works, list models
```
A new backend starts with **no** connections.

## Parallel jobs (important with commercial providers)
By default a connection runs **one job at a time**. A paid cloud provider can take many in parallel, so on its connection turn on **parallel** and choose how many at once:
```
admin_api PUT /admin/llm/connections/mistral  {"parallel": true, "max_concurrent": 4}
```
`max_concurrent` is 1–32 (default 4). Start low: providers answer `429 too many requests` above their rate limits, and then jobs fail. A local model on one machine should stay at 1. Jobs on different connections never block each other. See what is running: `GET /admin/queue` (progress per job).

## Local models (machine with enough memory)
- **LM Studio** (https://lmstudio.ai): enable the local server (port 1234). Connection: `openai`, `http://host.docker.internal:1234/v1`.
- **Ollama** (https://ollama.com): `ollama pull <model>`. Connection: `ollama`, `http://host.docker.internal:11434`.
- **oMLX / vLLM** on a Mac Studio or server: an `openai` connection to its address (`http://<LAN or Tailscale IP>:<port>/v1`, Bearer key if it has one).
- `host.docker.internal` = the machine running the backend container (works on Docker Desktop and OrbStack; the `backend` topology adds it on Linux too; in `t3-same-host` on Linux use the machine's LAN IP). A model server on another machine: use its LAN or Tailscale IP, and make the server listen on that address (Ollama: `OLLAMA_HOST=0.0.0.0`; LM Studio: "serve on local network").
- Memory guide: a 27–31B model at 4-bit quantization needs roughly 18–24 GB for the weights plus context — workable on 32–48 GB machines. Large translation models (hundreds of billions of parameters) need a workstation-class machine. Smaller machines: use a cloud model.

## Assigning the engine
```
admin_api PUT /admin/llm/settings
  {"translation_connection": "mistral", "translation_model": "<model id>",
   "translation_reasoning": "off"}
admin_api GET /admin/llm/health
```
Only the fields sent are changed. Other useful fields: `translation_temperature` (default 0.1 — keep it low), `translation_max_tokens`, `translation_num_ctx`, `translation_glossary_enabled` (true by default: the glossary pass). `translation_reasoning` is `default | off | low | medium | high`: **off** is the default because a reasoning pass can use up the token budget and return an empty answer (the app retries and then fails the job loudly rather than ship a hole). Some models cannot switch reasoning off (e.g. `mistral-large-4`): the admin shows the status of each control per connection and model, and the app drops an optional field the provider rejects and retries. `POST /admin/llm/capabilities` shows what a provider accepts for a connection and model.

## Usage
`GET /admin/llm/usage` — tokens per connection and model, with the prompt-cache hit rate (cached ÷ prompt). Prices are on the provider's site; the app does not know them.
