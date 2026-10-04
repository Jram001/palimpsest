<h1 align="center">
  <a href="https://ianperaltahirujo.github.io/palimpsest/"><img src="https://raw.githubusercontent.com/ianperaltahirujo/palimpsest/main/docs/assets/logo.png" width="48" height="48" valign="middle" alt="palimpsest logo — two overlapping page outlines in register"></a>
  palimpsest
</h1>

<p align="center">
  <i>A palimpsest is a manuscript page scraped clean so the surface can be reused — the<br>
  original artwork and impressions intact, new text written over it. That's what this<br>
  tool does to a document: same pages, same artwork, same typography — only the words change.</i>
</p>

<p align="center">
  <a href="https://pypi.org/project/palimpsest-translate/"><img alt="PyPI" src="https://img.shields.io/pypi/v/palimpsest-translate.svg?color=blue"></a>
  <a href="https://github.com/ianperaltahirujo/palimpsest/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ianperaltahirujo/palimpsest/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/ianperaltahirujo/palimpsest/blob/main/LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg">
  <a href="https://github.com/ianperaltahirujo/palimpsest/blob/main/CONTRIBUTING.md"><img alt="No network calls in tests" src="https://img.shields.io/badge/tests-no%20network%20calls-informational.svg"></a>
</p>

<p align="center">
  Layout-preserving Spanish→English document translation for PDF and Office formats
  (<code>.docx</code> / <code>.pptx</code> / <code>.xlsx</code>) — as a CLI, a library, or a local web UI.
</p>

<p align="center">
  <a href="https://ianperaltahirujo.github.io/palimpsest/">
    <img src="https://raw.githubusercontent.com/ianperaltahirujo/palimpsest/main/docs/assets/demo.gif" width="820" alt="Demo: dropping a document, estimating cost, translating it, and comparing the original against the translated page side by side">
  </a>
</p>

OCR when there's no text layer, styled-run extraction, in-place redraw with real
embedded fonts, entity/glossary-aware machine translation (Gemini, Claude, or Google
Translate), and an honest translation cache that never lets a failed translation
masquerade as a successful one.

- **Replicas, not rebuilds** — same pages, same fonts, same artwork; only the prose changes.
- **Protected entities** — company names, personal names, and amounts survive verbatim, guaranteed.
- **Three backends, one protocol** — Gemini (free tier, default), Claude (paid, highest quality), or Google Translate (free, no key).
- **An honest report, always** — a paragraph that fails to translate is never silently dropped or rendered as if it succeeded.
- **A local web UI**, in addition to the CLI and the library — drop a file, watch it translate, compare pages side by side.

