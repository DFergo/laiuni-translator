"""LLM provider abstraction — connection registry + protocol adapters (Sprint 19).

A connection registry (connection_registry.py) replaces the hardcoded
Ollama/LM Studio wiring. Three protocol adapters sit behind a common
interface:

  - ``openai``    OpenAI-compatible chat completions + /models (LM Studio,
                  OpenAI, OpenRouter, vLLM, LiteLLM, …). Bearer auth.
  - ``anthropic`` native Messages API (/v1/messages SSE) + /v1/models. System
                  message hoisted to a top-level param; ``max_tokens`` is
                  required by the API so a blank value is force-filled to 4096.
  - ``ollama``    native /api/chat (newline-delimited JSON) + /api/tags, with
                  ``num_ctx`` via options and warmup.

Slots reference a (connection, model) pair instead of a raw provider string.
Parameters (temperature/max_tokens/num_ctx) are optional overrides: sent only
when set; blank → the provider/model default applies.

Sprint 17 behaviors preserved: fallback cascade + per-slot circuit breaker,
now keyed by ``connection_id:model``.
"""

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, AsyncIterator

import httpx

from src.services.connection_registry import connections

logger = logging.getLogger("backend.llm")

# Anthropic requires max_tokens; used when a slot leaves it blank.
_ANTHROPIC_DEFAULT_MAX_TOKENS = 4096
_ANTHROPIC_VERSION = "2023-06-01"

# ---------------------------------------------------------------------------
# Message normalisation (shared by adapters)
# ---------------------------------------------------------------------------


def _split_multimodal(content: Any) -> tuple[str, list[dict[str, str]]]:
    """Split OpenAI-style content into (text, images).

    ``content`` is either a plain string or a list of parts
    ``{"type": "text"|"image_url", ...}``. Returns the concatenated text and a
    list of ``{"media_type", "data"}`` for any base64 data-URL images. Used by
    the ollama/anthropic adapters, which do not accept the OpenAI image_url
    shape natively.
    """
    if isinstance(content, str):
        return content, []
    text_parts: list[str] = []
    images: list[dict[str, str]] = []
    for part in content or []:
        if part.get("type") == "text":
            text_parts.append(part.get("text", ""))
        elif part.get("type") == "image_url":
            url = part.get("image_url", {}).get("url", "")
            m = re.match(r"data:(?P<mt>[^;]+);base64,(?P<data>.+)", url, re.DOTALL)
            if m:
                images.append({"media_type": m.group("mt"), "data": m.group("data")})
    return "\n".join(text_parts), images


# ---------------------------------------------------------------------------
# Protocol adapters
# ---------------------------------------------------------------------------


class OpenAIAdapter:
    """OpenAI-compatible chat completions. base_url already includes /v1."""

    def _headers(self, conn: dict[str, Any]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if conn.get("api_key"):
            headers["Authorization"] = f"Bearer {conn['api_key']}"
        return headers

    async def list_models(self, conn: dict[str, Any]) -> list[str]:
        url = f"{conn['base_url'].rstrip('/')}/models"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=self._headers(conn))
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

    async def stream(
        self, conn, model, messages, temperature, max_tokens, num_ctx, enable_thinking=None
    ) -> AsyncIterator[str]:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        # Sprint 9 (ADR-010): disable the model's reasoning pass (Qwen/oMLX) to cut
        # latency + tokens. Passthrough only for openai-compatible endpoints.
        if enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
        url = f"{conn['base_url'].rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers(conn)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        token = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                        if token:
                            yield token
                    except (ValueError, KeyError, IndexError):
                        continue

    async def warmup(self, conn, model):
        return  # no-op — only ollama benefits from warmup


