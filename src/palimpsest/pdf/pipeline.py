"""Translate a PDF in place: same pages, same artwork, English text.

Pipeline per document
  1. classify  -- digital text layer, existing OCR layer, or pure scan
  2. ocr       -- scans only (`pdf.ocr`)
  3. extract   -- paragraphs with styled runs, alignment, leading (`pdf.layout`)
  4. translate -- cached MT with entity protection and honest failure status
  5. clear     -- text removed without touching images or line art (`pdf.clearing`)
  6. draw      -- styled, aligned, correctly-fonted English (`pdf.render`)
  7. report    -- per-page QA facts

Failure behaviour is deliberate: a paragraph whose translation did not
succeed is NOT cleared and NOT redrawn. The original Spanish stays
visible and is listed in the report, rather than silently rendering
untranslated Spanish as though it were a finished translation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz

from palimpsest.config.model import Config
from palimpsest.core import paths as core_paths
from palimpsest.core.progress import ProgressCallback, ProgressEvent, emit
from palimpsest.pdf import clearing, inkstyle, layout
from palimpsest.pdf.classify import Kind, classify_pdf
from palimpsest.pdf.fontmap import FontResolver
from palimpsest.pdf.ocr import ensure_ocr
from palimpsest.pdf.render import RenderContext, draw_paragraph
from palimpsest.text import ordinals
from palimpsest.text.glossary import Glossary
from palimpsest.text.protect import EntityGuard, strip_accents
from palimpsest.translate.backend import Backend
from palimpsest.translate.registry import build_translator
from palimpsest.translate.translator import Translator

log = logging.getLogger(__name__)

# A leading list marker (letter/roman-numeral/digit enumerator or bullet
# glyph) or a spelled-out legal ordinal -- peeled off and reattached
# verbatim after translation so the translator never sees it and cannot
# corrupt it (a bare "CUARTO." sent to MT comes back "ROOM.", the
# furniture sense, not the ordinal).
_MARKER_RE = re.compile(r"^\s*((?:[a-zA-Z]\)|\(?[ivxIVX]{1,5}\)|\d{1,2}[.)]|[•●○◦▪§·]))\s+")


def split_prefix(text: str, source: str = "es") -> tuple[str, str]:
    """Peel off a leading list marker and/or legal ordinal. Returns
    (prefix, remainder); the prefix is already in its final English form.

    Legal ordinals are a Spanish-source feature (`text.ordinals` maps
    Spanish words to English ones), so for any other source language only
    the language-neutral list marker is peeled."""
    prefix = ""
    rest = text
    m = _MARKER_RE.match(rest)
    if m:
        prefix += m.group(1) + " "
        rest = rest[m.end():]
    en_ord, tail = ordinals.match(rest, strip_accents) if source == "es" else (None, rest)
    if en_ord:
        prefix += en_ord
        rest = tail
        while rest[:1] in (".", ",", ":"):
            prefix += rest[0]
            rest = rest[1:]
        prefix += " "
        rest = rest.lstrip()
    return prefix, rest


def translate_with_prefix(text: str, tr: Translator) -> tuple[str | None, str]:
    """Translate `text`, protecting any leading marker/ordinal."""
    prefix, rest = split_prefix(text, tr.source)
    if not prefix:
        return tr.translate(text)
    if not rest.strip():
        return prefix.strip(), "ok"
    en, status = tr.translate(rest)
    if status != "ok" or en is None:
        return None, status
    return prefix + en, "ok"


def style_segments(para: layout.Para) -> list[tuple[str, tuple]]:
    """Merge the paragraph's runs into maximal same-style segments."""
    segs: list[list] = []
    for r in para.runs:
        if segs and segs[-1][1] == r["style"]:
            segs[-1][0] += r["text"]
        else:
            segs.append([r["text"], r["style"]])
    return [(t, s) for t, s in segs if t.strip()]


def dominant_style(segs: list[tuple[str, tuple]]) -> tuple:
    return max(segs, key=lambda s: len(s[0]))[1]


