# ShipTrip — visual world

Durable visual decisions for the Flutter V1 client. Implemented in
`mobile/lib/design/`. A screen that needs a colour, size, radius or duration
takes it from there; it never names a value.

## The world

**Mediterranean transit, re-tuned for money.**

The product's existing identity — warm ground, Algerian emerald, Saharan
terracotta, a serif display voice — is kept, because it is the one thing about
this app that is not interchangeable with every other marketplace. What
changes is the job the identity does. The previous build spent its character on
ornament: passport stamps, boarding-pass cards, ticket perforations. V1 spends
it on the two things a user is actually anxious about — *where is my parcel*
and *what happens to my money* — and lets everything else recede.

The governing image is not a passport stamp. It is a **route line with nodes
on it**: Paris → Algiers by air, Algiers → Jijel by road. That line is the
product. It appears as the journey builder, as the leg list, as the delivery
timeline, as the progress indicator on a deal. One motif, earned everywhere.

**Anti-references:** vintage travel scrapbook, airline boarding pass, luggage
tags, passport stamps, distressed textures. Also: the weightless
blue-and-white SaaS default, which is what this becomes if the warmth is
removed.

## Ground and colour

The ground is a warm off-white (`sand1`, `#F8F5EF`) rather than the previous
parchment beige. Beige at that saturation dragged text contrast down and made
every money figure feel like a receipt from 1974. Lifting it keeps the warmth
and clears WCAG AA on body text.

Colour carries meaning, never decoration. Five semantic roles:

| Role | Hue | Means |
|---|---|---|
| `brand` / `success` | Algerian emerald | Primary action, and every terminal-good state: funded, delivered, approved, completed |
| `attention` | Saharan terracotta | **You must do something**: payment required, KYC action needed, proof rejected, recipient missing |
| `waiting` | Amber | Time is passing and nobody is blocked: processing, protection window, awaiting the counterparty |
| `danger` | Rust | Failed, cancelled, disputed, destructive |
| `info` | Lapis | Neutral information, and the flight transport mode |

Terracotta is the scarcest colour in the app. If two things on a screen are
terracotta, one of them is wrong. Emerald doubles as brand and success on
purpose — in this product "the platform worked" and "your delivery is safe"
are the same feeling.

**Status is never colour alone.** Every status carries an icon and a word.
Colour is the third signal, for people who can use it.

Dark is a first-class scheme, not an inversion. Surfaces separate by lightness
rather than by shadow, and the soft state fills become deep tints of the same
hue.

## Type

- **Fraunces** (variable serif) for screen titles and money figures only.
  It is the brand voice and it is rationed — a serif on every label reads
  boutique, not trustworthy.
- **DM Sans** for all UI text in Latin scripts.
- **Noto Sans Arabic** for Arabic, wired through the locale so `ar` gets a face
  designed for it rather than a per-glyph system fallback.
- **JetBrains Mono** for handover codes and reference strings, where a human
  reads digits aloud to another human and `0` must not look like `O`.

All fonts are **bundled as assets**, not fetched at runtime. A sender standing
in a stairwell in Bab Ezzouar on a bad connection should not see a font swap.

Money uses **tabular figures** so amounts align down a column, and money is
never set in a face that renders `€37.50` narrower than `€137.50`.

Sizes map to Material's type-scale roles and scale with the OS font-size
setting. No screen hard-codes a point size and no layout breaks at 200%.

## Structure

- **Bottom navigation bar, docked, four destinations**: Home, Deliveries,
  Chat, Profile. Labelled, because icon-only navigation is ambiguous in French
  and Arabic. Notifications live in the header bell, never as a tab.
- The bar is a solid surface with a hairline top edge. It is **not** a floating
  pill over `extendBody: true` — that construction is the direct cause of the
  overlap bug this rebuild exists to fix.
- One shared inset contract (`NavigationInsetScope` → `AppScaffold`) means no
  screen ever hard-codes bottom padding.
- Each tab owns its own navigator, so back behaviour is per-tab and the system
  Back gesture always works.

## Motion

Short and functional. 160 ms for state, 260 ms for entrance, expressive
ease-out. The only motion that is allowed to be expressive is the delivery
timeline advancing a node — that is the moment the user is waiting for.
Everything honours the platform Reduce Motion setting.

## Money and lifecycle: the two things that must be unmistakable

**Money.** Every amount the user sees is a server value rendered verbatim. The
Dart `Money` type deliberately has no `+` or `-` operator, so a screen
physically cannot compute an authoritative total. Breakdowns always read as
addition toward what the sender pays:

```
Traveler receives    €30.00
ShipTrip fee          €7.50
─────────────────────────────
You pay              €37.50
```

Never `€30 minus 25%`. The traveler's reward is not reduced by commission and
the wording must never imply it is. A credited deposit is shown as a
subtraction from the total, labelled as already paid — never as an extra line
item that looks like a second fee.

**Lifecycle.** A delivery is always shown as a position on its route: what has
happened, what is happening, what is next, and who is waiting on whom. The
user should never have to infer their own next action from a status word.

## Craft floor

Every surface ships its loading, empty, error and offline states. Every
interactive target is at least 48 dp with 8 dp between neighbours. Every icon
that carries meaning has a semantic label. Nothing sits under the navigation
bar, the keyboard, the home indicator, or a display cutout — in either text
direction, at any font scale, on any of the tested device sizes.