class AnthropicAdapter:
    """Native Anthropic Messages API."""

    def _headers(self, conn: dict[str, Any]) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": conn.get("api_key", ""),
            "anthropic-version": _ANTHROPIC_VERSION,
        }

    async def list_models(self, conn: dict[str, Any]) -> list[str]:
        url = f"{conn['base_url'].rstrip('/')}/v1/models"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=self._headers(conn))
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

    def _convert_messages(self, messages) -> tuple[str, list[dict[str, Any]]]:
        """Hoist system messages to a top-level string; convert the rest to
        Anthropic content blocks."""
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                text, _ = _split_multimodal(msg["content"])
                system_parts.append(text)
                continue
            text, images = _split_multimodal(msg["content"])
            blocks: list[dict[str, Any]] = []
            if text:
                blocks.append({"type": "text", "text": text})
            for img in images:
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img["data"],
                    },
                })
            converted.append({"role": msg["role"], "content": blocks or text})
        return "\n\n".join(p for p in system_parts if p), converted

    async def stream(
        self, conn, model, messages, temperature, max_tokens, num_ctx, enable_thinking=None
    ) -> AsyncIterator[str]:
        system, msgs = self._convert_messages(messages)
        body: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "stream": True,
            # max_tokens is required by the API — force-fill when blank (decision 3)
            "max_tokens": max_tokens if max_tokens is not None else _ANTHROPIC_DEFAULT_MAX_TOKENS,
        }
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        url = f"{conn['base_url'].rstrip('/')}/v1/messages"
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers(conn)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except ValueError:
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield delta["text"]
                    elif event.get("type") == "message_stop":
                        break

    async def warmup(self, conn, model):
        return


