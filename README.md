# LAIUNI Translator

A self-hostable portal that translates an uploaded document into any of the configured languages, glossary-aware, and emails the results back. Users sign in with a code sent to their email (whitelist), upload one or several documents (`.txt`, `.md`, `.docx`, `.rtf`, `.pptx`), pick the target languages and receive a download link by email.

It runs as two kinds of Docker containers:

- **Backend** — admin panel, job queue, language-model connection, email, and all stored data.
- **Frontend** — the portal users see; one or more, each with its own address, branding and whitelist. The backend polls the frontends; a frontend never connects to the backend.

The translation model can run on your own hardware (any OpenAI-compatible server, or Ollama) or at a cloud provider.

## Install it with an AI agent

Open Claude Code (or another coding agent) in an empty folder and paste:

```
Read https://raw.githubusercontent.com/DFergo/laiuni-translator/main/SETUP-AGENT.md and follow it to install LAIUNI Translator. Ask me before every step that changes something.
```

The agent downloads the app and connects its MCP server (`ops/translator_mcp.py`), which then guides the whole setup: a short survey of what you have and know, the recommended layout, Docker and Tailscale, a VPS, a domain and a Cloudflare Tunnel, AI models, email, frontends and tests — and later day-to-day administration. It asks for your permission before every change, and passwords, keys and tokens never go through the chat.

## Documentation

- **[Installation guide](docs/INSTALL.md)** — requirements, backend and frontend setup, the three deployment topologies, access modes, operation and troubleshooting.
- [Deployment examples](deploy/) — compose files for the backend, and for a frontend on the local network, on a VPS (with Tailscale or Cloudflare Access), or on the same machine as the backend.
- [Agent setup](SETUP-AGENT.md) and [MCP guides](ops/guides/) — what the AI agent follows.
- [Changelog](docs/CHANGELOG.md)

## Images

- `ghcr.io/dfergo/laiuni-translator-backend` (`amd64`, `arm64`)
- `ghcr.io/dfergo/laiuni-translator-frontend` (`amd64`, `arm64`)

Tags: `latest` (the `main` branch) and `sha-<commit>`.

## License

See [LICENSE](LICENSE).
