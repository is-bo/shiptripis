# L11B: Tracking number, mobile

Package L11B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built against `docs/PHASE_L11A_TRACKING_NUMBER.md`
and spec section 16. The app shows the parcel's tracking number (`WSL-7K3M9QXD`) wherever a screen
refers to a parcel. No amount, code, state or matching result changed, and there is no backend change.

## 1. The shared widget

`mobile/lib/design/components/tracking.dart`, `TrackingNumberView(number, dense)`. Later mobile packages
use it on their own screens (plan 1.5 rule 12) and never print a record id as a reference.

- **Full form.** A sunken panel with the label "Tracking number", the number in the mono face, and a
  copy button. Copy puts the number on the clipboard, flips the icon to a check for two seconds, gives a
  haptic tick and announces "Tracking number copied" to a screen reader.
- **Dense form.** One quiet line, label and number, no copy button. Used on lists that open a detail
  screen, which offers the copy.
- **Always left to right.** The number is laid out in a left-to-right `Directionality` and aligned to the
  start edge, so in Arabic it is read, spoken and copied in the order it was issued.
- **Spelled out.** The semantic label is "Tracking number, W S L 7 K 3 M 9 Q X D".
- **Absent means nothing.** A null, empty or blank number renders no widget, no spacing and no
  placeholder; screens guard the spacing with `if (x.trackingNumber != null)`.
- **Display only.** No tap on the number, and no deep link or search, opens a parcel from it.

Strings: `trackingNumberLabel`, `trackingNumberCopy`, `trackingNumberCopied` in EN, FR and AR.

## 2. Payloads read

`readTrackingNumber` (`domain/json.dart`) returns the trimmed text or null; the app never validates or
parses the number. `trackingNumber` is read on `DeliveryRequest` (sender only), `Match`, `Offer`, `Deal`,
`PaymentOrder`, `DealPaymentState`, `PayoutMobile`, `PayoutListItem` and `Dispute`.

## 3. Where it shows

| Screen | Place |
| --- | --- |
| Request detail (sender) | Under the title and status |
| Delivery screen (`DealScreen`, sender and traveler) | In the status header card |
| Proposal / negotiation | In the header card, with the other person |
| Deal payment (sender and traveler) | At the top of the summary, above the amount |
| Dispute detail | In the header card |
| Payout detail | Above the earnings card |
| Payout history | Dense line on each payout |

It is never on a discovery card, a browse list, Find Travelers or a public preview: those payloads do
not carry it, and no L11B change adds it to them.

## 4. Removed

No screen printed a delivery id as a reference at the baseline (`grep` for `ST-`, `Deal #` and a raw
`deal.id` in text returns nothing in `mobile/lib`), so there was nothing to remove.

## 5. Tests

`mobile/test/l11b_tracking_number_test.dart`: the widget in EN, FR and AR at 360 px (left to right, no
overflow), the spelled-out label, copy and confirmation, the dense form, null/empty/blank; every payload
with and without the key; each screen above with and without a number (nothing rendered without one).

Screenshots, in `/mnt/project-files/l-series-screens/L11B/` at 360 px, `-en` and `-ar`:
`request-detail`, `request-detail-no-number`, `delivery`, `proposal`, `payment`, `dispute`,
`payout-detail`, `payout-list`, `widget`, `widget-copied`. There is no form, so no keyboard-open shot.

## 6. Judgment calls

1. The posting-deposit screen does not show the number: the plan's list of screens leaves it out, though
   `PaymentOrder.trackingNumber` is read and ready for it.
