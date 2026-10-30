"""Per-provider / per-model capability profiles for the LLM adapters (Sprint 37).

The apps were built for LM Studio and Ollama; production also runs on API
providers that differ in which request fields they accept:

  - Mistral rejects any unknown field with HTTP 422 (``extra_forbidden``):
    ``seed``, ``num_ctx``, ``reasoning``, ``chat_template_kwargs``…
    ``reasoning_effort`` values depend on the model (``mistral-large-4``:
    low/medium/high, cannot be switched off; ``mistral-small``/``-medium``:
    none/high).
  - OpenRouter silently ignores unsupported fields (a setting can look active
    and do nothing). Reasoning: ``reasoning: {"enabled": false}`` /
    ``{"effort": ...}``.
  - LM Studio / vLLM (generic OpenAI-compatible): ``chat_template_kwargs``
    ``{"enable_thinking": bool}`` for Qwen-style templates.
  - Anthropic: ``thinking`` with a token budget; temperature must not be set
    while thinking.
  - Ollama: top-level ``think`` (bool); ``num_ctx`` / ``num_predict`` in options.

``num_ctx`` is only an Ollama request option. For every other provider it is
used solely as "context window used for compression" (context_compressor).

Verified live on 2026-10-30 against the Mistral API and OpenRouter (see
tests/fixtures/llm). OpenAI (api.openai.com) and Anthropic mappings follow the
providers' public documentation and were not tested live.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

PROVIDER_KINDS = ("mistral", "openrouter", "openai", "openai_compatible", "anthropic", "ollama")
REASONING_LEVELS = ("off", "low", "medium", "high")  # None / "" = provider default

PROVIDER_LABELS = {
    "mistral": "Mistral API",
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "openai_compatible": "OpenAI-compatible server (LM Studio, vLLM, …)",
    "anthropic": "Anthropic",
    "ollama": "Ollama",
}

# Anthropic thinking budgets per level (max_tokens is raised above the budget).
_ANTHROPIC_THINKING_BUDGET = {"low": 2048, "medium": 8192, "high": 16384}

# OpenAI reasoning models (o-series, gpt-5): no temperature, max_completion_tokens.
_OPENAI_REASONING_RE = re.compile(r"^(o\d|gpt-5)", re.I)


def provider_kind(conn: dict[str, Any]) -> str:
    """Provider behind a connection: explicit ``provider`` field, else inferred."""
    explicit = (conn.get("provider") or "").strip()
    if explicit in PROVIDER_KINDS:
        return explicit
    ctype = conn.get("type", "")
    if ctype in ("anthropic", "ollama"):
        return ctype
    host = (urlparse(conn.get("base_url", "")).hostname or "").lower()
    if host == "api.mistral.ai" or host.endswith(".mistral.ai"):
        return "mistral"
    if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return "openrouter"
    if host == "api.openai.com":
        return "openai"
    return "openai_compatible"


def _mistral_reasoning_values(model: str) -> tuple[str, ...]:
    """reasoning_effort values a Mistral model accepts ("" = unknown → don't send)."""
    m = model.lower()
    if m.startswith("mistral-large"):
        return ("low", "medium", "high")
    if m.startswith(("mistral-small", "mistral-medium", "magistral")):
        return ("none", "high")
    return ()


def _has_thinking_switch(model: str) -> bool:
    m = (model or "").lower()
    return "qwen" in m or "qwq" in m


def reasoning_mapping(kind: str, model: str, level: str | None) -> tuple[dict[str, Any], str]:
    """(fields to add to the request, note for the admin) for a reasoning level.

    ``level`` None/"" → provider default, nothing sent. A note is returned when
    the level cannot be applied, so the admin never shows a silent no-op.
    """
    if not level:
        return {}, ""
    if kind == "mistral":
        allowed = _mistral_reasoning_values(model)
        want = "none" if level == "off" else level
        if want in allowed:
            return {"reasoning_effort": want}, ""
        if level == "off":
            return {}, "This model cannot switch reasoning off; it always reasons."
        if "high" in allowed and level in ("low", "medium"):
            return {"reasoning_effort": "high"}, f"This model only supports reasoning off/high; '{level}' is sent as high."
        return {}, "Reasoning level not supported for this model; not sent."
    if kind == "openrouter":
        if level == "off":
            return {"reasoning": {"enabled": False}}, ""
        return {"reasoning": {"effort": level}}, ""
    if kind == "openai":
        if not _OPENAI_REASONING_RE.match(model):
            return {}, "Not a reasoning model; not sent."
        if level == "off":
            return {}, "OpenAI reasoning models cannot switch reasoning off."
        return {"reasoning_effort": level}, ""
    if kind == "openai_compatible":
        # Only Qwen-family chat templates understand enable_thinking; sending it to
        # others (e.g. Gemma on oMLX/LM Studio) can break their template.
        if not _has_thinking_switch(model):
            return {}, "This model has no reasoning switch on this server; not sent."
        enable = level != "off"
        note = "" if level == "off" else "Levels are not mapped on this server: reasoning is simply on."
        return {"chat_template_kwargs": {"enable_thinking": enable}}, note
    if kind == "anthropic":
        if level == "off":
            return {}, ""  # off is Anthropic's default
        return {"thinking": {"type": "enabled", "budget_tokens": _ANTHROPIC_THINKING_BUDGET[level]}}, ""
    if kind == "ollama":
        note = "" if level == "off" else "Levels are not mapped on Ollama: reasoning is simply on."
        return {"think": level != "off"}, note
    return {}, ""


def describe(conn: dict[str, Any], model: str, slot: dict[str, Any],
             supported: list[str] | None = None) -> dict[str, Any]:
    """What happens to each control of a slot on this connection + model.

    Returned to the admin UI so every setting says whether it is sent, renamed
    or ignored. Statuses: "sent", "not sent (default)", "ignored", "adjusted".
    ``supported`` is OpenRouter's per-model ``supported_parameters``: OpenRouter
    accepts any field silently, so this is the only way to flag a no-op.
    """
    kind = provider_kind(conn)
    model = model or ""
    out: dict[str, Any] = {"provider": kind, "provider_label": PROVIDER_LABELS[kind], "controls": {}}
    c = out["controls"]

    temp = slot.get("temperature")
    if temp is None:
        c["temperature"] = {"status": "not sent (default)"}
    elif kind == "openai" and _OPENAI_REASONING_RE.match(model):
        c["temperature"] = {"status": "ignored", "note": "OpenAI reasoning models do not accept temperature."}
    elif kind == "anthropic" and slot.get("reasoning") in ("low", "medium", "high"):
        c["temperature"] = {"status": "ignored", "note": "Anthropic does not allow temperature while thinking."}
    else:
        c["temperature"] = {"status": "sent"}

    mt = slot.get("max_tokens")
    if mt is None:
        c["max_tokens"] = ({"status": "adjusted", "note": "Anthropic requires it: 4096 is sent."}
                           if kind == "anthropic" else {"status": "not sent (default)"})
    else:
        note = ""
        if kind in ("openrouter", "mistral") or (kind == "openai_compatible"):
            note = "Reasoning tokens count against this limit; with reasoning on, a small value can return an empty answer."
        c["max_tokens"] = {"status": "sent", **({"note": note} if note else {})}

    if kind == "ollama":
        c["num_ctx"] = {"status": "sent" if slot.get("num_ctx") is not None else "not sent (default)"}
    else:
        c["num_ctx"] = {"status": "ignored",
                        "note": "Not a request parameter for this provider; used only as the context window for compression."}

    fields, note = reasoning_mapping(kind, model, slot.get("reasoning"))
    if not slot.get("reasoning"):
        c["reasoning"] = {"status": "not sent (default)"}
    elif fields:
        c["reasoning"] = {"status": "sent", "fields": fields, **({"note": note} if note else {})}
    else:
        c["reasoning"] = {"status": "ignored", "note": note or "Not supported here."}
    c["reasoning"]["options"] = _reasoning_options(kind, model)

    if kind == "openrouter" and supported:
        for control, param in (("temperature", "temperature"), ("max_tokens", "max_tokens"), ("reasoning", "reasoning")):
            if param not in supported:
                if c[control]["status"] == "sent":
                    c[control] = {**c[control], "status": "ignored",
                                  "note": "This model on OpenRouter does not support it: the provider ignores it silently."}
                if control == "reasoning":
                    c["reasoning"]["options"] = []
    return out


def _reasoning_options(kind: str, model: str) -> list[str]:
    """Levels that actually do something for this provider/model (for the UI)."""
    if kind == "mistral":
        allowed = _mistral_reasoning_values(model)
        opts = ["off"] if "none" in allowed else []
        return opts + [lv for lv in ("low", "medium", "high") if lv in allowed]
    if kind == "openai":
        return ["low", "medium", "high"] if _OPENAI_REASONING_RE.match(model) else []
    if kind == "openai_compatible":
        return ["off", "high"] if _has_thinking_switch(model) else []
    if kind == "ollama":
        return ["off", "high"]
    return list(REASONING_LEVELS)


def openai_body_extras(
    conn: dict[str, Any],
    model: str,
    temperature: float | None,
    max_tokens: int | None,
    reasoning: str | None,
    cache_key: str | None,
) -> dict[str, Any]:
    """Request fields for the OpenAI-compatible adapter, per provider rules.

    Optional fields we add (reasoning, stream_options, prompt_cache_key,
    provider routing) are listed in ``OPTIONAL_FIELDS`` so the adapter can drop
    them and retry once if a provider rejects them.
    """
    kind = provider_kind(conn)
    body: dict[str, Any] = {}
    reasoning_model = kind == "openai" and _OPENAI_REASONING_RE.match(model or "")
    if temperature is not None and not reasoning_model:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_completion_tokens" if reasoning_model else "max_tokens"] = max_tokens
    body.update(reasoning_mapping(kind, model or "", reasoning)[0])
    # Usage in the final stream chunk: Mistral and OpenRouter send it anyway;
    # OpenAI, vLLM and LM Studio need stream_options.
    if kind in ("openai", "openai_compatible"):
        body["stream_options"] = {"include_usage": True}
    if cache_key and conn.get("prompt_cache_key"):
        body["prompt_cache_key"] = cache_key
    routing = conn.get("routing")
    if kind == "openrouter" and isinstance(routing, dict) and routing:
        body["provider"] = routing
    return body


OPTIONAL_FIELDS = ("reasoning", "reasoning_effort", "chat_template_kwargs", "stream_options",
                   "prompt_cache_key", "provider")


def rejected_optional_fields(error_text: str, body: dict[str, Any]) -> list[str]:
    """Optional fields to drop after a provider's 400/422: the ones its error names
    or, when it names none, every optional field we added (a translation must not
    fail on an optional field a server rejects without saying which)."""
    present = [f for f in OPTIONAL_FIELDS if f in body]
    named = [f for f in present if f in error_text]
    return named or present
