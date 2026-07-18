"""Document translation loop (Sprint 3 + 7, SPEC §3.4 / §4.2).

Three functions behind one per-format interface:

    extract(path) -> IR            list of segments (+ format), granularity-preserving
    translate(IR, ...) -> IR       per-language, per-segment two-pass fill
    recompose(IR, lang, out) -> path   rebuild the document in the original format

``translate`` is format-agnostic — it only touches each segment's ``text`` /
``translate`` / ``out``. Only ``extract`` and ``recompose`` are per-format:

  - **Tier 1** (`.txt` / `.md`): loss-less line segmentation (blank runs + fenced
    code are skeleton), so recomposition is byte-stable.
  - **Tier 2** (`.docx` / `.rtf`, Sprint 7): in-container libs (lesson #11) — no
    host CLI. `.docx` via **python-docx** at paragraph granularity (paragraph
    style kept; minor inline-format shifts accepted, §4.2); `.rtf` via **pandoc**
    (rtf↔markdown), reusing the Tier-1 markdown segmenter.

Each segment is translated two-pass (draft with neighbour context → glossary
review) through the connection registry — never a hardcoded endpoint (lesson #9).
"""

import logging
import re
from pathlib import Path
from typing import Any

from src.api.v1.admin.llm import get_llm_settings, load_document_translation_prompt
from src.core.languages import language_name
from src.services.glossary_slice import slice_glossary, format_glossary_block
from src.services.llm_provider import llm, build_fallback_chain

logger = logging.getLogger("backend.document_translator")

_MD_SUFFIXES = {".md", ".markdown"}
_DOCX_SUFFIXES = {".docx"}
_RTF_SUFFIXES = {".rtf"}


def _strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from model output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ---------------------------------------------------------------------------
# Segmentation (Tier 1: txt / md) — loss-less
# ---------------------------------------------------------------------------


def _segment(text: str, fmt: str) -> list[dict[str, Any]]:
    """Split into ordered segments, each ``{text, translate}``.

    Three kinds, so structure survives recomposition:
      - blank runs (one or more blank lines) → skeleton, not translated;
      - fenced code blocks (```) in markdown → verbatim, not translated;
      - runs of consecutive non-blank lines → one translatable text segment.

    Loss-less: ``"".join(s["text"] for s in _segment(t, fmt)) == t``.
    """
    lines = text.splitlines(keepends=True)
    segments: list[dict[str, Any]] = []
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        # fenced code block (md only) — consume until the closing fence
        if fmt == "md" and stripped.startswith("```"):
            block = [lines[i]]
            j = i + 1
            while j < n:
                block.append(lines[j])
                closed = lines[j].strip().startswith("```")
                j += 1
                if closed:
                    break
            segments.append({"text": "".join(block), "translate": False})
            i = j
            continue
        # blank run
        if stripped == "":
            j = i
            while j < n and lines[j].strip() == "":
                j += 1
            segments.append({"text": "".join(lines[i:j]), "translate": False})
            i = j
            continue
        # text run — consecutive non-blank, non-fence lines
        j = i
        while j < n:
            s = lines[j].strip()
            if s == "" or (fmt == "md" and s.startswith("```")):
                break
            j += 1
        segments.append({"text": "".join(lines[i:j]), "translate": True})
        i = j
    return segments


# ---------------------------------------------------------------------------
# Tier 2 handlers (docx / rtf) — in-container libs only (lesson #11)
# ---------------------------------------------------------------------------


def _iter_doc_paragraphs(doc: Any) -> list[Any]:
    """Every paragraph in a python-docx document, in a stable order (body first,
    then table-cell paragraphs). extract + recompose walk this identically so
    segment order lines up with paragraph order."""
    paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                paras.extend(cell.paragraphs)
    return paras


def _extract_docx(p: Path) -> dict[str, Any]:
    from docx import Document
    doc = Document(str(p))
    segments = [
        {"text": para.text, "translate": bool(para.text.strip())}
        for para in _iter_doc_paragraphs(doc)
    ]
    return {"format": "docx", "source_path": str(p), "segments": segments}


