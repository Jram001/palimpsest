"""Per-document translation direction (Spanish -> English or English -> Spanish).

The backends, cache namespace, and prompts are already language-agnostic
(they read `source_lang`/`target_lang` off the `TranslationContext`). What
is NOT agnostic is a small amount of Spanish-source tooling that was built
for the project's original es -> en use case:

  - the bundled glossaries are Spanish -> English term lists;
  - the packaged post-rules fix English date shapes and a Santo-Domingo
    mistranslation;
  - `text.ordinals` peels Spanish legal ordinals;
  - OCR's language pack defaults to Spanish.

This module is the one place that decides, per document, which of those
apply, so a caller (the server's job runner and estimate route) can hand
the existing pipelines a config + glossary + post-rule set that is correct
for that file's direction without the pipelines themselves knowing there
is more than one.

Only English and Spanish are supported, in either direction. The source
is always "the other one" of the pair -- picking a target IS picking a
direction.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from palimpsest.config.model import Config, LanguageConfig
from palimpsest.text.glossary import Glossary

SUPPORTED_TARGETS = ("en", "es")
DEFAULT_TARGET = "en"

# Tesseract language-pack codes for a document whose SOURCE is the key.
_OCR_CODES = {"en": "eng", "es": "spa"}


def is_supported_target(target: str) -> bool:
    return target in SUPPORTED_TARGETS


def source_for(target: str) -> str:
    if target not in SUPPORTED_TARGETS:
        raise ValueError(
            f"unsupported target language {target!r}; expected one of {SUPPORTED_TARGETS}"
        )
    return "es" if target == "en" else "en"


def config_for_target(config: Config, target: str) -> Config:
    """A copy of `config` whose language pair (and OCR language, when the
    source language changes) matches translating INTO `target`.

    The configured OCR language is kept whenever the source language is
    unchanged -- a user's own `[ocr].language` (e.g. "spa+eng") is theirs
    to choose; only a flipped direction needs a different pack."""
    source = source_for(target)
    ocr = config.ocr
    if source != config.language.source:
        ocr = dataclasses.replace(ocr, language=_OCR_CODES[source])
    return dataclasses.replace(
        config, language=LanguageConfig(source=source, target=target), ocr=ocr
    )


def resources_for(
    target: str, glossary: Glossary, post_rules: Sequence[tuple[str, str]]
) -> tuple[Glossary, tuple[tuple[str, str], ...]]:
    """The glossary and post-rules that are valid for this direction.

    Both are es -> en artifacts, so for English -> Spanish they are
    dropped rather than applied backwards: inverting a glossary is lossy
    (several Spanish terms share one English rendering) and the date
    rules rewrite English month names, which a Spanish output never
    contains. Protected entities are language-neutral and unaffected."""
    if target == "en":
        return glossary, tuple(post_rules)
    return Glossary(), ()
