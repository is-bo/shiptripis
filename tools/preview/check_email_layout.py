"""Local-only email layout probes; no SMTP, database writes or external resources.

Optional test dependencies: Playwright and a local Chromium executable. Run with
PYTHONPATH=backend/monolith DJANGO_SETTINGS_MODULE=config.settings.dev python
tools/preview/check_email_layout.py --chromium /usr/bin/chromium.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from unittest.mock import patch

import django
from django.test import override_settings
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    django.setup()
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import render_parts

    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    results = []
    with (
        sync_playwright() as playwright,
        patch("apps.notifications.outbox.resolve_secret", return_value="483921"),
        override_settings(
            TRANSACTIONAL_EMAIL_ENABLED=False,
            EMAIL_SUPPORT_ADDR="support@example.invalid",
            FRONTEND_BASE_URL="https://app.example.invalid",
        ),
    ):
        browser = playwright.chromium.launch(
            executable_path=args.chromium,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            timeout=30000,
        )
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            for locale in ("en", "fr", "ar"):
                for kind in OutboundMessage.Kind.values:
                    context = {
                        "frontend_base_url": "https://app.example.invalid",
                        "role": "support",
                        "status": "succeeded",
                        "payment_reference": "PAY-01234567-89ab-4cde-0123-456789abcdef",
                        "deal_reference": "ST-01234567-89ab-4cde-0123-456789abcdef",
                        "amount_eur_cents": 1234,
                        "event": "password_reset_completed",
                        "recipient_name": "Local recipient",
                        "protection_ends_at": "2030-10-20T12:00:00Z",
                    }
                    _, _, html = render_parts(
                        OutboundMessage(kind=kind, language=locale, context=context)
                    )
                    for inline_only in (False, True):
                        body = (
                            re.sub(r"<style>.*?</style>", "", html, flags=re.S)
                            if inline_only
                            else html
                        )
                        for width in (320, 390, 800):
                            page.set_viewport_size({"width": width, "height": 1400})
                            page.set_content(
                                body, wait_until="domcontentloaded", timeout=5000
                            )
                            facts = page.evaluate("""() => ({
                                content: document.documentElement.scrollWidth,
                                rtl: getComputedStyle(document.body).direction === 'rtl',
                                brand: document.body.textContent.includes('Waçla')
                            })""")
                            results.append(
                                {
                                    "kind": kind,
                                    "locale": locale,
                                    "width": width,
                                    "inline_only": inline_only,
                                    **facts,
                                }
                            )
                            if (
                                args.screenshots
                                and not inline_only
                                and (
                                    (
                                        locale == "ar"
                                        and kind
                                        in (
                                            "admin_invitation",
                                            "recipient_delivery_code",
                                        )
                                    )
                                    or (locale == "fr" and kind == "delivery_confirmed")
                                )
                                and width in (390, 800)
                            ):
                                page.screenshot(
                                    path=str(
                                        args.screenshots
                                        / f"{kind}-{locale}-{width}.png"
                                    ),
                                    full_page=True,
                                )
        finally:
            browser.close()
    failures = [
        r
        for r in results
        if r["content"] > r["width"]
        or not r["brand"]
        or r["rtl"] != (r["locale"] == "ar")
    ]
    print(json.dumps({"checks": len(results), "failures": failures}, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
