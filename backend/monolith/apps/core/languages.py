"""Durable communication-language choices shared by accounts and messages.

Request headers are useful for rendering one HTTP response, but they are not a
stable preference for an email that may be dispatched hours later. Domain rows
therefore store one of these explicit values and the outbox snapshots the
resolved value when an obligation is armed.
"""

from django.db import models


class CommunicationLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    FRENCH = "fr", "French"
    ARABIC = "ar", "Arabic"


DEFAULT_COMMUNICATION_LANGUAGE = CommunicationLanguage.ENGLISH
SUPPORTED_COMMUNICATION_LANGUAGES = frozenset(CommunicationLanguage.values)


def normalize_communication_language(value: object) -> str:
    """Return a supported language, falling back to complete English copy.

    API serializers reject unsupported choices. This defensive fallback is
    for legacy rows and internal callers: a malformed stored value must never
    create a half-rendered or permanently stuck critical email.
    """

    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_COMMUNICATION_LANGUAGES:
        return normalized
    return str(DEFAULT_COMMUNICATION_LANGUAGE)
