# Phase J8.4 — Public Legal Route Edge Fix Report

**Execution Date:** 2026-09-19  
**Branch:** `main`  
**Phase Purpose:** Remediate the public edge routing defect identified in J8.3, where canonical legal routes (`/terms`, `/privacy`) returned HTTP 404 on the TEST public origin (`https://shiptrip-production-f7f7.up.railway.app`) because Caddy matched only `.html` file extensions and forwarded extensionless requests to Django.

---

## 1. Root Cause Analysis

In J8.1, mobile `ProfileScreen` was wired to open canonical legal routes resolved via `AppConfig.webBaseUrl`:
- Terms of Service: `/terms`
- Privacy Policy: `/privacy`

However, the deployed edge proxy configurations (`backend/railway/Caddyfile` and `backend/gateway/Caddyfile`) defined static routing using:
```caddy
@public path / /index.html /en/* /fr/* /ar/* /assets/* /terms.html /privacy.html /prohibited-items.html /support.html /robots.txt /sitemap.xml /favicon.ico
handle @public {
    header Content-Security-Policy ...
    header Cache-Control "public, max-age=300"
    root * /web
    encode gzip
    file_server
}
```

Because extensionless clean URLs `/terms` and `/privacy` were omitted from `@public path`:
1. Requests for `/terms` and `/privacy` failed to match `@public`.
2. They fell through to the catch-all Django reverse proxy (`reverse_proxy 127.0.0.1:8000`).
3. Django's `config/urls.py` intentionally does not serve static marketing or legal pages, which are isolated from the authenticated application surface.
4. Django responded with HTTP 404.
5. Meanwhile, `/terms.html` and `/privacy.html` matched `@public` and returned HTTP 200 directly from static storage.

---

## 2. Solution: Clean Internal Rewrites (Option A)

In accordance with phase instructions, the canonical URLs `/terms` and `/privacy` are preserved without modifying mobile source code.

In both `backend/railway/Caddyfile` and `backend/gateway/Caddyfile`:
1. Updated `@public path` to match clean paths and trailing-slash variants:
   ```caddy
   @public path / /index.html /en/* /fr/* /ar/* /assets/* /terms /terms/ /terms.html /privacy /privacy/ /privacy.html /prohibited-items /prohibited-items/ /prohibited-items.html /support /support/ /support.html /robots.txt /sitemap.xml /favicon.ico
   ```
2. Added internal `rewrite` directives inside `handle @public`:
   ```caddy
   rewrite /terms /terms.html
   rewrite /terms/ /terms.html
   rewrite /privacy /privacy.html
   rewrite /privacy/ /privacy.html
   rewrite /prohibited-items /prohibited-items.html
   rewrite /prohibited-items/ /prohibited-items.html
   rewrite /support /support.html
   rewrite /support/ /support.html
   ```

### Architecture Benefits:
- **Clean Browser URL:** The browser's address bar remains `https://shiptrip-production-f7f7.up.railway.app/terms` with zero redirect round-trips.
- **Backward Compatibility:** Requests to `/terms.html` and `/privacy.html` continue to return HTTP 200.
- **Route Isolation:** Backend routes (`/api/*`, `/admin/*`, `/pay/*`, `/payouts/*`, `/healthz`, `/readyz`) and Go services (`/ws/*`, `/kyc/*`) remain completely unaffected and unintercepted.

---

## 3. Automated Test Suites & Quality Gates

1. **`tools/check_static_web.py`:**
   - Added `check_edge_routing()` which inspects both Caddyfiles, verifies required routes and rewrite directives, verifies that target HTML files exist with correct headers, and validates that protected routes are never shadowed.
   - Verified: `static web and edge routing check passed (8 HTML files, 1 stylesheet, 2 Caddy edge configs verified)`.
2. **`backend/monolith/apps/finance/tests/test_deployment_safety.py`:**
   - Added `PublicEdgeRoutingTests` asserting that both Caddyfiles define clean legal rewrites, target documents exist with valid headings, and protected routes are not shadowed.
   - Verified: **40 passed, 0 failed**.
3. **Django Production Deployment Check:**
   - `python manage.py check --deploy --fail-level WARNING`: System check identified no issues (0 silenced).
4. **Schema Drift Check:**
   - `python manage.py makemigrations --check --dry-run`: No changes detected (0 drift).
5. **Ruff Linter:**
   - `python -m ruff check .`: All checks passed.

---

## 4. Deployment & Live Verification

- Deployed to Railway TEST environment (`https://shiptrip-production-f7f7.up.railway.app`).
- Financial safety invariants maintained:
  - Stripe TEST mode.
  - Chargily TEST mode.
  - `PAYOUT_DZD_EXECUTION_ENABLED=false`.
  - Zero real-money transactions.

### Live Production TEST Origin HTTP Verification:
| Endpoint | Method | Result | Content-Type | Document Content |
|---|---|---|---|---|
| `/terms` | GET | **200 OK** | `text/html; charset=utf-8` | Contains `<h1>Terms of Service</h1>` |
| `/privacy` | GET | **200 OK** | `text/html; charset=utf-8` | Contains `<h1>Privacy Policy</h1>` |
| `/terms.html` | GET | **200 OK** | `text/html; charset=utf-8` | Contains `<h1>Terms of Service</h1>` |
| `/privacy.html` | GET | **200 OK** | `text/html; charset=utf-8` | Contains `<h1>Privacy Policy</h1>` |
| `/healthz` | GET | **200 OK** | `application/json` | `{"status":"ok"}` |
| `/readyz` | GET | **200 OK** | `application/json` | `{"status":"ready"}` |

---

## 5. Mobile Compatibility & APK Status

- **Mobile Source Code:** **NOT MODIFIED** (0 files changed in `mobile/`).
- **APK Rebuild:** **NOT BUILT** (unnecessary).
- **Existing J8.3 APK:**
  - Filename: `shiptrip-v1.0.0-j83-test-07f777e-profile-arm64.apk`
  - SHA-256: `621394886c2548c20519b260258e92d4353ccb5f2e7c7daee53dd6a1c2cbb5d3`
  - Built from commit: `07f777ee3b88df801eb920479edb0699ebc948b4`
  - The J8.3 APK already contains the canonical links to `/terms` and `/privacy`. Following this edge deployment, legal links opened from the app in the external browser resolve and render the authoritative documents with HTTP 200.

---

## 6. Defect Closure & Pre-LIVE Verdict

- **Blockers:** 0
- **Majors:** 0
- **Minors:** 0 (The edge routing defect identified during J8.3 is fully remediated and verified live).
- **Verdict:** **PASS**. All product-code and edge routing defects are resolved.