def _set_paragraph_text(para: Any, text: str) -> None:
    """Replace a paragraph's text, keeping its style (heading/list) and the first
    run's character formatting. Minor inline-format shifts are accepted (§4.2)."""
    if para.runs:
        para.runs[0].text = text
        for r in para.runs[1:]:
            r.text = ""
    else:
        para.add_run(text)


def _recompose_docx(ir: dict[str, Any], target_lang: str, out_path: str | None) -> str:
    from docx import Document
    doc = Document(ir["source_path"])  # fresh copy per language (no cross-lang mutation)
    for seg, para in zip(ir["segments"], _iter_doc_paragraphs(doc)):
        if seg["translate"]:
            _set_paragraph_text(para, seg.get("out", {}).get(target_lang, seg["text"]))
    out_path = out_path or _default_out(ir, target_lang)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def _extract_rtf(p: Path) -> dict[str, Any]:
    import pypandoc
    md = pypandoc.convert_file(str(p), "markdown", format="rtf")
    return {"format": "rtf", "source_path": str(p), "segments": _segment(md, "md")}


def _recompose_rtf(ir: dict[str, Any], target_lang: str, out_path: str | None) -> str:
    import pypandoc
    md = "".join(
        s.get("out", {}).get(target_lang, s["text"]) if s["translate"] else s["text"]
        for s in ir["segments"]
    )
    out_path = out_path or _default_out(ir, target_lang)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    pypandoc.convert_text(md, "rtf", format="markdown", outputfile=out_path)
    return out_path


def _default_out(ir: dict[str, Any], target_lang: str) -> str:
    p = Path(ir["source_path"])
    return str(p.with_name(f"{p.stem}.{target_lang}{p.suffix}"))


# ---------------------------------------------------------------------------
# extract dispatch
# ---------------------------------------------------------------------------


def extract(path: str) -> dict[str, Any]:
    """Build the IR for a document, dispatching on format (Tier 1 + Tier 2)."""
    p = Path(path)
    suf = p.suffix.lower()
    if suf in _DOCX_SUFFIXES:
        return _extract_docx(p)
    if suf in _RTF_SUFFIXES:
        return _extract_rtf(p)
    fmt = "md" if suf in _MD_SUFFIXES else "txt"
    text = p.read_text(encoding="utf-8")
    return {"format": fmt, "source_path": str(p), "segments": _segment(text, fmt)}


def count_translatable_chars(path: str) -> int:
    """Total characters in translatable segments — drives the duration estimate."""
    return sum(len(s["text"]) for s in extract(path)["segments"] if s["translate"])


# ---------------------------------------------------------------------------
# Per-segment two-pass (draft → glossary review)
# ---------------------------------------------------------------------------


def _resolve_chain(connection_id: str | None, model: str | None) -> list[dict[str, Any]]:
    """Provider chain: explicit override, else the `translation` slot (→ inference)."""
    if connection_id:
        return [{
            "connection_id": connection_id, "model": model or "",
            "temperature": None, "max_tokens": None, "num_ctx": None,
            "_slot_name": "document-override",
        }]
    return build_fallback_chain(get_llm_settings(), "translation")


async def _translate_segment(
    core: str,
    *,
    source_name: str,
    target_name: str,
    source_code: str,
    target_code: str,
    ctx_before: str,
    ctx_after: str,
    user_glossary: str,
    system_prompt: str,
    chain: list[dict[str, Any]],
) -> str:
    """Translate one segment's text: pass 1 (draft, neighbour context) → pass 2
    (sliced-glossary review). Returns the corrected translation (no trailing
    newline handling — the caller re-attaches the source's trailing newlines)."""
    context_parts = []
    if ctx_before.strip():
        context_parts.append(f"[preceding segment]\n{ctx_before.strip()}")
    if ctx_after.strip():
        context_parts.append(f"[following segment]\n{ctx_after.strip()}")
    context_block = (
        "--- Context (for consistency only — do NOT translate this) ---\n"
        + "\n\n".join(context_parts) + "\n\n"
    ) if context_parts else ""

    pass1_user = (
        f"Pass 1 — Draft. Source language: {source_name}. Target language: {target_name}.\n\n"
        f"{context_block}--- Segment to translate ---\n{core}"
    )
    draft = _strip_think(await llm.chat_with_fallback(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": pass1_user}],
        chain,
    ))

    sliced = slice_glossary(core, source_code, target_code, user_glossary)
    glossary_block = format_glossary_block(sliced)
    review_terms = glossary_block or (
        "No glossary terms apply to this segment; return the draft unchanged."
    )
    pass2_user = (
        f"Pass 2 — Glossary review. Target language: {target_name}.\n\n"
        f"Your draft:\n{draft}\n\n{review_terms}\n\nReturn the corrected segment only."
    )
    return _strip_think(await llm.chat_with_fallback(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": pass2_user}],
        chain,
    ))


