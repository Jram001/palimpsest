"""Per-document translation direction (es->en or en->es).

`translate.direction` decides which Spanish-source-only tooling applies to
a file; these tests pin that decision plus the places it is consumed: the
job runner / estimate route (`server/`), the ordinal peeler, and the
"identical output" classifier. No network, no real backend.
"""

from __future__ import annotations

import time

import fitz
import pytest
from fastapi.testclient import TestClient

from palimpsest.config.model import Config, FontsConfig, PathsConfig, ThresholdsConfig
from palimpsest.pdf.pipeline import split_prefix
from palimpsest.server.app import create_app
from palimpsest.text.glossary import Glossary
from palimpsest.translate.cache import compute_namespace
from palimpsest.translate.direction import (
    config_for_target,
    resources_for,
    source_for,
)
from palimpsest.translate.translator import Translator
from tests.fixtures.fake_backend import FakeBackend

# -- direction.py itself ----------------------------------------------------


def test_source_is_the_other_language():
    assert source_for("en") == "es"
    assert source_for("es") == "en"


def test_unsupported_target_is_rejected():
    with pytest.raises(ValueError):
        source_for("fr")


def test_default_direction_keeps_config_and_ocr_language_untouched():
    cfg = Config()
    out = config_for_target(cfg, "en")
    assert (out.language.source, out.language.target) == ("es", "en")
    assert out.ocr.language == cfg.ocr.language


def test_reversed_direction_swaps_languages_and_ocr_pack():
    out = config_for_target(Config(), "es")
    assert (out.language.source, out.language.target) == ("en", "es")
    assert out.ocr.language == "eng"


def test_glossary_and_post_rules_only_apply_spanish_to_english():
    glossary = Glossary({"sociedad": "company"})
    rules = (("a", "b"),)
    assert resources_for("en", glossary, rules) == (glossary, rules)
    g, r = resources_for("es", glossary, rules)
    assert g.terms == {} and r == ()


# -- consumers --------------------------------------------------------------


def test_ordinals_are_only_peeled_for_a_spanish_source():
    assert split_prefix("DECIMO CUARTO. Las partes acuerdan")[0].strip() != ""
    prefix, rest = split_prefix("DECIMO CUARTO. text", source="en")
    assert prefix == ""
    assert rest == "DECIMO CUARTO. text"


def test_list_markers_are_still_peeled_for_an_english_source():
    prefix, rest = split_prefix("a) the tenant shall pay", source="en")
    assert prefix == "a) "
    assert rest == "the tenant shall pay"


def _translator(tmp_path, source, target, fn):
    backend = FakeBackend(translate_fn=fn)
    ns = compute_namespace(backend.name, None, source, target)
    return Translator(tmp_path / "c.json", backend, ns, source=source, target=target, verbose=False)


def test_unchanged_english_prose_is_flagged_identical_for_an_english_source(tmp_path):
    tr = _translator(tmp_path, "en", "es", lambda s: s)
    text, status = tr.translate("the company shall pay this amount to the party")
    assert (text, status) == (None, "identical")


def test_unchanged_spanish_prose_is_not_flagged_for_an_english_source(tmp_path):
    # Spanish function words are not "source language" signals when the
    # source is English, so an echoed name-like string stays ok.
    tr = _translator(tmp_path, "en", "es", lambda s: s)
    text, status = tr.translate("GRUPO MERIDIAN")
    assert status == "ok"


# -- server -----------------------------------------------------------------


class _CtxCapturingBackend(FakeBackend):
    def __init__(self, seen):
        super().__init__(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
        self._seen = seen

    def translate(self, text, ctx):
        self._seen.append((ctx.source_lang, ctx.target_lang, dict(ctx.glossary)))
        return super().translate(text, ctx)


def _client(tmp_path, seen):
    config = Config(
        paths=PathsConfig(
            work_dir=tmp_path / "work", cache_dir=tmp_path / "cache",
            report_dir=tmp_path / "reports",
        ),
        thresholds=ThresholdsConfig(),
        fonts=FontsConfig(use_bundled_fallback=True),
    )
    app = create_app(config, backend_factory=lambda _c, **_k: _CtxCapturingBackend(seen))
    return TestClient(app)


ES_TEXT = "Hola mundo, este es un documento de prueba para el sistema."
EN_TEXT = "Hello world, this is a test document for the translation system."


def _pdf(text):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(fitz.Rect(40, 40, 360, 160), text, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client, name, text):
    resp = client.post("/api/uploads", files={"file": (name, _pdf(text), "application/pdf")})
    assert resp.status_code == 200, resp.text
    return resp.json()["file_id"]


def _wait(client, job_id):
    deadline = time.time() + 15
    while time.time() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_each_file_is_translated_in_its_own_direction(tmp_path):
    seen: list = []
    with _client(tmp_path, seen) as c:
        es_file = _upload(c, "spanish.pdf", ES_TEXT)
        en_file = _upload(c, "english.pdf", EN_TEXT)
        resp = c.post(
            "/api/jobs",
            json={"file_ids": [es_file, en_file], "targets": {en_file: "es"}, "dual": False},
        )
        assert resp.status_code == 200, resp.text
        job = _wait(c, resp.json()["job_id"])

    assert job["status"] == "done", job
    by_id = {f["file_id"]: f for f in job["files"]}
    assert by_id[es_file]["target"] == "en"  # no entry -> the default
    assert by_id[en_file]["target"] == "es"
    pairs = {(s, t) for s, t, _ in seen}
    assert pairs == {("es", "en"), ("en", "es")}
    # The es->en glossary must not be applied to the reversed file.
    assert all(g == {} for s, t, g in seen if (s, t) == ("en", "es"))


def test_unsupported_target_is_a_400(tmp_path):
    with _client(tmp_path, []) as c:
        f = _upload(c, "doc.pdf", ES_TEXT)
        resp = c.post("/api/jobs", json={"file_ids": [f], "targets": {f: "fr"}})
        assert resp.status_code == 400
        est = c.post("/api/estimate", json={"file_ids": [f], "targets": {f: "fr"}})
        assert est.status_code == 400


def test_download_is_named_for_the_source_file_and_target_language(tmp_path):
    with _client(tmp_path, []) as c:
        f = _upload(c, "english.pdf", EN_TEXT)
        job_id = c.post(
            "/api/jobs", json={"file_ids": [f], "targets": {f: "es"}, "dual": False}
        ).json()["job_id"]
        _wait(c, job_id)
        resp = c.get(f"/api/jobs/{job_id}/download/replica")
    assert 'filename="english.es.pdf"' in resp.headers["content-disposition"]
