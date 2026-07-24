"""Okapi/Tikal extract + recompose engine (ADR-021).

An **alternative** to the python-docx/pptx/pandoc path in ``document_translator``,
selectable per-instance via the admin Settings ``format_engine`` toggle:

    python       — the in-process python libs (default)
    okapi        — Okapi/Tikal, allowWordStyleOptimisation ON  (Okapi's default)
    okapi_noopt  — Okapi/Tikal, allowWordStyleOptimisation OFF (keeps original styles)

Okapi is the localisation-industry filter framework: it turns an Office file into
XLIFF (translatable *text units* + protected *inline codes* + skeleton) and merges
a translated XLIFF back into the original. We reuse only its **extract** and
**merge**; the app's own two-pass translation loop runs unchanged in between.

The bridge is the interesting part: Okapi protects inline formatting with XLIFF
``<bpt>/<ept>`` paired codes plus standalone ``<ph>/<it>/<x>`` codes. We present
these to the LLM as **XLIFF-generic tags** — ``<g id="k">…</g>`` (paired) and
``<x id="k"/>`` (standalone), ADR-022 — the same shape ``translate()`` uses for
the python engine. On merge we deep-copy the **original** ``<bpt>/<ept>`` back into
``<target>``, so Tikal always receives its own native codes; the ``<g>/<x>`` tags
are only the LLM-facing wire format. ``_build_target`` **guarantees balanced codes**
(or degrades that unit to plain text), so one mangled tag can never leave a dangling
code that aborts ``tikal -m`` for the whole document.

Tikal is invoked in-container via ``subprocess`` (a Java CLI bundled in the image,
never a host CLI — same pattern as pypandoc→pandoc). ``OKAPI_LIB`` points at the
jar dir, ``OKAPI_CONFIG_DIR`` at the versioned ``.fprm`` filter configs.
"""

import copy
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lxml import etree

logger = logging.getLogger("backend.okapi")

_NS = "urn:oasis:names:tc:xliff:document:1.2"
_Q = "{%s}" % _NS
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_TIKAL_MAIN = "net.sf.okapi.applications.tikal.Main"
_OKAPI_LIB = os.environ.get("OKAPI_LIB", "/opt/okapi/lib")
_OKAPI_CONFIG_DIR = os.environ.get("OKAPI_CONFIG_DIR", "/app/config/okapi")

_OPENXML_SUFFIXES = {".docx", ".pptx", ".xlsx"}
_RTF_SUFFIXES = {".rtf"}
SUPPORTED_SUFFIXES = _OPENXML_SUFFIXES | _RTF_SUFFIXES


# ---------------------------------------------------------------------------
# Tikal invocation
# ---------------------------------------------------------------------------


def _filter_args(ext: str, style_optimisation: bool) -> list[str]:
    """The ``-fc`` filter config for a given format. ``allowWordStyleOptimisation``
    lives only in the OpenXML filter, so the OFF variant (versioned ``.fprm``) is
    used only there; rtf ignores the flag."""
    ext = ext.lower()
    if ext in _OPENXML_SUFFIXES:
        if not style_optimisation:
            return ["-fc", "okf_openxml@noopt", "-pd", _OKAPI_CONFIG_DIR]
        return ["-fc", "okf_openxml"]
    if ext in _RTF_SUFFIXES:
        return ["-fc", "okf_rtf"]
    return []


def _tikal(args: list[str], cwd: str) -> None:
    """Run Tikal in-container. Raises with captured output on any failure."""
    cmd = ["java", "-cp", f"{_OKAPI_LIB}/*", _TIKAL_MAIN, *args]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as e:
        raise RuntimeError(
            "java not found — Okapi engine requires the JRE bundled in the backend "
            f"image (OKAPI_LIB={_OKAPI_LIB}); is format_engine=okapi on a non-Okapi image?"
        ) from e
    if r.returncode != 0:
        raise RuntimeError(f"tikal {' '.join(args)} exited {r.returncode}: {r.stdout}\n{r.stderr}")


# ---------------------------------------------------------------------------
# Bridge: XLIFF inline codes  <->  LLM-facing tags <g id="k">…</g> / <x id="k"/>
# ---------------------------------------------------------------------------