def _split_trailing_newlines(text: str) -> tuple[str, str]:
    """Return (content, trailing_newlines) so recompose keeps block spacing."""
    core = text.rstrip("\n")
    return core, text[len(core):]


# ---------------------------------------------------------------------------
# Translate + recompose
# ---------------------------------------------------------------------------


async def translate(
    ir: dict[str, Any],
    source_lang: str,
    target_langs: list[str],
    user_glossary: str = "",
    connection_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Fill ``ir`` with a translation of every translatable segment for each
    target language. Non-translatable segments are left as source. Mutates and
    returns ``ir`` (each translatable segment gains ``out[lang]``)."""
    system_prompt = load_document_translation_prompt()
    chain = _resolve_chain(connection_id, model)
    if not chain or not chain[0].get("connection_id"):
        raise ValueError("no translation connection resolved (register one / set the translation slot)")

    source_name = language_name(source_lang)
    segs = ir["segments"]
    trans_idx = [i for i, s in enumerate(segs) if s["translate"]]

    for lang in target_langs:
        target_name = language_name(lang)
        for pos, i in enumerate(trans_idx):
            core, trailing = _split_trailing_newlines(segs[i]["text"])
            ctx_before = segs[trans_idx[pos - 1]]["text"] if pos > 0 else ""
            ctx_after = segs[trans_idx[pos + 1]]["text"] if pos < len(trans_idx) - 1 else ""
            translated = await _translate_segment(
                core,
                source_name=source_name, target_name=target_name,
                source_code=source_lang, target_code=lang,
                ctx_before=ctx_before, ctx_after=ctx_after,
                user_glossary=user_glossary,
                system_prompt=system_prompt, chain=chain,
            )
            # re-attach the source segment's trailing newlines → stable block spacing
            segs[i].setdefault("out", {})[lang] = translated.rstrip("\n") + trailing
        logger.info(f"Translated {len(trans_idx)} segments → {lang}")
    return ir


def recompose(ir: dict[str, Any], target_lang: str, out_path: str | None = None) -> str:
    """Rebuild the document for one target language and write it, dispatching on
    format. Non-translatable / untranslated segments fall back to source."""
    fmt = ir["format"]
    if fmt == "docx":
        return _recompose_docx(ir, target_lang, out_path)
    if fmt == "rtf":
        return _recompose_rtf(ir, target_lang, out_path)
    # Tier 1 (txt / md): loss-less text join.
    result = "".join(
        s.get("out", {}).get(target_lang, s["text"]) if s["translate"] else s["text"]
        for s in ir["segments"]
    )
    out_path = out_path or _default_out(ir, target_lang)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(result, encoding="utf-8")
    return out_path


async def translate_document(
    path: str,
    source_lang: str,
    target_langs: list[str],
    user_glossary: str = "",
    out_dir: str | None = None,
    connection_id: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """End-to-end: extract → translate → recompose. Returns ``{lang: out_path}``."""
    ir = extract(path)
    await translate(ir, source_lang, target_langs, user_glossary, connection_id, model)
    src = Path(path)
    outputs: dict[str, str] = {}
    for lang in target_langs:
        out_path = (
            str(Path(out_dir) / f"{src.stem}.{lang}{src.suffix}") if out_dir else None
        )
        outputs[lang] = recompose(ir, lang, out_path)
    return outputs
