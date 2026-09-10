# Phase 8F-H4.1 — DZD payout Finance/Admin UX

Starting main: `6d8b8146fbf0913cd0d93b9d4cb1a7c6bce0b7d2` in `is-bo/shiptripis`.

H4 built the manual DZD rail. H4.1 changes only how a Finance operator reads and
drives it. No financial logic, model, migration, permission or provider path was
touched, and no control was added that the H4 domain would not already accept.
Every command still goes to `apps.finance.payout_manual` and is re-checked inside
that transaction; the screen's job is to make sure the operator knows what they
are about to do before they do it.

## Where the presentation lives

`apps/admin_panel/console_manual_presenter.py` is new and is the only thing that
decides how this rail reads. It is pure and read-only: it takes a `Payout` and an
operator and returns state labels, blockers, steps, masked destination, receipt
history and a timeline. Keeping it in `admin_panel` rather than in `finance` means
the H4 API contract in `payout_manual_api.projection` is unchanged — the console
and the API no longer share a projection, so a presentation change cannot alter an
API response.

## What the screen says

**The amount.** DZD is the dominant figure, because it is the number retyped into
a bank. Beside it, labelled *canonical*, sit the EUR obligation and the exchange
rate frozen at funding. Nothing is computed in the browser: both figures come from
the server's snapshot, and there is no editable FX, amount or destination control
anywhere on the page. Copying the amount yields the bare digits (`15600`) because a
bank amount field rejects a thousands separator, and a rejected paste sends the
operator back to typing; the page says so where the button is.

**The destination.** Masked at rest — last four of the CCP and the RIP, and the
two-digit CCP key masked whole, since any part of two digits is the key. The full
values exist only inside an explicit *Reveal payout details* action: a POST, never
rendered on a GET, `no-store`, audited by H4's existing `payout_profile.revealed`
record, and cleared from the page after five minutes with a *Hide details* control
for sooner. Each revealed field has its own copy button; the confirmation says
"Copied" and the live region names the field. No value is ever written into a
message, a URL, an event, an attribute or a log.

**Version binding.** The screen states that the destination was locked when the
shipment was funded and names the payout-method version. Where the Traveler has
since replaced their details, that is reported as context — *applies to future
payouts only* — and the newer account's mask is not shown, so there is nothing on
the page that could be mistaken for an alternative destination.

**The two documents.** The Traveler's crossed cheque and Finance's transfer receipt
are separate sections with separate wording, never merged. Both carry their
approved label verbatim in French, Arabic and English, the Arabic set `lang="ar"`
and `dir="rtl"` so it renders right-to-left inside the LTR console. The exact
strings are `apps.finance.payout_evidence.CHEQUE_LABELS` and the new
`RECEIPT_LABELS`; the receipt upload API now echoes its own set rather than the
cheque's. NIP appears nowhere.

- Cheque — FR **Photo du chèque barré complet** · AR **صورة كاملة لشيك مُسطَّر** ·
  EN **Photo of the full crossed cheque**
- Receipt — FR **Reçu du virement** · AR **إيصال التحويل** · EN **Transfer receipt**

**Evidence viewing.** `admin_console:payout-evidence` is a new session-authenticated
GET that decrypts through H4's `read_evidence`, so every open is audited. It resolves
only evidence belonging to *this* payout — the frozen profile's cheque, or a receipt
on one of this payout's own attempts — and 404s anything else regardless of
capability. It is `no-store`, `nosniff`, `no-referrer`, and no storage URL is ever
emitted. The trigger is a real link, so it works with scripting off; with scripting
on it opens a `<dialog>` lightbox that fetches the image only when opened and clears
it on every close path.

**The instruction.** Five numbered steps in the order a person performs them, with
the current one marked, stated so that ShipTrip is never the party sending money:
step three happens in a banking application, outside this system. Claim ownership is
explicit — *Available for processing*, *You are processing this*, or *Being processed
by …* with an instruction not to send a second transfer. Releasing a claim is offered
only before commitment and only to its owner, and the page says a committed
instruction can only be resolved through a recovery hold.

**Sent is not paid.** *Processing* means Finance is performing the transfer,
*Transfer sent* means an operator attested it and attached a receipt, and *Paid*
means ShipTrip's settlement completed against the ledger. Three labels, three tones,
three sentences. There is no "Mark paid" on this rail and no control that reaches
`sent` or `paid` without a receipt and an explicit attestation. The legacy
one-click manual-evidence form on `finance_detail.html` is now additionally refused
for any DZD payout, so a payout on this rail cannot fall back to it.

**Blockers.** A protection window, a dispute, a Finance hold, an unreviewed profile,
unsettled funding, a missing balance order and the global DZD execution flag are each
named at the top of the page with the machine code beside them, and the actions they
would refuse are absent rather than merely rejected. A held payout is stored as
`eligible`; the chip says *On hold*, because a queue that calls it ready is telling an
operator to go and send money the same page will refuse.

**Refusals.** Known domain refusals are mapped to a sentence that says what to do —
already claimed, stale revision, committed, storage unavailable, invalid receipt,
duplicate settlement — prefixed with which command was refused. No stack trace,
provider detail or exception repr reaches the page.

**Timeline.** The same H4 audit events, read as operational history: what happened,
what it meant, when, and which safe actor did it. No encrypted or sensitive content.

**The queue.** The payouts list now carries the payout reference, the rail, the
canonical EUR obligation with the DZD settlement figure beneath it, the state, and a
*Waiting on* column that emphasises the rows a person has to act on. Open holds — the
payout's and the Deal's — are counted in one annotated query rather than per row. No
account data, masked or otherwise, appears in a list.

## Accessibility, theme and size

Semantic buttons and links throughout, a visible 3px focus ring on every control,
`showModal` for the lightbox's focus trap and Escape, distinct accessible names on
every copy control, status carried by text as well as colour, and an `aria-live`
region for copy confirmations. Both themes come from the existing token set; no
colour is hard-coded. At 375px there is no horizontal overflow, the amount, the
revealed values, the steps and the blocker list restack, and the receipt table
scrolls inside its own container.

## Verification

Eleven H4.1 console tests cover the wording and the three languages, masked-by-
default and audited reveal, evidence scoped to its own payout, Finance/Super only
with Support/Ops/Trust refused on the screen and the evidence route, a hold naming
itself and removing the controls, a claim visible to the operator who does not own
it, sent-versus-paid, append-only receipt revisions, frozen-version binding, a named
refusal, and the queue's settlement figure. One H4 assertion was updated for the
renamed claim control; its intent is unchanged.

Visual QA ran against locally rendered pages from real PostgreSQL fixtures in all
seven required states, in both themes and at 375px, with synthetic data only. Two
defects were found and fixed there: a held payout still labelled *Ready for payout*,
and a duplicated profile-review blocker. One JavaScript defect was found and fixed —
this Chromium build fires neither `close` nor `cancel` for a programmatic
`dialog.close()`, so an Escape-dismissed lightbox kept the decrypted document loaded;
the clearing now also runs from an attribute observer, which no close path can skip.

No money moved. No provider call, no Stripe object, no Chargily object, no real DZD
transfer, and no LIVE operation is involved in any of this work.
