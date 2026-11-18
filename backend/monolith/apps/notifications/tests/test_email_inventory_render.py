"""Every email the outbox can write, in English, French and Arabic.

For each `OutboundMessage.Kind`, and for each branch of its copy that a
context can select, the French and Arabic subject and heading must be the
catalogue's translation of the English one, never English left untranslated.
The checks read the committed `.po` catalogues directly, so a missing or empty
entry fails here even when the compiled `.mo` would quietly fall back.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import translation

from apps.notifications import outbox
from apps.notifications.models import OutboundMessage

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "egs_compile_po", ROOT.parents[1] / "tools" / "compile_po.py"
)
_compile_po = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_compile_po)

CATALOGUES = {
    language: _compile_po._catalog(ROOT / f"locale/{language}/LC_MESSAGES/django.po")
    for language in ("fr", "ar")
}

BASE = {
    "frontend_base_url": "https://app.example.invalid",
    "role": "support",
    "payment_reference": "PAY-test",
    "amount_eur_cents": 1234,
    "tracking_number": "WSL-TEST1",
    "protection_ends_at": "2099-01-01T00:00:00+00:00",
}

#: Each context selects another branch of some kind's copy; kinds ignore the
#: keys they do not read.
BRANCHES = (
    {},
    {"status": "approved"},
    {"status": "rejected"},
    {"outcome": "resubmission_requested"},
    {"mode": "SEA", "status": "approved"},
    {"mode": "SEA", "status": "rejected"},
    {"mode": "SEA", "outcome": "resubmission_requested"},
    {"status": "succeeded"},
    {"status": "failed"},
    {"event": "password_reset_completed"},
)


def _document(kind: str, context: dict, language: str):
    message = OutboundMessage(kind=kind, language=language, context=context)
    with patch.object(outbox, "resolve_secret", return_value="483921"), translation.override(
        language
    ):
        return outbox._build_document(message)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", OutboundMessage.Kind.values)
def test_every_kind_has_a_translated_subject_and_heading_in_french_and_arabic(kind):
    seen = set()
    for branch in BRANCHES:
        context = {**BASE, **branch}
        english = _document(kind, context, "en")
        if (english.subject, english.heading) in seen:
            continue
        seen.add((english.subject, english.heading))
        for language, catalogue in CATALOGUES.items():
            localized = _document(kind, context, language)
            for field in ("subject", "heading"):
                source = getattr(english, field)
                assert catalogue.get(source), f"{kind} {field} {source!r} has no {language} entry"
                assert getattr(localized, field) == catalogue[source]
                assert getattr(localized, field) != source, (
                    f"{kind} {field} is English in {language}"
                )
    assert seen


@pytest.mark.django_db
@pytest.mark.parametrize("language", ["en", "fr", "ar"])
@pytest.mark.parametrize("kind", OutboundMessage.Kind.values)
def test_every_footer_shows_the_contact_address(kind, language):
    assert settings.WASSLA_CONTACT_ADDRESS == "contact@wassla.eu"
    message = OutboundMessage(kind=kind, language=language, context=BASE)
    with (
        override_settings(EMAIL_SUPPORT_ADDR=settings.WASSLA_CONTACT_ADDRESS),
        patch.object(outbox, "resolve_secret", return_value="483921"),
    ):
        subject, text, html = outbox.render_parts(message)
    assert subject
    assert "contact@wassla.eu" in text
    assert 'href="mailto:contact@wassla.eu"' in html
