"""Glossary slicing (Sprint 2, SPEC §3.4 / §4.2, lesson #7).

Pass 2 of the translation loop enforces domain terminology. Rather than inject
the whole glossary on every segment (wasted tokens, diluted attention), we
inject only the terms whose **source-language** value actually appears in the
segment, resolved to the target language. The base glossary is
`knowledge/glossary.json` (the UNI base glossary, 17 languages); a per-job user
glossary (free text) augments/overrides it and wins on conflict.

Algorithm ported from `docs/knowledge/uni-glossary/glossary_slice.py` (the UNI
translator skill's slicer): accent- and case-insensitive matching, `/`-variant
splitting, and a minimum variant length to avoid false positives. The CLI's
Phase-1 fallback (keep the whole language slice when <5 terms match) is
deliberately NOT ported — for per-segment injection we always want Phase 2 only
(inject only what is present), never the full glossary.
"""

import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger("backend.glossary")

# Separators accepted in a user-glossary line: "source -> target", "=>", "=", ":".
_USER_SEP = re.compile(r"\s*(?:->|=>|=|:)\s*")

# Glossary values shorter than this (normalized) are skipped when matching, to
# avoid false positives from short strings ("CI", "es"). From the reference.
_MIN_VARIANT_LENGTH = 4


def normalize(text: str) -> str:
    """Lowercase and strip diacritics for accent-insensitive matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def extract_variants(value: str) -> list[str]:
    """Split a glossary value on '/' into variants, dropping short ones.

    E.g. "Afiliada / Organización miembro" → ["Afiliada", "Organización miembro"].
    """
    return [v.strip() for v in value.split("/") if len(v.strip()) >= _MIN_VARIANT_LENGTH]


def parse_user_glossary(text: str) -> list[dict[str, str]]:
    """Parse a free-text user glossary into ``[{source, target}]``.

    One term per line, ``source -> target`` (also ``=>``, ``=``, ``:``). Blank
    lines and lines without a separator are skipped. The user glossary is not
    language-tagged — the target is whatever the user wrote.
    """
    terms: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _USER_SEP.split(line, maxsplit=1)
        if len(parts) != 2:
            continue
        source, target = parts[0].strip(), parts[1].strip()
        if source and target:
            terms.append({"source": source, "target": target})
    return terms


def slice_glossary(
    text: str,
    source_lang: str,
    target_lang: str,
    user_glossary: str = "",
    base_terms: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Return glossary terms whose source value appears in ``text``.

    Base terms come from ``knowledge/glossary.json`` in the app shape
    ``{"terms": [{"term", "translations": {lang: value}, "note"?}]}``. A base
    term is included when it has a ``target_lang`` translation AND its
    source-language value (``translations[source_lang]``, falling back to the
    English ``term`` key) appears in the segment — accent/case-insensitive,
    ``/``-variants considered. User-glossary terms are included when their source
    appears in the segment and **override** a base term with the same source.

    Returns ``[{source, target}]`` (base entries also carry ``note`` if set).
    """
    if base_terms is None:
        from src.api.v1.admin.knowledge import load_glossary
        base_terms = load_glossary().get("terms", [])

    src_lang = (source_lang or "").lower()
    tgt_lang = (target_lang or "").lower()
    norm_doc = normalize(text)
    sliced: dict[str, dict[str, str]] = {}  # keyed by normalized source

    for entry in base_terms:
        translations = entry.get("translations") or {}
        target = translations.get(tgt_lang)
        if not target:
            continue
        src_value = translations.get(src_lang) or entry.get("term", "")
        candidates = extract_variants(src_value)
        if not any(normalize(v) in norm_doc for v in candidates):
            continue
        item: dict[str, str] = {"source": src_value, "target": target}
        if entry.get("note"):
            item["note"] = entry["note"]
        sliced[normalize(src_value)] = item

    for entry in parse_user_glossary(user_glossary):
        source = entry["source"]
        if normalize(source) in norm_doc:
            sliced[normalize(source)] = {"source": source, "target": entry["target"]}

    return list(sliced.values())


def format_glossary_block(sliced: list[dict[str, str]]) -> str:
    """Render sliced terms as a prompt block for pass 2. '' if none apply."""
    if not sliced:
        return ""
    lines = [f"- {t['source']} → {t['target']}" for t in sliced]
    return (
        "The following domain terms appear in this segment and MUST use exactly "
        "these target-language equivalents:\n" + "\n".join(lines)
    )
