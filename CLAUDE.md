# ShipTrip Claude Code Instructions

Before substantial work, read:

- `docs/SHIPTRIP_V1_SPEC.md`
- `docs/IMPLEMENTATION_STATUS.md`

The specification is authoritative when legacy code, documentation, comments, tests, or previous assumptions conflict with it, unless the user explicitly overrides it.

## Primary role

Claude primarily owns Flutter UI/UX, frontend architecture, navigation, the design system, Impeccable-driven frontend work, accessibility, Arabic RTL, localization, frontend performance, client state, validation and error UX, the admin frontend, the landing site, and integration review. Claude is not restricted to styling.

Codex remains the primary engineering and backend owner. Claude may make safe frontend and integration changes and must clearly report backend issues for Codex to fix. Review and flag awkward or unsafe API contracts, backend integration problems, auth/session edge cases, state inconsistencies, frontend security issues, and stale or race-state UX problems.

## Permanent UI rules

- Main mobile navigation is Home, Deliveries, Chat, and Profile.
- Notifications belong in the header/bell.
- Traveler My Trips and Carrying belong in the same Deliveries experience.
- Audit and fix bottom-navigation overlap across forms, lists, maps, chat, keyboards, sheets, small phones, Android gesture navigation, the iPhone home indicator, landscape, and Arabic RTL.
- Treat loading, empty, error, offline, validation, accessibility, localization, and responsive states as intentional product behavior.
- Do not fake payment, verification, delivery or payout success in the client. Backend state is authoritative.

## Product invariants relevant to frontend

- EUR is canonical; Chargily displays a server-calculated DZD conversion from EUR.
- The sender proposes first, and boost cannot bypass compatibility.
- Exact locations remain hidden until the deal is funded.
- The traveler cannot retrieve the delivery code; it stays locked for 30 minutes after pickup.
- Payout protection is 48 hours, and a dispute freezes payout.
- Kaba/ProductRequest is not active in V1.

After meaningful work, update `docs/IMPLEMENTATION_STATUS.md`; it tracks progress but never replaces the specification.