**Contents:** [Install](#install) · [Quickstart](#quickstart) · [Web UI](#web-ui) ·
[Why this exists](#why-this-exists-not-just-what-it-does) · [Architecture](#architecture) ·
[Contributing](#contributing) · [License](#license)

## Install

```bash
pip install palimpsest-translate            # Google Translate backend only, free, no key
pip install palimpsest-translate[gemini]    # + Gemini backend (default, free API key)
pip install palimpsest-translate[anthropic] # + Claude backend (paid, highest quality)
pip install palimpsest-translate[ocr]       # + OCR for scanned PDFs (needs Tesseract on PATH)
pip install palimpsest-translate[all]       # everything
```

Requires Python 3.11+. To work on palimpsest itself, or to install from source:

```bash
git clone https://github.com/ianperaltahirujo/palimpsest.git
cd palimpsest
pip install -e ".[all,dev]"
```

## Quickstart

```bash
palimpsest translate deed.pdf                    # -> deed.en.pdf, Gemini backend (needs GEMINI_API_KEY, free)
palimpsest translate deed.pdf --backend anthropic # needs ANTHROPIC_API_KEY in the environment
palimpsest translate deed.pdf --backend google    # Google Translate, no key at all
palimpsest translate deed.pdf --dry-run           # classify, count paragraphs, estimate cost -- no translation
```

That's it for a single file — no config required. `palimpsest translate`
works out of the box because a missing `palimpsest.toml` just means "no
protected entities, no glossary, default thresholds," not an error.

### A whole corpus

```bash
palimpsest config init            # scaffolds private/ (gitignored) for your entity list and document map
palimpsest batch                  # translates everything named in private/documents.toml, resumes on re-run
palimpsest batch --force          # rebuild everything
palimpsest batch --only pdf --jobs 4
```

See `examples/palimpsest.toml`, `examples/entities.example.toml`, and
`examples/documents.example.toml` for the file shapes, and
[`docs/configuration.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/configuration.md) for the full reference.

### Web UI

```bash
pip install "palimpsest-translate[server]"
python tools/build_frontend.py   # builds web/prototype and stages it into the package
palimpsest serve                 # http://127.0.0.1:8765, opens your browser
```

Local-first, single-user, no accounts: everything runs on your own machine
and binds to loopback by default (`--host` requires an explicit `--i-know`
to bind wider). API keys are read from the environment exactly like the
CLI, and never stored in a job record or echoed back in a response — you
can also type one into the page itself instead of a shell (`PUT /api/keys`, applied immediately, saved to `.env`). See
[`web/prototype/README.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/web/prototype/README.md) for the frontend
itself, including `--dev` mode for working on the UI against a live API
without rebuilding on every change, its "Standalone" mode for publishing
a build somewhere other than this server (e.g. GitHub Pages, via
`--allow-origin`), and its "Office files" section for what previewing a
`.docx`/`.pptx`/`.xlsx` in the browser needs
([LibreOffice](https://www.libreoffice.org/download/download/), optional
and only for that preview — translation itself never needs it).

A standalone frontend build's default expectation is that each visitor runs their own
`palimpsest serve` locally. For a zero-command deployment instead — a visitor opens the page,
types an API key, and translates — see [`docs/deployment.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/deployment.md) for running the
backend itself somewhere persistent (a `Dockerfile` and a Render walkthrough), plus what
per-visitor isolation that requires and doesn't guarantee.

## Why this exists, not just what it does

Generic "translate this PDF" tools tend to do one of two things badly:
rebuild the document from extracted text (losing layout, fonts, and
artwork), or leave the original untouched and bolt on a translation
elsewhere. Neither produces a document you'd actually hand to someone in
place of the original.

palimpsest was extracted from a real pipeline built for legal and
financial documents — trust deeds, audited financial statements,
environmental permits, budget workbooks — where the layout, the
signatures, the letterhead, and the exact numbers all have to survive
untouched, and only the prose changes language. That constraint shaped
almost every design decision here:

- **Replicas, not rebuilds.** A digital PDF's text is extracted with its
  styled runs, alignment, and measured leading, cleared without touching
  images or vector art, and redrawn in a real embedded font at the
  original position. A scanned PDF gets a real OCR text layer first.
- **An honest cache.** Every cached translation carries an explicit status
  (`ok` / `failed` / `identical` / `refused`) — a failed machine
  translation can never be silently served as a successful one, and a
  document that still has untranslated paragraphs says so in its report
  rather than shipping quietly incomplete.
- **Protected entities as a first-class concept**, not a glossary
  workaround — company names, personal names, and amounts are guaranteed
  to survive verbatim, including the specific failure modes documented in
  [`docs/design/protected-entities.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/design/protected-entities.md):
  OCR fragmenting a heading into a bare `GRUPO` and letting it
  machine-translate as if it were an ordinary noun.

The four documents in `docs/design/` are a genuine engineering postmortem
— what broke, why, and what specifically fixed it — carried over (and
de-identified) from the pipeline this project was extracted from:

- [`v1-postmortem.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/design/v1-postmortem.md) — the first version
  of this pipeline rebuilt documents from scratch and lost logos, fonts,
  and whole spreadsheet parts; nine concrete bugs and what fixed each one.
- [`protected-entities.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/design/protected-entities.md) — a company
  name translated as if it were a common noun, found after a full corpus
  run had already shipped; two independent root causes and three separate
  places a protective guard got bypassed before the fix became
  architectural instead of another patch.
- [`bold-calibration.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/design/bold-calibration.md) — how bold text
  is recovered from scanned pixels when the OCR text layer carries no
  weight information, and why the threshold is a corpus-fitted number, not
  a universal constant.
- [`limitations.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/design/limitations.md) — an honest account of
  what this pipeline does not handle, from a real corpus run rather than
  written speculatively.
- [`backends.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/docs/design/backends.md) — why the Gemini/Claude LLM
  backends handle entity protection completely differently from Google
  Translate's phrase-level API, why Gemini is the default despite Claude
  being the stronger model, and the pricing/quality tradeoffs between all
  three.

## Architecture

```
src/palimpsest/
  cli.py                 subcommands: translate, batch, compare, cache, audit, config
  corpus.py               whole-corpus batch orchestration
  config/                 layered TOML config (packaged defaults -> project file -> private/)
  core/                   cross-platform paths, errors, logging, the IR serialization boundary
  text/                   entity protection, glossary, ordinals, post-translation fixups
  pdf/                    classify, OCR, layout extraction, font resolution, clearing, render, pipeline
  office/                 OOXML surgery (translate .xlsx/.docx/.pptx by editing the zip in place)
  translate/              backend protocol, Gemini + Claude + Google backends, cache, cost estimation
  qa/                     side-by-side comparison renders, bilingual PDF output, cache audit
```

Three backends behind one `Backend` protocol: Gemini (the `google-genai`
SDK, free-tier, LLM — the default) and Claude (the `anthropic` SDK, paid,
LLM) both protect entities by prompt instruction plus a post-hoc
verification pass, since an LLM benefits from reading the whole sentence
in a way placeholder substitution would defeat; Google Translate
(`deep-translator`, free, phrase-level, no key at all) has no concept of
"entity" at all, so its entities are protected by placeholder substitution
instead. See `docs/design/backends.md` for why they're architected
differently rather than sharing one protection scheme.

## What this borrows from, and doesn't share code with

Several architectural ideas — most notably TOML-based project
configuration and bilingual side-by-side PDF output — were inspired by
[BabelDOC](https://github.com/funstory-ai/BabelDOC), an AGPL-3.0
scientific-PDF translation tool, after comparing it against this
pipeline's own approach. BabelDOC's headline feature, ML-based layout
analysis (DocLayout-YOLO), was deliberately **not** adopted: this
pipeline's own geometry-based column/paragraph detection
(`pdf.layout.column_bands`) already solves the layout problem it exists
for, for this document type, without a model download or GPU dependency.
See `NOTICE` — no BabelDOC source is included in or derived into this
project.

## Contributing

See [`CONTRIBUTING.md`](https://github.com/ianperaltahirujo/palimpsest/blob/main/CONTRIBUTING.md). The short version: no test may
make a real network call, and `tools/scrub_check.py` runs in CI to keep
this repository free of the confidential document data it was extracted
from.

## License

Apache 2.0 — see [`LICENSE`](https://github.com/ianperaltahirujo/palimpsest/blob/main/LICENSE). See [`NOTICE`](https://github.com/ianperaltahirujo/palimpsest/blob/main/NOTICE) for the
BabelDOC design-inspiration credit above.
