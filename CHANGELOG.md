# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project
does not yet promise strict [Semantic Versioning](https://semver.org/)
compatibility guarantees (pre-1.0).

## [Unreleased]

### Added

- **Per-file target language.** Each file in the web UI's Queue step has an
  English / Español switch choosing which language it is translated into,
  so one job can mix Spanish -> English and English -> Spanish files.
  `POST /api/estimate` and `POST /api/jobs` take a `targets` map
  (file id -> `"en"` | `"es"`, default `"en"`), and each job file reports
  its `target`. Downloads are now named `<source name>.<lang>.<ext>`.
  See `docs/design/limitations.md` for what English -> Spanish does not
  get (glossaries, date fixups, ordinals).
- A setup guide page, a home-page help link, and a Back button on the
  Sample screen.


## [0.2.2] — 2026-08-09

### Fixed

- v0.2.1's fix made the README's logo render with a visible background
  box on GitHub -- GitHub applies its own background-box styling to any
  image loaded from an absolute URL (confirmed for both
  raw.githubusercontent.com and a third-party CDN), never to a same-repo
  relative path. README.md is back to fully relative links/images (a
  clean render on GitHub, which is what most people actually browse);
  a new `tools/render_pypi_readme.py` generates a separate
  `README.pypi.md` with everything absolute, which is what
  `pyproject.toml`'s `readme` field now points at. CI fails if the two
  drift out of sync.
- The Dockerfile's build image still referenced `README.md` after that
  field changed, so `pip install` failed hatchling's readme-file-exists
  check immediately -- fixed to copy `README.pypi.md` instead.

## [0.2.1] — 2026-08-09

### Fixed

- The README's images and every cross-file link (`LICENSE`, `NOTICE`,
  `CONTRIBUTING.md`, the `docs/design/` postmortems, etc.) rendered
  broken on PyPI's project page — PyPI's readme renderer has no GitHub
  base URL to resolve a relative path against, unlike GitHub's own
  renderer. Every non-anchor link/image now points at an absolute
  `github.com`/`raw.githubusercontent.com` URL instead.

## [0.2.0] — 2026-08-09

The 0.1.0 release was the library and CLI alone. This release adds a
server, a web UI, a second translation backend, and a hosted-deployment
story on top of that — the biggest jump so far.

### Added

- **FastAPI server** (`palimpsest serve`) wrapping the existing pipeline
  — no translation logic of its own, every route composes library
  functions that already existed.
- **React + Mantine web UI**: drop a file, get a real cost estimate,
  watch translation progress live over SSE, review results, compare the
  original and translated page side by side with a wipe slider, and
  edit a translated page directly (backed by a new IR→PDF reflow path).
  Ships in both a design-review "mock" mode and a real-API mode against
  the FastAPI server.
- **Gemini backend**, now the default (free tier, no billing setup) —
  Claude remains available for higher-quality legal/financial prose.
- **Multi-tenant hosting**: per-browser visitor identity, per-visitor
  API keys (never falling back to the operator's own environment for a
  non-local visitor), per-visitor upload/job ownership (a mismatch reads
  as 404, never 403), and small abuse guardrails (upload size cap,
  one job per visitor).
- **Docker image + Render deployment walkthrough**
  (`docs/deployment.md`) for running the backend somewhere persistent,
  so a visitor can open a published frontend build, type a key, and
  translate without running anything locally.
- **GitHub Pages deployment** of the standalone frontend build, wired to
  point at any backend via a runtime "Server address" setting.
- Office file (`.docx`/`.pptx`/`.xlsx`) page previews via LibreOffice
  headless conversion, since `fitz.open()` silently doesn't render them.
- Protected-entity **profiles**: save/load/delete a named roster instead
  of retyping the same entities for every document (browser-local, since
  the server's entity list is one shared file, not per-visitor).
- **"Remove all" + Undo** for protected entities.
- A real **Cancel** on the "you already have a job in progress" limit —
  frees the visitor's job slot and lets a new translation start
  immediately, rather than only being able to wait.

### Changed

- The scan-warning and dropzone-accept colors were dimmed to a muted,
  low-saturation tint — both used to read as far more alarming/bold than
  intended.
- The Running screen now shows a real animated spinner and periodically
  reconciles against the server's own job status, instead of freezing
  silently if the SSE stream goes quiet or the job vanishes (see Fixed).

### Fixed

- A real production OOM: `ocrmypdf` was defaulting to one worker per
  *reported host core*, not per the container's actual memory — a
  512MB Render instance could be killed translating a 3-page scan.
  `[ocr] jobs` now caps this explicitly on hosted deployments.
- A job whose SSE stream went silent (dead connection, or the process
  having restarted and lost all in-memory job state) previously left the
  UI frozen forever on "OCR: waiting" with no explanation.
- `OriginCheckMiddleware` rejecting the served SPA's own same-origin
  requests, and the Private Network Access CORS preflight needed for a
  publicly-hosted frontend to reach a loopback backend.
- Several entity-protection and layout regressions now documented in
  `docs/design/` — a bare `GRUPO` fragment machine-translating as an
  ordinary noun, table-cell paragraphs overflowing into the next row,
  OCR noise from decorative graphics rendering at the wrong size, short
  protected entities matching as substrings inside unrelated words.
- Mock design-review fixtures leaking into real mode when a fetch failed.
- `GeminiBackend.estimate()` crashing against the real Developer API.

## [0.1.0] — 2026-08-06

Initial extraction from a private client pipeline: the CLI and library
(PDF and Office translation pipelines, protected-entity guard, glossary
matching, honest translation cache with per-entry status), with no
server or web UI yet.

[0.2.2]: https://github.com/ianperaltahirujo/palimpsest/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/ianperaltahirujo/palimpsest/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ianperaltahirujo/palimpsest/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ianperaltahirujo/palimpsest/releases/tag/v0.1.0