class OllamaAdapter:
    """Native Ollama API (/api/chat, /api/tags). num_ctx via options."""

    def _headers(self, conn: dict[str, Any]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if conn.get("api_key"):
            headers["Authorization"] = f"Bearer {conn['api_key']}"
        return headers

    async def list_models(self, conn: dict[str, Any]) -> list[str]:
        url = f"{conn['base_url'].rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=self._headers(conn))
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]

    def _convert_messages(self, messages) -> list[dict[str, Any]]:
        """Convert OpenAI-style messages to Ollama native (images as a base64
        list on the message)."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            text, images = _split_multimodal(msg["content"])
            entry: dict[str, Any] = {"role": msg["role"], "content": text}
            if images:
                entry["images"] = [img["data"] for img in images]
            out.append(entry)
        return out

    async def stream(
        self, conn, model, messages, temperature, max_tokens, num_ctx, enable_thinking=None
    ) -> AsyncIterator[str]:
        options: dict[str, Any] = {}
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        body: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": True,
        }
        if options:
            body["options"] = options
        url = f"{conn['base_url'].rstrip('/')}/api/chat"
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers(conn)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    token = chunk.get("message", {}).get("content")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break

    async def warmup(self, conn, model):
        """Pre-load an Ollama model into VRAM with a minimal request."""
        url = f"{conn['base_url'].rstrip('/')}/api/chat"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "options": {"num_predict": 1},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=self._headers(conn))
            resp.raise_for_status()


_ADAPTERS: dict[str, Any] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "ollama": OllamaAdapter(),
}


def _adapter_for(conn: dict[str, Any]):
    adapter = _ADAPTERS.get(conn.get("type", ""))
    if adapter is None:
        raise ValueError(f"Unknown connection type: {conn.get('type')}")
    return adapter


# ---------------------------------------------------------------------------
# Slot resolution helpers (used by the translation loop)
# ---------------------------------------------------------------------------


def slot_settings(settings: dict[str, Any], slot: str) -> dict[str, Any]:
    """Resolve LLM settings for a given slot.

    Connection + model fall back to the inference slot (so an unconfigured
    slot reuses inference). Parameters do NOT fall back: a blank param stays
    ``None`` and is omitted from the request (provider default applies).

    Returns {connection_id, model, temperature, max_tokens, num_ctx, _slot_name}.
    """
    connection_id = settings.get(f"{slot}_connection") or settings.get("inference_connection")
    model = settings.get(f"{slot}_model") or settings.get("inference_model")
    return {
        "connection_id": connection_id,
        "model": model,
        "temperature": settings.get(f"{slot}_temperature"),
        "max_tokens": settings.get(f"{slot}_max_tokens"),
        "num_ctx": settings.get(f"{slot}_num_ctx"),
        "_slot_name": slot,
    }


# Fallback chains by primary slot role.
_FALLBACK_CHAINS: dict[str, list[str]] = {
    "summariser": ["summariser", "reporter", "inference"],
    "reporter": ["reporter", "inference"],
    "translation": ["translation", "inference"],
    "inference": ["inference"],
}


def build_fallback_chain(settings: dict[str, Any], primary_slot: str) -> list[dict[str, Any]]:
    """Build a list of slot configs to try in order (primary → fallbacks).

    Deduplicates slots that resolve to the same connection:model.
    """
    slot_names = _FALLBACK_CHAINS.get(primary_slot, [primary_slot])
    configs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in slot_names:
        cfg = slot_settings(settings, name)
        key = f"{cfg['connection_id']}:{cfg['model']}"
        if key in seen:
            continue
        seen.add(key)
        configs.append(cfg)
    return configs


class LLMProvider:
    """Unified interface over the connection adapters."""

    # Circuit breaker constants
    _CB_THRESHOLD = 3       # failures before marking slot as down
    _CB_WINDOW = 60.0       # seconds — only count recent failures
    _CB_COOLDOWN = 300.0    # seconds — how long a down slot stays down

    def __init__(self):
        self._slot_failures: dict[str, list[float]] = {}
        # Track which fallback was last used, for email notifications
        self.last_fallback_event: dict[str, Any] | None = None

    # --- Circuit breaker (keyed by connection:model) ---

    def _slot_key(self, connection_id: str, model: str) -> str:
        return f"{connection_id}:{model}"

    def is_slot_down(self, connection_id: str, model: str) -> bool:
        key = self._slot_key(connection_id, model)
        failures = self._slot_failures.get(key, [])
        now = time.time()
        recent = [t for t in failures if now - t < self._CB_WINDOW]
        self._slot_failures[key] = recent
        if len(recent) >= self._CB_THRESHOLD:
            if now - recent[-1] < self._CB_COOLDOWN:
                return True
            self._slot_failures[key] = []
        return False

    def _mark_failure(self, connection_id: str, model: str):
        key = self._slot_key(connection_id, model)
        self._slot_failures.setdefault(key, []).append(time.time())

    def _mark_success(self, connection_id: str, model: str):
        key = self._slot_key(connection_id, model)
        self._slot_failures.pop(key, None)

    def get_slot_health(self) -> dict[str, str]:
        """Return per-slot health: {"connection:model": "down"|"degraded"}."""
        result: dict[str, str] = {}
        now = time.time()
        for key, failures in list(self._slot_failures.items()):
            recent = [t for t in failures if now - t < self._CB_WINDOW]
            if len(recent) >= self._CB_THRESHOLD and now - recent[-1] < self._CB_COOLDOWN:
                result[key] = "down"
            elif recent:
                result[key] = "degraded"
        return result

    # --- Health Checks (lesson #3: always try-except) ---

    async def check_connection(self, conn: dict[str, Any]) -> dict[str, Any]:
        """Probe one connection's model list. Never raises."""
        try:
            models = await _adapter_for(conn).list_models(conn)
            return {"status": "online", "models": models}
        except Exception as e:
            return {"status": "offline", "error": str(e), "models": []}

    async def check_health(self) -> dict[str, Any]:
        """Probe all enabled connections in parallel. Returns {conn_id: {...}}."""
        enabled = connections.enabled()
        results = await asyncio.gather(
            *(self.check_connection(c) for c in enabled), return_exceptions=True
        )
        health: dict[str, Any] = {}
        for conn, res in zip(enabled, results):
            if isinstance(res, Exception):
                health[conn["id"]] = {"status": "offline", "error": str(res), "models": []}
            else:
                health[conn["id"]] = res
        return health

    # --- Inference ---

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        connection_id: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        num_ctx: int | None = None,
        enable_thinking: bool | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from a specific (connection, model).

        Resolves the connection record from the registry and delegates to its
        protocol adapter. Parameters are optional — omitted when ``None``.
        """
        conn = connections.get(connection_id) if connection_id else None
        if conn is None:
            raise ConnectionError(f"No such connection: {connection_id}")
        if not conn.get("enable", True):
            raise ConnectionError(f"Connection disabled: {connection_id}")
        model = model or ""
        if not model:
            raise ValueError(f"No model set for connection {connection_id}")

        logger.info(f"Using connection {connection_id} ({conn['type']}) model {model}")

        tokens_yielded = 0
        async for token in _adapter_for(conn).stream(
            conn, model, messages, temperature, max_tokens, num_ctx, enable_thinking
        ):
            tokens_yielded += 1
            yield token

        if tokens_yielded == 0:
            logger.warning(
                f"stream_chat produced ZERO tokens — connection={connection_id} model={model}. "
                f"Likely model eviction, context overflow, or empty <think> block."
            )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        connection_id: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        num_ctx: int | None = None,
    ) -> str:
        """Non-streaming chat completion. Returns full response."""
        full_response = ""
        async for token in self.stream_chat(
            messages, connection_id=connection_id, model=model,
            temperature=temperature, max_tokens=max_tokens, num_ctx=num_ctx,
        ):
            full_response += token
        return full_response

    async def warmup(self, connection_id: str, model: str):
        """Warm up a model on its connection (ollama only does real work)."""
        conn = connections.get(connection_id)
        if conn is None or not model:
            return
        await _adapter_for(conn).warmup(conn, model)

    # --- Fallback cascade (Sprint 17, re-keyed to connection:model) ---

    async def stream_chat_with_fallback(
        self,
        messages: list[dict[str, Any]],
        slot_configs: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        """Stream tokens, trying each slot config in order until one succeeds.

        ``slot_configs`` is a list of dicts with keys:
            connection_id, model, temperature, max_tokens, num_ctx, _slot_name
        Typically built via ``build_fallback_chain(settings, primary_slot)``.
        """
        last_error: Exception | None = None

        for i, cfg in enumerate(slot_configs):
            connection_id = cfg.get("connection_id", "")
            model = cfg.get("model", "")
            slot_name = cfg.get("_slot_name", f"slot-{i}")

            if self.is_slot_down(connection_id, model):
                logger.info(f"Skipping {slot_name} ({connection_id}/{model}) — circuit breaker open")
                continue

            try:
                tokens_yielded = 0
                async for token in self.stream_chat(
                    messages=messages,
                    connection_id=connection_id,
                    model=model,
                    temperature=cfg.get("temperature"),
                    max_tokens=cfg.get("max_tokens"),
                    num_ctx=cfg.get("num_ctx"),
                    enable_thinking=cfg.get("enable_thinking"),
                ):
                    tokens_yielded += 1
                    yield token

                if tokens_yielded == 0:
                    raise RuntimeError(f"Zero tokens from {connection_id}/{model}")

                self._mark_success(connection_id, model)
                if i > 0:
                    failed_c = slot_configs[0].get("connection_id", "")
                    failed_m = slot_configs[0].get("model", "")
                    logger.warning(f"{slot_name} served by fallback #{i}: {connection_id}/{model}")
                    self.last_fallback_event = {
                        "slot": slot_name,
                        "failed_connection": failed_c,
                        "failed_model": failed_m,
                        "fallback_connection": connection_id,
                        "fallback_model": model,
                        "timestamp": time.time(),
                    }
                    asyncio.create_task(self._notify_slot_event(
                        slot_name, failed_c, failed_m,
                        str(last_error or "unknown"),
                        fallback_provider=connection_id,
                        fallback_model=model,
                    ))
                return

            except Exception as e:
                self._mark_failure(connection_id, model)
                last_error = e
                if i < len(slot_configs) - 1:
                    next_cfg = slot_configs[i + 1]
                    logger.warning(
                        f"{slot_name} ({connection_id}/{model}) failed: {e}. "
                        f"Falling back to {next_cfg.get('_slot_name', next_cfg.get('model'))}"
                    )
                else:
                    logger.error(
                        f"{slot_name} ({connection_id}/{model}) failed: {e}. No more fallbacks."
                    )

        # All slots failed — notify admin (offline, no fallback)
        if slot_configs:
            first = slot_configs[0]
            asyncio.create_task(self._notify_slot_event(
                first.get("_slot_name", "unknown"),
                first.get("connection_id", ""),
                first.get("model", ""),
                str(last_error or "all slots exhausted"),
            ))

        if last_error:
            raise last_error
        raise RuntimeError("No LLM slots available (all circuit breakers open)")

    async def _notify_slot_event(
        self,
        slot_name: str,
        failed_provider: str,
        failed_model: str,
        error: str,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ):
        """Fire-and-forget email notification for slot failures."""
        try:
            from src.services.smtp_service import notify_slot_failure
            await notify_slot_failure(
                slot_name=slot_name,
                failed_provider=failed_provider,
                failed_model=failed_model,
                error=error,
                fallback_provider=fallback_provider,
                fallback_model=fallback_model,
            )
        except Exception as e:
            logger.debug(f"Slot failure notification skipped: {e}")

    async def chat_with_fallback(
        self,
        messages: list[dict[str, Any]],
        slot_configs: list[dict[str, Any]],
    ) -> str:
        """Non-streaming chat with fallback cascade. Returns full response."""
        full_response = ""
        async for token in self.stream_chat_with_fallback(messages, slot_configs):
            full_response += token
        return full_response


# Singleton
llm = LLMProvider()