def translate_paragraph(
    para: layout.Para, tr: Translator, guard: EntityGuard, label_max_chars: int
) -> tuple[list[tuple[str, tuple]] | None, str]:
    """Return (segments, status) where segments is [(english_text, style)].

    Inline emphasis is preserved for the pattern that dominates these
    documents -- a short bold lead-in label followed by regular body text
    (`CONSIDERANDO:`, `Asunto:`). The label and body are translated as
    separate units so each keeps its own styling; any other style mix is
    translated whole and drawn in its dominant style.
    """
    segs = style_segments(para)
    if not segs:
        return None, "empty"
    dom = dominant_style(segs)

    if len(segs) >= 2:
        head, head_style = segs[0]
        head_s = head.strip()
        rest = "".join(t for t, _ in segs[1:]).strip()
        # Terminal punctuation is required, not just an all-caps word: a
        # bare uppercase word with no punctuation is weak evidence and is
        # exactly what OCR size-jitter produces -- a heading spuriously
        # split into separate runs would otherwise translate its first
        # word in total isolation from the rest.
        looks_like_label = (
            len(head_s) <= label_max_chars
            and rest
            and head_style != dom
            and head_s.endswith((":", "."))
        )
        if looks_like_label:
            # Both fragments need the same protected-fragment guard the
            # top-level paragraph loop applies to para.text -- splitting
            # here creates two new, smaller strings the top-level check
            # never sees.
            en_rest: str | None
            en_head: str | None
            if guard.skip(rest):
                en_rest, st2 = rest, "ok"
            else:
                en_rest, st2 = tr.translate(rest)
            if guard.skip(head_s):
                en_head, st1 = head_s, "ok"
            else:
                en_head, st1 = translate_with_prefix(head_s, tr)
            if st1 == "ok" and st2 == "ok" and en_head is not None and en_rest is not None:
                return [(en_head + " ", head_style), (en_rest, dom)], "ok"

    en, st = translate_with_prefix(para.text, tr)
    if st != "ok" or en is None:
        return None, st
    return [(en, dom)], "ok"


