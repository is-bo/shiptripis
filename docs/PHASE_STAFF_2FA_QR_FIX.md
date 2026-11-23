# Staff two-step sign-in: the enrolment QR code scans (2026-11-23)

Ismail's first sign-in to the staff console on the live server, 2026-11-23: the "Set up two-step
sign-in" page (L14) showed a QR code his authenticator app could not read. Nothing is deployed by
this change.

## Cause

`apps/admin_panel/two_step.py` `qr_svg()` asked segno for `scale=5, border=2`. segno then writes an
SVG `width="285" height="285"` (for a typical address) with no `viewBox`, and `admin.css` drew it in
a `width: min(220px, 100%)` box. Without a `viewBox` a browser does not shrink an SVG's drawing to
its box; it cuts it. The right and bottom 65 px were lost, and with them two of the three corner
squares a scanner looks for. The quiet zone was also 2 modules where the QR standard asks for 4.

Evidence: the owner's screenshot shows one corner square and a code cut off mid-module on the right
and bottom, and a QR decoder (zxing-cpp) finds no code in it. The old markup and CSS, rendered in
headless Edge with a test address, look the same and decode to nothing.

## Fix

- `qr_svg()` draws whole pixels per module (`scale=4`), a 4-module quiet zone (`border=4`), and asks
  for `unit="px"`, which makes segno add a `viewBox` matching the size.
- `admin.css` no longer forces a width: the code shows at the size it is drawn (228 to 260 px for
  usual addresses) and only shrinks, whole and square, when the card is narrower (`max-width: 100%`,
  `height: auto`). `shape-rendering: crispEdges` keeps a shrunk code free of faint lines between rows.

The address the code carries, the key, its storage and every verification rule are unchanged. No
new wording.

The same page rendered after the fix decodes to the exact `otpauth://` address in headless Edge at
500 px, with the card narrowed so the code shrinks, and at a phone's 2.625 device-pixel ratio.

## Test

`test_l14_two_step.py::EnrolmentQrCodeTests` rebuilds the module grid from the SVG and checks that
it is exactly segno's symbol for the address, square, in whole pixels, with a matching `viewBox`,
dark on a light square, and with at least 4 modules of quiet zone on every side. It fails on the old
parameters (no `viewBox`).

## A fresh key after an exposed one

The key is made once, the first time the enrolment page opens, and kept until it is confirmed:
signing out and in again shows the same key (`pending_enrolment()`, on purpose, so an app that
already scanned it keeps working). A new key comes only from a reset, which deletes the pending or
confirmed enrolment and the recovery codes, ends the account's sessions and writes an audit row:

- another Super Admin: Staff page, "Reset two-step sign-in" (needs a fresh code of their own);
- the last Super Admin: on the server, in the app container,
  `python manage.py reset_admin_two_step <email> --reason "<why>"`.

The next sign-in then opens the enrolment page with a new key.
