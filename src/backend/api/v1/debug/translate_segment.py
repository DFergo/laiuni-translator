"""TEMPORARY debug endpoint — single-segment two-pass translation proof (Sprint 2).

Proves the translation loop end to end on ONE segment: pass 1 drafts (with
neighbor context), pass 2 enforces the sliced glossary — all through the
connection registry + llm_provider, provider-agnostic (SPEC §3.4, §4.2, §6).

RETIRE IN SPRINT 3 once `services/document_translator.py` exists and is wired
to the job queue. This route is direct/inbound and unauthenticated; it is only
reachable on the LAN-only backend (pull-inverse boundary, SPEC §2/§8), never
exposed through the sidecar. Do not ship it to production.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.llm import get_llm_settings, load_document_translation_prompt
from src.services.glossary_slice import slice_glossary, format_glossary_block
from src.services.llm_provider import llm, build_fallback_chain

logger = logging.getLogger("backend.debug.translate")

router = APIRouter(prefix="/debug", tags=["debug"])


def _strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from model output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class TranslateSegmentRequest(BaseModel):
    segment: str
    source_lang: str = "English"          # display name for the prompt
    source_lang_code: str = "en"          # ISO code for glossary slicing
    target_lang: str = "Spanish"          # display name for the prompt
    target_lang_code: str = "es"          # ISO code for glossary slicing
    context_before: str = ""
    context_after: str = ""
    user_glossary: str = ""
    # Provider-agnostic proof: point at any registered connection without code
    # changes. When omitted, the `translation` slot (→ inference) chain is used.
    connection_id: str | None = None
    model: str | None = None


def _resolve_chain(req: TranslateSegmentRequest) -> list[dict[str, Any]]:
    if req.connection_id:
        return [{
            "connection_id": req.connection_id,
            "model": req.model or "",
            "temperature": None,
            "max_tokens": None,
            "num_ctx": None,
            "_slot_name": "debug-override",
        }]
    return build_fallback_chain(get_llm_settings(), "translation")


@router.post("/translate-segment")
async def translate_segment(req: TranslateSegmentRequest) -> dict[str, Any]:
    """Run one segment through pass 1 (draft) + pass 2 (glossary review)."""
    if not req.segment.strip():
        raise HTTPException(status_code=400, detail="segment is empty")

    system_prompt = load_document_translation_prompt()
    chain = _resolve_chain(req)
    if not chain or not chain[0].get("connection_id"):
        raise HTTPException(status_code=400, detail="no translation connection resolved")

    # --- Pass 1: draft (neighbors as context only) ---
    context_parts = []
    if req.context_before:
        context_parts.append(f"[preceding segment]\n{req.context_before}")
    if req.context_after:
        context_parts.append(f"[following segment]\n{req.context_after}")
    context_block = (
        "--- Context (for consistency only — do NOT translate this) ---\n"
        + "\n\n".join(context_parts)
        + "\n\n"
    ) if context_parts else ""

    pass1_user = (
        f"Pass 1 — Draft. Source language: {req.source_lang}. "
        f"Target language: {req.target_lang}.\n\n"
        f"{context_block}"
        f"--- Segment to translate ---\n{req.segment}"
    )
    try:
        draft = _strip_think(await llm.chat_with_fallback(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": pass1_user}],
            chain,
        ))
    except Exception as e:
        logger.warning(f"Pass 1 failed: {e}")
        raise HTTPException(status_code=502, detail=f"pass 1 failed: {e}")

    # --- Pass 2: glossary review (sliced to this segment) ---
    sliced = slice_glossary(
        req.segment, req.source_lang_code, req.target_lang_code, req.user_glossary
    )
    glossary_block = format_glossary_block(sliced)
    review_terms = glossary_block or (
        "No glossary terms apply to this segment; return the draft unchanged."
    )
    pass2_user = (
        f"Pass 2 — Glossary review. Target language: {req.target_lang}.\n\n"
        f"Your draft:\n{draft}\n\n"
        f"{review_terms}\n\n"
        f"Return the corrected segment only."
    )
    try:
        final = _strip_think(await llm.chat_with_fallback(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": pass2_user}],
            chain,
        ))
    except Exception as e:
        logger.warning(f"Pass 2 failed: {e}")
        raise HTTPException(status_code=502, detail=f"pass 2 failed: {e}")

    return {
        "draft": draft,
        "final": final,
        "glossary_applied": sliced,
        "connection_id": chain[0]["connection_id"],
        "model": chain[0].get("model") or None,
    }
