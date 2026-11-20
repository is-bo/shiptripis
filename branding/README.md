# Wassla application branding

`wassla/` is the supplied branding package, preserved unchanged. Its SVG paths
are the visual source. Existing orange, yellow, neutral, success and transport
colors remain unchanged; only brand emerald is replaced with `#042D49` and
`#021E33`, with ivory foreground ink on dark surfaces.

Run `python tools/branding/build_assets.py` with CairoSVG and Pillow installed
to reproduce web/admin vectors, Flutter PNGs, native icons and launch artwork.
The PNGs are proportional exports, not replacement designs. iOS icons are
composited on the supplied navy to meet the opaque-icon requirement. Android
12's launch symbol is padded inside the system mask's safe area. Android 8 and
newer use an adaptive launcher icon made of vector layers: the app icon's navy
surface, the ivory-and-yellow W inside the 66 dp safe circle, and a one-colour
W that Android 13 tints for themed icons.

The landing page and email retain their existing light presentation even under
a dark system preference. Flutter, the admin and hosted payment pages retain
their existing light/dark behavior and select artwork for the actual background.
Email uses a PNG from the existing `FRONTEND_BASE_URL` origin, with alt text and
a text-only fallback when no absolute public origin is configured. No delivery
settings, sender addresses, domains or transport code are changed.

Compatibility names intentionally remain in import paths, storage keys,
notification channels, URLs, migrations and provider requests. The app id
(Android application id and iOS bundle id) is `eu.wassla.app`.
In particular, historical Stripe account and checkout descriptions participate
in persisted fingerprints and idempotent replay. The integrated V1/V2 provider
strings retain Waçla byte-for-byte; the app's guest-payment description converts
both historical names to Wassla only at the presentation boundary.

Checks: Flutter analyze/tests, Django notification/admin/payment-presentation
tests, `python tools/check_static_web.py`, and
`node --test tools/web/globe.test.mjs`. Local Django tests must run with
`EMAIL_ENABLED=false`, matching CI's default; a workspace SMTP configuration
otherwise changes expected guest-receipt and provider-readiness behavior.

For local screenshots of real Flutter widgets with synthetic account data,
run from `mobile/`:

```sh
flutter test --no-pub ../tools/branding/flutter_preview.dart
flutter test --no-pub --dart-define=WASSLA_PREVIEW_WIDTH=1280 ../tools/branding/flutter_preview.dart
```

This writes light/dark EN/FR/AR captures of Home, welcome, sign-in, profile and
splash into `mobile/build/rebrand/screenshots`. It loads the actual bundled
fonts and logos, and exercises layout at phone and desktop sizes. Native OS
launch-screen and store-icon verification still requires an Android/iOS device
or simulator; no APK is built by this workflow.
