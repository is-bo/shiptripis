# ShipTrip public website

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

## Email boundary

The website only links to support mailboxes. Transactional email remains on
the existing durable Django `OutboundMessage` outbox and Go email worker. A
Sender.net account is configured as an SMTP relay (`smtp.sender.net`, TLS on
587) through environment variables; no credentials belong in this tree. The
outbox resolves a delivery code only while rendering the final recipient
message from its sealed `secret_ref`; it never stores it in Redis, an event
payload, logs or a notification row.

Production deliverability still requires a verified sending domain with SPF,
DKIM and DMARC, valid TLS, and a monitored Sender.net account.
