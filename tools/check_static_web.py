#!/usr/bin/env python3
"""Fail CI on broken local links or CSP-incompatible static HTML.

The production CSP is `default-src 'self'`, which means an inline style, an
inline script, a `data:` URI or a hosted font is not a style choice — it is a
resource the browser will refuse to load. The rules below are the shape of that
policy, checked before a deploy rather than discovered in a console.

The stylesheet is checked too: its `@font-face` sources are the one class of
asset an HTML-only crawl cannot see, and a page that ships without the faces it
asks for degrades silently into system fallbacks.
"""

from __future__ import annotations

import html.parser
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class Inspector(html.parser.HTMLParser):
    def __init__(self, source: Path):
        super().__init__()
        self.source = source
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if "style" in values:
            self.errors.append("inline style is blocked by production CSP")
        if tag in {"script", "style"} and not values.get("src"):
            self.errors.append(f"inline <{tag}> is blocked by production CSP")
        for attribute in ("href", "src"):
            value = values.get(attribute) or ""
            if not value or value.startswith(("#", "mailto:", "tel:")):
                continue
            parsed = urlparse(value)
            if parsed.scheme or parsed.netloc:
                self.errors.append(f"external resource/link is not reviewed: {value}")
                continue
            path = parsed.path
            if not path:
                continue
            if path.startswith("/"):
                target = WEB / path.lstrip("/")
            else:
                target = self.source.parent / path
            if path.endswith("/"):
                target /= "index.html"
            if not target.exists():
                self.errors.append(f"missing local target: {value}")


#: Assets every page must name. A missing favicon is a 404 on every visit and a
#: missing stylesheet is an unstyled page; both are the kind of regression a
#: copy-paste of a new page introduces silently.
REQUIRED_REFERENCES = ("/assets/site.css", "/assets/favicon.svg", "/favicon.ico")

CSS_URL = re.compile(r"""url\(\s*["']?(/[^"')\s]+)["']?\s*\)""")


def check_stylesheets() -> list[str]:
    """Every asset a stylesheet asks for must exist, and must be local.

    `@font-face` sources are invisible to an HTML-only crawl, and a stylesheet
    that names a face nobody built degrades to a system fallback without any
    error anywhere. That is exactly the failure the bundled fonts exist to
    prevent, so it is checked rather than assumed.
    """

    errors: list[str] = []
    for sheet in sorted(WEB.rglob("*.css")):
        text = sheet.read_text(encoding="utf-8")
        name = sheet.relative_to(ROOT)
        # Matched inside `url(...)` rather than anywhere in the file, so a
        # comment explaining the rule does not trip the rule.
        if re.search(r"""url\(\s*["']?data:""", text):
            errors.append(f"{name}: a data: URI is blocked by the production CSP")
        for url in CSS_URL.findall(text):
            if not (WEB / url.lstrip("/")).exists():
                errors.append(f"{name}: missing asset referenced by the stylesheet: {url}")
        if re.search(r"""url\(\s*["']?https?://""", text):
            errors.append(f"{name}: external resource is blocked by the production CSP")
        if "@import" in text:
            errors.append(f"{name}: @import adds a render-blocking round trip")
    return errors


def main() -> int:
    errors: list[str] = []
    pages = sorted(WEB.rglob("*.html"))
    for source in pages:
        text = source.read_text(encoding="utf-8")
        inspector = Inspector(source)
        inspector.feed(text)
        errors.extend(f"{source.relative_to(ROOT)}: {error}" for error in inspector.errors)
        for required in REQUIRED_REFERENCES:
            if required not in text:
                errors.append(f"{source.relative_to(ROOT)}: does not reference {required}")
    errors.extend(check_stylesheets())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    sheets = len(list(WEB.rglob("*.css")))
    print(
        f"static web check passed ({len(pages)} HTML files, "
        f"{sheets} stylesheet{'' if sheets == 1 else 's'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
