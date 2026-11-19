# Wassla public website

This directory is a dependency-free static landing site for the EU ↔ Algeria
launch scope. It contains English (`/en/`), French (`/fr/`) and Arabic
(`/ar/`) routes, plus structural Terms, Privacy, prohibited-items and
Support pages. Arabic is rendered with `dir="rtl"` and a dedicated Arabic font
fallback. Product/legal pages are drafts pending final French, EU and Algerian
review.

## Run locally

From the repository root:

```bash
python -m http.server 4173 --directory web
```

Open <http://localhost:4173/>. The site has no build step or runtime
dependency; a CDN or any static host can serve the directory as-is. Canonical
and OpenGraph links are root-relative so they follow the deployed origin. The
absolute origin in `sitemap.xml` and `robots.txt` must be set by the deployment
template before launch; the checked-in example intentionally does not claim a
real domain.

## Fonts

The four faces the mobile app bundles are subset and served from this origin —
the production CSP is `default-src 'self'`, so a hosted font would not load, and
naming a face without shipping it degrades silently to a system fallback.

```bash
python tools/web/build_fonts.py
```

It reads the variable fonts out of `mobile/assets/fonts/`, pins the non-weight
axes to the values `mobile/lib/design/typography.dart` sets, subsets each to the
range the site actually uses, and writes woff2 into `web/assets/fonts/`
(Fraunces 66 KiB, DM Sans 36 KiB, Noto Sans Arabic 154 KiB, JetBrains Mono
7 KiB). `unicode-range` keeps the Arabic face off the English and French routes.
Requires `fonttools` and `brotli`.

`tools/check_static_web.py` fails the build if the stylesheet asks for a face
that is not there, references anything external, uses `@import` or a `data:`
URI, or if a page forgets the stylesheet or either favicon.

## Screenshots

`tools/web/shot.sh <url> <out.png> [width] [height]` renders a page with
headless Edge. Note the floor documented in that script: Edge on Windows will
not lay out below ~492 CSS px, so phone widths have to be reviewed in a browser
that emulates the viewport properly.

## Landing hero

The root and EN/FR/AR pages share `assets/hero.css` and native ES modules.
`hero-globe.mjs` manages lifecycle, motion, labels and the featured route;
`globe-renderer.mjs` renders an actual perspective sphere using WebGL;
`globe-math.mjs` shares the projection with `globe-network.mjs`'s ambient
journeys. No globe library, framework, runtime API or build step is required.

The geography source, license, pinned digest, camera and asset regeneration
instructions are in [assets/globe/README.md](assets/globe/README.md). Public-web
design decisions are recorded in [DESIGN.md](DESIGN.md); the root design
document remains scoped to the Flutter app.

Run the scoped checks from the repository root:

```sh
python tools/check_static_web.py
node --test tools/web/globe.test.mjs
```

The static check follows local module imports and script-owned assets as well
as HTML, CSS and existing legal edge routes. CI runs the journey/geography
tests without installing an npm dependency. `tools/web/check_hero_browser.js`
can be piped into an isolated agent-browser session's `eval --stdin` on `/en/`
for animated and reduced-motion lifecycle checks. Use a local server sending
the production CSP when validating browser behavior; a plain Python server
does not attach those headers or rewrite clean legal URLs.

## Email boundary

The website only links to support mailboxes. Transactional email remains on
the existing durable Django `OutboundMessage` outbox and Go email worker, sent
through Sender.net's REST API from contact@wassla.eu (`infra/vps/EMAIL.md`).
Its API token lives only in the deployment's secret file; no credentials belong
in this tree. The
outbox resolves a delivery code only while rendering the final recipient
message from its sealed `secret_ref`; it never stores it in Redis, an event
payload, logs or a notification row.

Production deliverability still requires a verified sending domain with SPF,
DKIM and DMARC, a monitored contact@wassla.eu mailbox, and a monitored
Sender.net account.
