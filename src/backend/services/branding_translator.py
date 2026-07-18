"""Branding translator — uses LLM to translate custom branding text to all supported languages.

Sprint 11: Background translation of disclaimer and instructions text for per-frontend branding.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from src.services.llm_provider import llm

logger = logging.getLogger("backend.branding_translator")

_CAMPAIGNS_DIR = Path("/app/data/campaigns")

# All supported languages (must match frontend i18n.ts)
LANGUAGES = [
    ("en", "English"), ("zh", "Chinese (Simplified)"), ("hi", "Hindi"),
    ("es", "Spanish"), ("ar", "Arabic"), ("fr", "French"),
    ("bn", "Bengali"), ("pt", "Portuguese"), ("ru", "Russian"),
    ("id", "Indonesian"), ("de", "German"), ("mr", "Marathi"),
    ("ja", "Japanese"), ("te", "Telugu"), ("tr", "Turkish"),
    ("ta", "Tamil"), ("vi", "Vietnamese"), ("ko", "Korean"),
    ("ur", "Urdu"), ("th", "Thai"), ("it", "Italian"),
    ("pl", "Polish"), ("nl", "Dutch"), ("el", "Greek"),
    ("uk", "Ukrainian"), ("ro", "Romanian"), ("hr", "Croatian"),
    ("xh", "Xhosa"), ("sw", "Swahili"), ("hu", "Hungarian"),
    ("sv", "Swedish"),
]

# In-memory translation status per frontend
_translation_status: dict[str, dict[str, Any]] = {}


def get_translation_status(frontend_id: str) -> dict[str, Any]:
    return _translation_status.get(frontend_id, {"status": "idle", "progress": 0, "total": 0})


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _glossary_block(terms: list[dict[str, Any]], target_lang: str) -> str:
    """Build a target-language-filtered glossary block for the prompt.

    Only terms that have a translation in ``target_lang`` are included.
    Returns '' if none apply.
    """
    lines: list[str] = []
    for t in terms:
        tr = (t.get("translations") or {}).get(target_lang)
        if tr:
            term = t.get("term", "")
            definition = t.get("definition", "")
            lines.append(f"- {term} → {tr}" + (f" ({definition})" if definition else ""))
    if not lines:
        return ""
    return (
        "\n\n## Glossary (use these canonical translations for domain terms when they appear)\n"
        + "\n".join(lines)
    )


async def _translate_text(
    text: str, target_name: str, settings: dict[str, Any], system_prompt: str
) -> str:
    """Translate a single text to the target language using the translation slot.

    Sprint 20: runs on the dedicated `translation` fallback chain (→ inference)
    with the editable, domain-aware prompt (plus an optional glossary block).
    """
    from src.services.llm_provider import build_fallback_chain

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Target language: {target_name}.\n\nTranslate the following text into {target_name}:\n\n{text}"},
    ]
    try:
        chain = build_fallback_chain(settings, "translation")
        result = await llm.chat_with_fallback(messages, chain)
        return _strip_think_blocks(result)
    except Exception as e:
        logger.warning(f"Translation to {target_name} failed: {e}")
        return ""


async def translate_branding(frontend_id: str, branding: dict[str, str], force: bool = False):
    """Translate branding texts to all supported languages. Saves to disk.

    Fill-missing (Sprint 20): existing non-empty translations are kept; only
    missing fields are (re)translated. ``force=True`` regenerates everything
    from the current English source. `en` is always the verbatim source.

    Args:
        frontend_id: The frontend to translate for
        branding: Dict with disclaimer_text and instructions_text (source language)
        force: Re-translate all languages even if a translation already exists
    """
    disclaimer = branding.get("disclaimer_text", "")
    instructions = branding.get("instructions_text", "")

    if not disclaimer and not instructions:
        return

    from src.api.v1.admin.llm import get_llm_settings, load_translation_prompt
    settings = get_llm_settings(frontend_id)
    base_prompt = load_translation_prompt()

    glossary_terms: list[dict[str, Any]] = []
    if settings.get("translation_glossary_enabled"):
        try:
            from src.api.v1.admin.knowledge import load_glossary
            glossary_terms = load_glossary().get("terms", [])
        except Exception as e:
            logger.warning(f"Glossary load failed, translating without it: {e}")

    # Start from existing translations so we can fill only what's missing
    existing = load_translations(frontend_id) or {}
    translations: dict[str, dict[str, str]] = {code: dict(existing.get(code, {})) for code, _ in LANGUAGES}

    total = len(LANGUAGES)
    _translation_status[frontend_id] = {"status": "translating", "progress": 0, "total": total}

    for i, (code, name) in enumerate(LANGUAGES):
        entry = translations.setdefault(code, {})
        system_prompt = base_prompt + (_glossary_block(glossary_terms, code) if glossary_terms else "")

        if disclaimer:
            if code == "en":
                entry["disclaimer_text"] = disclaimer
            elif force or not entry.get("disclaimer_text"):
                entry["disclaimer_text"] = await _translate_text(disclaimer, name, settings, system_prompt)

        if instructions:
            if code == "en":
                entry["instructions_text"] = instructions
            elif force or not entry.get("instructions_text"):
                entry["instructions_text"] = await _translate_text(instructions, name, settings, system_prompt)

        translations[code] = entry
        _translation_status[frontend_id] = {"status": "translating", "progress": i + 1, "total": total}
        logger.info(f"Translated branding for {frontend_id}: {name} ({i + 1}/{total})")

    # Save to disk (atomic)
    path = _CAMPAIGNS_DIR / frontend_id / "branding_translations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(translations, ensure_ascii=False, indent=2))
    tmp.rename(path)

    _translation_status[frontend_id] = {"status": "done", "progress": total, "total": total}
    logger.info(f"Branding translations complete for {frontend_id}: {total} languages")


def load_translations(frontend_id: str) -> dict[str, dict[str, str]] | None:
    """Load saved translations from disk. Returns None if no translations exist."""
    path = _CAMPAIGNS_DIR / frontend_id / "branding_translations.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def delete_translations(frontend_id: str):
    """Delete translation files for a frontend (reset to default)."""
    path = _CAMPAIGNS_DIR / frontend_id / "branding_translations.json"
    if path.exists():
        path.unlink()
        logger.info(f"Branding translations deleted for {frontend_id}")