def process_document(
    src: Path,
    out: Path,
    rel: str,
    tr: Translator,
    guard: EntityGuard,
    render_ctx: RenderContext,
    config: Config,
    kind: Kind | None = None,
    debug: bool = False,
    pages: set[int] | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    """`pages`, if given, is a 0-indexed set restricting translation to
    those pages only -- e.g. to reproduce a layout bug cheaply on a large
    scan without paying for a full-document OCR run. Pages outside the
    set are left exactly as in the source (not translated, not touched)
    but still present in the saved output.

    `progress`, if given, is called at the boundary of each of the six
    phases described in this module's docstring -- `None` (the default)
    reproduces today's behaviour exactly, with zero added overhead."""
    kind = kind or classify_pdf(str(src))
    emit(progress, ProgressEvent(phase="classify", status="done", detail=kind))

    work_src = src
    if kind == "scan":
        emit(progress, ProgressEvent(phase="ocr", status="active"))
        key = core_paths.cache_key(core_paths.norm_rel(rel))
        work_src = ensure_ocr(src, config.paths.work_dir, key, config.ocr)
        emit(progress, ProgressEvent(phase="ocr", status="done"))
    else:
        emit(progress, ProgressEvent(phase="ocr", status="done", detail="skipped -- not a scan"))

    doc = fitz.open(str(work_src))
    scanned = kind in ("scan", "ocr")
    report: dict = {
        "pages": len(doc), "paragraphs": 0, "translated": 0, "skipped": 0,
        "failed": [], "scaled": 0, "overflow": 0, "inpainted": 0, "kind": kind,
    }

    # Pass 1: collect every paragraph so unique strings can be
    # batch-translated. On a scanned page the text layer is one block per
    # physical line and knows nothing about weight, so paragraphs are
    # re-joined and bold is measured from the page's own ink.
    emit(progress, ProgressEvent(phase="extract", status="active"))
    min_size = (
        config.thresholds.min_text_size_scan if scanned else config.thresholds.min_text_size
    )
    ink_thresholds = inkstyle.InkThresholds(
        dark=config.thresholds.ink_dark_threshold,
        bold_stem_ratio=config.thresholds.bold_stem_ratio,
    )
    page_paras: list[list[layout.Para]] = []
    for pno in range(len(doc)):
        if pages is not None and pno not in pages:
            page_paras.append([])
            continue
        page = doc[pno]
        paras = layout.extract_paragraphs(page, min_size=min_size)
        if scanned:
            # Bullets must be found BEFORE merging: they are the signal
            # that a line opens a new list item rather than continuing
            # the previous one.
            inkstyle.detect_bullets(page, paras)
            paras = layout.merge_flowing_paragraphs(paras, page)
            inkstyle.annotate_bold(page, paras, ink_thresholds)
        page_paras.append(paras)

    total_paras = sum(len(paras) for paras in page_paras)
    emit(
        progress,
        ProgressEvent(
            phase="extract", status="done",
            detail=f"{total_paras} paragraphs found across {len(doc)} pages",
        ),
    )

    all_text = [
        p.text for paras in page_paras for p in paras if not guard.skip(p.text)
    ]
    emit(progress, ProgressEvent(phase="translate", status="active"))
    tr.warm(all_text, on_progress=progress)
    emit(progress, ProgressEvent(phase="translate", status="done"))

    # Pass 2: translate, clear, redraw.
    emit(progress, ProgressEvent(phase="render", status="active"))
    for pno in range(len(doc)):
        if pages is not None and pno not in pages:
            continue
        page = doc[pno]
        paras = page_paras[pno]
        jobs = []
        for para in paras:
            report["paragraphs"] += 1
            if guard.skip(para.text):
                report["skipped"] += 1
                continue
            segs, status = translate_paragraph(
                para, tr, guard, config.thresholds.label_max_chars
            )
            if status != "ok" or not segs:
                report["failed"].append(
                    {"page": pno + 1, "text": para.text[:120], "status": status}
                )
                continue
            jobs.append((para, segs))

        if not jobs:
            continue

        rects = [j[0].rect for j in jobs]
        if scanned:
            report["inpainted"] += clearing.inpaint_scanned(page, rects)
            clearing.strip_text_layer(page, rects)
        else:
            clearing.clear_text_digital(page, rects)

        # Re-fetch paragraphs' growth room after clearing (geometry is
        # unchanged, so the pre-clear paragraph list is still the right
        # neighbour set).
        obstacles = layout.page_obstacle_rects(page)
        for para, segs in jobs:
            avail = layout.available_rect(page, para, paras, obstacles=obstacles)
            info = draw_paragraph(render_ctx, page, para, segs, avail, debug_boxes=debug)
            report["translated"] += 1
            if info["scaled"]:
                report["scaled"] += 1
            if info["overflow"]:
                report["overflow"] += 1
                report.setdefault("overflow_detail", []).append(
                    {"page": pno + 1, "text": para.text[:90]}
                )

    emit(
        progress,
        ProgressEvent(
            phase="render", status="done",
            detail=f"{report['translated']} paragraphs drawn",
        ),
    )

    emit(progress, ProgressEvent(phase="save", status="active"))
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out), garbage=4, deflate=True)
    doc.close()
    tr.cache.save()
    if render_ctx.font_resolver.substitutions:
        report["font_substitutions"] = dict(render_ctx.font_resolver.substitutions)
    emit(progress, ProgressEvent(phase="save", status="done"))
    return report


def translate_pdf_document(
    src: Path,
    out: Path,
    rel: str,
    backend: Backend,
    entities: tuple[str, ...],
    glossary: Glossary,
    post_rules: tuple[tuple[str, str], ...],
    config: Config,
    kind: Kind | None = None,
    debug: bool = False,
    pages: set[int] | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    """Entry point: build the per-document Translator/font/render context
    and run the full pipeline. `entities`/`glossary`/`post_rules` are
    passed in rather than read from `config` directly -- config only
    stores where the private entity/document files live, not their
    contents (see `config.loader.load_entities`/`load_documents`)."""
    guard = EntityGuard(entities)
    tr = build_translator(rel, config, backend, entities, glossary, post_rules)
    font_resolver = FontResolver(
        extra_dirs=config.fonts.extra_dirs,
        use_bundled_fallback=config.fonts.use_bundled_fallback,
    )
    render_ctx = RenderContext(
        font_resolver=font_resolver,
        default_scan_family=config.fonts.per_document.get(rel, config.fonts.scan_default),
        min_scale=config.thresholds.min_scale,
        justify_max_stretch=config.thresholds.justify_max_stretch,
    )
    return process_document(
        src, out, rel, tr, guard, render_ctx, config,
        kind=kind, debug=debug, pages=pages, progress=progress,
    )
