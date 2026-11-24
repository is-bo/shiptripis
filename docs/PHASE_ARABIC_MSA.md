# Arabic copy in Modern Standard Arabic

The Arabic locale uses clear, concise Modern Standard Arabic (الفصحى). The guest,
account creation and sign-in flows previously contained most of the Darja copy.
For example, «كيفاش تخدم Wassla» became «كيف تعمل Wassla؟», and the sign-in
separator «ولا» became «أو».

## Scope

- Flutter strings, including guest and account prompts, offer and handover copy,
  payout setup and the iOS permission prompts. The ARB keys, metadata,
  placeholders and ICU structures are preserved.
- Django's Arabic email catalogue, push notifications, and the guest payment,
  payment result and Stripe return pages. The catalogue's message IDs and format
  placeholders are preserved.
- The public Arabic landing page and Arabic account deletion help. The active
  agent instructions and email, guest and social plan use the new language rule.

[Arabic dates and digits](PHASE_ARABIC_DATES_AND_DIGITS.md) still defines Western
digits, Algerian month names, a 24-hour clock and left-to-right isolation for
codes and tracking numbers.

## Vocabulary

| English | Arabic |
| --- | --- |
| Parcel | طرد |
| Traveler | مسافر |
| Sender | مُرسِل |
| Trip or journey | رحلة |
| Offer or proposal | عرض |
| Counteroffer | عرض مقابل |
| Deal | صفقة |
| Tracking number | رقم التتبع |
| Delivery code | رمز التسليم |
| Pickup code | رمز الاستلام |
| Payment | دفع |
| Posting deposit | عربون |
| Payout | تحويل الأرباح |
| Refund | استرداد المبلغ |

## Tests changed

- `mobile/test/phase8fh6b_payout_screens_test.dart`, “PayoutMethodsScreen
  renders cleanly in Arabic RTL without overflow.” Updated the three payout
  label expectations because Arabic copy moved to Modern Standard Arabic.
- `mobile/test/arabic_dates_and_digits_test.dart` and
  `backend/monolith/apps/core/tests/test_locale_format.py`. Updated the file
  comments to describe Algerian date conventions under the new Arabic copy
  standard. The date and digit assertions are identical.

## Screenshots

Arabic Flutter screens at 360 × 800 px with bundled fonts and fixture data.

- [Home](screenshots/arabic-msa/home-guest-ar.png)
- [Trip details](screenshots/arabic-msa/trip-detail-ar.png)
- [Post a request](screenshots/arabic-msa/post-request-ar.png)
- [Deliveries](screenshots/arabic-msa/deliveries-ar.png)
- [Profile](screenshots/arabic-msa/profile-ar.png)
