"""Server-written dates follow Wassla's Algerian Arabic: Maghrebi months, Western digits."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from apps.core.locale_format import MONTHS, format_utc_datetime

EASTERN_DIGITS = re.compile("[\u0660-\u0669\u06f0-\u06f9]")
MASHRIQ_MONTHS = ("يناير", "فبراير", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس")


class FormatUtcDatetimeTests(SimpleTestCase):
    def test_arabic_uses_algerian_month_names_and_western_digits(self):
        moment = datetime(2026, 8, 1, 9, 5, tzinfo=timezone.utc)
        self.assertEqual(format_utc_datetime(moment, "ar"), "1 أوت 2026، 09:05 UTC")

    def test_every_arabic_month_is_maghrebi(self):
        for month in range(1, 13):
            text = format_utc_datetime(datetime(2026, month, 15, tzinfo=timezone.utc), "ar")
            self.assertIn(MONTHS["ar"][month - 1], text)
            self.assertIsNone(EASTERN_DIGITS.search(text), text)
            for name in MASHRIQ_MONTHS:
                self.assertNotIn(name, text)

    def test_english_and_french(self):
        moment = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(format_utc_datetime(moment, "en"), "1 September 2026, 10:00 UTC")
        self.assertEqual(format_utc_datetime(moment, "fr"), "1 septembre 2026 à 10:00 UTC")

    def test_reads_event_payload_iso_strings_and_converts_to_utc(self):
        self.assertEqual(
            format_utc_datetime("2026-06-01T12:30:00+01:00", "ar"),
            "1 جوان 2026، 11:30 UTC",
        )
        local = datetime(2026, 7, 4, 1, 0, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(format_utc_datetime(local, "fr"), "3 juillet 2026 à 23:00 UTC")

    def test_missing_naive_or_unreadable_values_render_nothing(self):
        for value in (None, "", "not a date", "2026-09-01T10:00:00", datetime(2026, 9, 1)):
            self.assertEqual(format_utc_datetime(value, "ar"), "")

    def test_unknown_language_falls_back_to_english(self):
        moment = datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc)
        self.assertEqual(format_utc_datetime(moment, "de"), "3 February 2026, 04:05 UTC")