# XLIFF-generic tags (ADR-022). ASCII + non-mirror, tolerant of the loose spacing /
# dropped quotes the model sometimes emits. One alternation, three shapes:
#   open  <g id="k">   → group "open"
#   close </g>         → neither group set
#   x     <x id="k"/>  → group "x"
_TAG_RE = re.compile(
    r'<\s*g\s+id\s*=\s*"?(?P<open>\d+)"?\s*>'
    r'|<\s*/\s*g\s*>'
    r'|<\s*x\s+id\s*=\s*"?(?P<x>\d+)"?\s*/?\s*>'
)
_TAG_ANY = re.compile(r'<\s*/?\s*[gx](?:\s+id\s*=\s*"?\d+"?)?\s*/?\s*>')


def _source_to_core(source_el: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert a ``<source>`` (mixed text + inline codes) to the LLM-facing tag string.

    Each paired ``bpt/ept`` becomes ``<g id="k">…</g>``; each standalone code (ph/it/x)
    becomes ``<x id="k"/>`` at its position. ``codes[k]`` holds the element(s) to
    re-emit on the open / close tag at recompose."""
    codes: list[dict[str, Any]] = []
    id2k: dict[str, int] = {}
    parts: list[str] = []
    if source_el.text:
        parts.append(source_el.text)
    for child in source_el:
        local = child.tag.split("}")[-1]
        if local == "bpt":
            k = len(codes); id2k[child.get("id")] = k
            codes.append({"open": child, "close": None})
            parts.append('<g id="%d">' % k)
        elif local == "ept":
            k = id2k.get(child.get("id"))
            if k is None:  # orphan close — emit as a self-contained standalone
                k = len(codes); codes.append({"open": child, "close": None})
                parts.append('<x id="%d"/>' % k)
            else:
                codes[k]["close"] = child
                parts.append("</g>")
        elif local in ("ph", "it", "x", "bx", "ex"):
            k = len(codes); codes.append({"open": child, "close": None})
            parts.append('<x id="%d"/>' % k)
        else:
            raise ValueError("unexpected inline code <%s>" % local)
        if child.tail:
            parts.append(child.tail)
    return "".join(parts), codes


def _build_target(target_el: Any, translated: str, codes: list[dict[str, Any]]) -> None:
    """Rebuild ``<target>`` from the translated tag string, restoring inline codes.

    Guarantees **balanced** XLIFF codes: the tags are validated with a stack (spans
    are sequential, non-nested), and on any imbalance — a dangling ``<g>``, an
    unmatched ``</g>``, a duplicate or out-of-range id — the whole unit degrades to
    plain text (tags stripped, no codes). A target with *missing* codes only makes
    ``tikal -m`` warn; a *dangling* code makes it abort the whole merge, so we never
    emit one."""
    # Tokenise into text / open(k) / close / x(k).
    tokens: list[tuple[str, Any]] = []
    pos = 0
    for m in _TAG_RE.finditer(translated):
        if m.start() > pos:
            tokens.append(("t", translated[pos:m.start()]))
        if m.group("open") is not None:
            tokens.append(("open", int(m.group("open"))))
        elif m.group("x") is not None:
            tokens.append(("x", int(m.group("x"))))
        else:
            tokens.append(("close", None))
        pos = m.end()
    if pos < len(translated):
        tokens.append(("t", translated[pos:]))

    # Validate balance; resolve each close to the id it closes.
    stack: list[int] = []
    used: set[int] = set()
    resolved: list[tuple[str, Any]] = []
    ok = True
    for kind, val in tokens:
        if kind == "open":
            if not (0 <= val < len(codes)) or codes[val]["close"] is None or val in used:
                ok = False; break
            used.add(val); stack.append(val); resolved.append(("open", val))
        elif kind == "close":
            if not stack:
                ok = False; break
            resolved.append(("close", stack.pop()))
        elif kind == "x":
            if not (0 <= val < len(codes)) or val in used:
                ok = False; break
            used.add(val); resolved.append(("x", val))
        else:
            resolved.append(("t", val))
    if stack:
        ok = False

    for c in list(target_el):
        target_el.remove(c)
    target_el.text = None
    if not ok:
        target_el.text = _TAG_ANY.sub("", translated)
        return

    last: list[Any] = [None]

    def add_text(s: str) -> None:
        if not s:
            return
        if last[0] is None:
            target_el.text = (target_el.text or "") + s
        else:
            last[0].tail = (last[0].tail or "") + s

    for kind, val in resolved:
        if kind == "t":
            add_text(val)
            continue
        el = codes[val]["close" if kind == "close" else "open"]
        if el is not None:
            c = copy.deepcopy(el); c.tail = None
            target_el.append(c); last[0] = c


# ---------------------------------------------------------------------------
# extract / recompose
# ---------------------------------------------------------------------------


def extract(path: str, options: dict[str, Any] | None, style_optimisation: bool) -> dict[str, Any]:
    """Tikal ``-x`` an Office file → IR whose segments carry the app's markers.

    The IR keeps the parsed XLIFF tree + per-segment inline-code templates + a copy
    of the original (Okapi's merge re-reads the original by name), all under a
    per-job temp workdir, so ``recompose`` can inject targets and merge per language."""
    p = Path(path)
    ext = p.suffix.lower()
    workdir = tempfile.mkdtemp(prefix="okapi_")
    src_copy = Path(workdir) / p.name
    shutil.copy(p, src_copy)

    _tikal(["-x", p.name, *_filter_args(ext, style_optimisation)], cwd=workdir)
    xlf_path = Path(workdir) / (p.name + ".xlf")
    if not xlf_path.exists():
        raise RuntimeError(f"Okapi extract produced no XLIFF for {p.name}")

    tree = etree.parse(str(xlf_path))
    segments: list[dict[str, Any]] = []
    tus: list[Any] = []
    codes_per: list[list[dict[str, Any]]] = []
    for tu in tree.getroot().iter(_Q + "trans-unit"):
        core, codes = _source_to_core(tu.find(_Q + "source"))
        segments.append({"text": core, "translate": bool(core.strip())})
        tus.append(tu)
        codes_per.append(codes)

    logger.info("Okapi extracted %d units from %s (style_opt=%s)",
                len(segments), p.name, style_optimisation)
    return {
        "format": ext.lstrip("."),
        "source_path": str(p),
        "segments": segments,
        "_okapi": {
            "tree": tree, "tus": tus, "codes": codes_per, "workdir": workdir,
            "src_copy": str(src_copy), "ext": ext, "style_opt": style_optimisation,
        },
    }


def recompose(ir: dict[str, Any], target_lang: str, out_path: str | None) -> str:
    """Inject the translated targets into the XLIFF and Tikal ``-m`` back to Office."""
    ok = ir["_okapi"]
    tree, tus, codes_per = ok["tree"], ok["tus"], ok["codes"]

    for f in tree.getroot().iter(_Q + "file"):
        f.set("target-language", target_lang)
    for seg, tu, codes in zip(ir["segments"], tus, codes_per):
        tgt = tu.find(_Q + "target")
        if tgt is None:
            tgt = etree.SubElement(tu, _Q + "target")
        tgt.set(_XML_LANG, target_lang)
        if seg["translate"]:
            out = seg.get("out", {}).get(target_lang)
            if out is not None:
                _build_target(tgt, out, codes)

    # Merge needs the original present and name-matched to the XLIFF (<name>.<ext>.xlf).
    src_copy = Path(ok["src_copy"])
    langdir = Path(ok["workdir"]) / target_lang
    langdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src_copy, langdir / src_copy.name)
    xlf = langdir / (src_copy.name + ".xlf")
    tree.write(str(xlf), xml_declaration=True, encoding="UTF-8")

    _tikal(["-m", xlf.name, *_filter_args(ok["ext"], ok["style_opt"])], cwd=str(langdir))
    merged = langdir / (src_copy.stem + ".out" + ok["ext"])
    if not merged.exists():
        raise RuntimeError(f"Okapi merge produced no output for {target_lang}")

    if out_path is None:
        out_path = str(src_copy.with_name(f"{src_copy.stem}.{target_lang}{ok['ext']}"))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(merged), out_path)
    return out_path
