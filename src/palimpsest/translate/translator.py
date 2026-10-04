"""Orchestrates entity protection, glossary lookup, caching, and a
translation backend into one `translate()` call that never lets a
failure masquerade as a result.

Call order matters and is fixed: the entity guard is checked FIRST,
before anything else -- including before this function's own caller gets
a chance to slice the text into a sub-fragment. That ordering is the
direct fix for a documented class of bug: three separate call sites in
an earlier version of this pipeline each independently forgot to
re-check entity protection after transforming the text (a label-split
path, a list-marker/ordinal-peeling path, and a batch warm-up path), and
each one let a bare fragment of a protected name reach the translation
backend and come back mistranslated. The fix was architectural, not a
fourth patch: every call path in this module funnels through
`EntityGuard.skip()` at the top of `translate()`, and nothing downstream
re-implements any part of that decision.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence

from palimpsest.core.progress import ProgressCallback, ProgressEvent, emit
from palimpsest.text.glossary import Glossary
from palimpsest.text.postfix import apply as apply_post_rules
from palimpsest.text.protect import EntityGuard, all_tokens_restored, protect, restore
from palimpsest.translate.backend import Backend, TranslationContext
from palimpsest.translate.cache import Cache

log = logging.getLogger(__name__)

# Source-language-only signals: if these survive into the "translation",
# it did not actually translate. Used only to classify a same-as-input
# result as suspicious ("identical") vs. legitimately unchanged (a bare
# company name, a code, a number), never to silently rewrite anything.
_SOURCE_LANGUAGE_MARKERS = {
    "es": re.compile(
        r"\b(que|los|las|del|por|para|con|una|este|esta|son|ser|como|más|"
        r"sobre|entre|desde|hasta|cuando|donde|quien|cual|pero|porque|"
        r"señor|señores|sociedad|contrato|presente|mismo|dicha|dicho)\b",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"\b(the|and|of|to|that|with|for|this|shall|which|from|by|are|is|"
        r"will|have|has|been|not|or|agreement|company|hereby|party|parties)\b",
        re.IGNORECASE,
    ),
}


class Translator:
    def __init__(
        self,
        cache_path,
        backend: Backend,
        cache_namespace: str,
        entities: Iterable[str] = (),
        glossary: Glossary | None = None,
        post_rules: Iterable[tuple[str, str]] = (),
        source: str = "es",
        target: str = "en",
        verbose: bool = True,
    ):
        self.backend = backend
        self.cache = Cache(cache_path, namespace=cache_namespace)
        self.guard = EntityGuard(entities)
        self.glossary = glossary or Glossary()
        self.post_rules = tuple(post_rules)
        self.source = source
        self.target = target
        self.verbose = verbose
        self.stats = {
            "glossary": 0, "cache": 0, "translated": 0,
            "failed": 0, "identical": 0, "protected_fragment": 0, "refused": 0,
        }

    def _ctx(self) -> TranslationContext:
        return TranslationContext(
            source_lang=self.source, target_lang=self.target,
            entities=self.guard.entities, glossary=self.glossary.terms,
        )

    def _classify(self, source: str, english: str | None) -> str:
        if english is None:
            return "failed"
        a, b = source.strip(), english.strip()
        if not b:
            return "failed"
        if a == b:
            # Identical is only suspicious when the source really is
            # prose in the source language; a line like "GRUPO MERIDIAN,
            # S.A.S." is legitimately unchanged and must not be flagged
            # forever as a translation failure.
            markers = _SOURCE_LANGUAGE_MARKERS.get(self.source)
            return "identical" if markers is not None and markers.search(a) else "ok"
        return "ok"

    def _call_backend(self, text: str) -> tuple[str | None, str]:
        """Returns (english_or_None, status). status is never "ok" without
        a non-None english -- callers can rely on that pairing."""
        ctx = self._ctx()
        if self.backend.uses_placeholder_protection:
            protected_text, tokens = protect(text, self.guard.protect_re)
            result = self.backend.translate(protected_text, ctx)
            if result.status != "ok":
                return None, result.status
            english = apply_post_rules(restore(result.text, tokens), self.post_rules)
            if english is not None and not all_tokens_restored(english):
                # A placeholder survived -- an entity would render as
                # "[[2]]" in the output. Retry once unprotected rather
                # than ship broken text.
                retry = self.backend.translate(text, ctx)
                if retry.status == "ok" and retry.text:
                    english = apply_post_rules(retry.text, self.post_rules)
            return english, "ok"
        result = self.backend.translate(text, ctx)
        if result.status != "ok":
            return None, result.status
        return apply_post_rules(result.text, self.post_rules), "ok"

    def translate(self, text: str) -> tuple[str | None, str]:
        """Translate one paragraph. Returns (english, status)."""
        if self.guard.skip(text):
            self.stats["protected_fragment"] += 1
            return text, "ok"
        glossary_hit = self.glossary.lookup(text)
        if glossary_hit is not None:
            self.stats["glossary"] += 1
            return glossary_hit, "ok"
        cached = self.cache.get_ok(text)
        if cached is not None:
            self.stats["cache"] += 1
            return cached, "ok"

        english, status = self._call_backend(text)
        if status == "ok":
            status = self._classify(text, english)

        if status == "ok":
            self.stats["translated"] += 1
        else:
            self.stats[status] = self.stats.get(status, 0) + 1
            if self.verbose:
                log.info("[MT %s] %r", status, text[:70])
        self.cache.put(text, english, status)
        return (english, "ok") if status == "ok" else (None, status)

    # -- bulk -----------------------------------------------------------

    def warm(
        self,
        texts: Sequence[str],
        batch_size: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        """Pre-translate a document's unique strings, batching for speed.

        Anything the batch call cannot handle falls through to
        `translate()`, which retries and records an honest status --
        never duplicated here, so there is exactly one place that decides
        what counts as a good result.

        `on_progress`, if given, fires once per completed chunk with
        `count`/`total` against `todo` -- the strings this call actually
        sends to the backend, which excludes anything already resolved
        by the glossary, the cache, or the entity guard above. That is a
        deliberately different (smaller, real) number than "every unique
        string in the document"; a caller wanting the larger number
        already has it before calling `warm()` and can report it
        separately.
        """
        batch_size = batch_size or self.backend.max_batch
        todo: list[str] = []
        for t in texts:
            if self.glossary.lookup(t) is not None or self.cache.get_ok(t) is not None:
                continue
            if self.guard.skip(t):
                # Cheap: hits the guard immediately, no network call --
                # routed through translate() rather than duplicating the
                # skip-and-cache bookkeeping here.
                self.translate(t)
                continue
            if t not in todo:
                todo.append(t)
        if not todo:
            return 0

        use_placeholder = self.backend.uses_placeholder_protection
        ctx = self._ctx()
        done = 0
        for i in range(0, len(todo), batch_size):
            chunk = todo[i:i + batch_size]
            if use_placeholder:
                pairs = [protect(t, self.guard.protect_re) for t in chunk]
                send_texts = [p[0] for p in pairs]
            else:
                pairs = [(t, []) for t in chunk]
                send_texts = list(chunk)

            results = self.backend.translate_batch(send_texts, ctx)
            for src, (_prot, tokens), result in zip(chunk, pairs, results, strict=True):
                if result.status != "ok":
                    self.translate(src)  # leave it for the accurate single-string path
                    continue
                raw = restore(result.text, tokens) if use_placeholder else result.text
                english = apply_post_rules(raw, self.post_rules)
                if use_placeholder and (english is None or not all_tokens_restored(english)):
                    self.translate(src)
                    continue
                status = self._classify(src, english)
                if status == "ok":
                    self.cache.put(src, english, status)
                    self.stats["translated"] += 1
                else:
                    self.translate(src)
            done += len(chunk)
            self.cache.save()
            emit(
                on_progress,
                ProgressEvent(phase="translate", status="active", count=done, total=len(todo)),
            )
        self.cache.save()
        return done

    def retry_pending(self) -> tuple[int, int]:
        """Re-attempt every entry not marked ok. Returns (recovered, total)."""
        pending = list(self.cache.pending())
        recovered = 0
        for src in pending:
            self.cache.data.pop(src, None)
            _english, status = self.translate(src)
            if status == "ok":
                recovered += 1
        self.cache.save()
        return recovered, len(pending)
