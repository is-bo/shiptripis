#!/usr/bin/env python3
"""Fail CI on broken local links, CSP-incompatible static HTML, or broken edge routing.

The production CSP is `default-src 'self'`, which means an inline style, an
inline script, a `data:` URI or a hosted font is not a style choice — it is a
resource the browser will refuse to load. The rules below are the shape of that
policy, checked before a deploy rather than discovered in a console.

The stylesheet is checked too: its `@font-face` sources are the one class of
asset an HTML-only crawl cannot see, and a page that ships without the faces it
asks for degrades silently into system fallbacks.

Edge routing (Caddy) is also validated: canonical public clean URLs (/terms, /privacy)
must be matched by the public matcher, rewritten to their respective .html documents,
and served without redirect loops or interference with Django/API endpoints.
"""

from __future__ import annotations

import html.parser
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
CADDYFILES = (
    ROOT / "backend" / "railway" / "Caddyfile",
    ROOT / "backend" / "gateway" / "Caddyfile",
)


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


def check_edge_routing() -> list[str]:
    """Validate that Caddy edge configurations route canonical clean URLs properly.

    Mobile clients and public web canonical links rely on `/terms` and `/privacy`.
    These routes must be routed by Caddy to the underlying `.html` static files
    via internal rewrite, without redirect loops, and without shadowing Django/API
    routes.
    """

    errors: list[str] = []

    # 1. Verify target static legal documents exist and contain valid headings
    terms_file = WEB / "terms.html"
    if not terms_file.exists():
        errors.append("web/terms.html does not exist")
    else:
        terms_text = terms_file.read_text(encoding="utf-8")
        if "<title>Terms of Service — ShipTrip</title>" not in terms_text:
            errors.append("web/terms.html missing expected title")
        if "<h1>Terms of Service</h1>" not in terms_text:
            errors.append("web/terms.html missing Terms of Service header")

    privacy_file = WEB / "privacy.html"
    if not privacy_file.exists():
        errors.append("web/privacy.html does not exist")
    else:
        privacy_text = privacy_file.read_text(encoding="utf-8")
        if "<title>Privacy Policy — ShipTrip</title>" not in privacy_text:
            errors.append("web/privacy.html missing expected title")
        if "<h1>Privacy Policy</h1>" not in privacy_text:
            errors.append("web/privacy.html missing Privacy Policy header")

    # 2. Check each Caddyfile for clean URL support
    for caddyfile in CADDYFILES:
        name = caddyfile.relative_to(ROOT)
        if not caddyfile.exists():
            errors.append(f"{name}: file does not exist")
            continue
        text = caddyfile.read_text(encoding="utf-8")

        # Find the @public path matcher
        match = re.search(r"@public\s+path\s+([^\n]+)", text)
        if not match:
            errors.append(f"{name}: missing @public path matcher")
            continue
        public_paths = match.group(1).split()

        # Ensure required canonical clean paths are covered
        for required_path in ("/terms", "/privacy", "/terms.html", "/privacy.html"):
            if required_path not in public_paths:
                errors.append(f"{name}: @public path matcher missing required route '{required_path}'")

        # Ensure trailing slash variants are also covered
        for slash_path in ("/terms/", "/privacy/"):
            if slash_path not in public_paths:
                errors.append(f"{name}: @public path matcher missing trailing slash route '{slash_path}'")

        # Ensure internal rewrite directives exist for clean legal URLs
        for route, target in (
            ("/terms", "/terms.html"),
            ("/terms/", "/terms.html"),
            ("/privacy", "/privacy.html"),
            ("/privacy/", "/privacy.html"),
        ):
            expected_directive = f"rewrite {route} {target}"
            if expected_directive not in text:
                errors.append(f"{name}: missing required directive '{expected_directive}'")

        # Ensure @public matcher does NOT intercept backend, API, or WebSocket routes
        for protected_prefix in ("/api", "/admin", "/pay", "/payouts", "/healthz", "/readyz", "/ws", "/kyc"):
            for path in public_paths:
                if path.startswith(protected_prefix):
                    errors.append(f"{name}: @public path matcher incorrectly intercepts protected route '{path}'")

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
    errors.extend(check_edge_routing())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    sheets = len(list(WEB.rglob("*.css")))
    print(
        f"static web and edge routing check passed ({len(pages)} HTML files, "
        f"{sheets} stylesheet{'' if sheets == 1 else 's'}, 2 Caddy edge configs verified)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
