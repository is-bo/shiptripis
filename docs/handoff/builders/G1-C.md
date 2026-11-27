# Brief G1-C: one gate, and screens that follow it

**Builder:** Claude Opus, extra-high effort.
**Branch:** `claude/g1-guest-checkout-csrf`, pull request #67. You start from G1-B's pushed,
green head. Pull first. You are the last brief on the branch, so you also finish the pull
request.
**Read first:** `CLAUDE.md`, the mobile rules included; `docs/handoff/builders/README.md`; the
plan sections 3, 4 (rules R6 and R9) and 5.2 and the G1 rows of Appendix A;
`docs/handoff/status/G1.md` as G1-B left it; `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md`.

## 1. Your job

Close rule G-F: screens offer exactly what the gate allows. Two statements of one rule become one
pure function, and the two phone screens stop showing an older answer over a newer one.

## 2. What you build

**G-F1. One gate function** (`backend/monolith/apps/finance/services.py`: `_checkout_step`,
`_hands_back`, `next_checkout`; `views.py`; `guest_web.py`). `checkout_gate(facts)` is a pure
function. The facts are: the order (collectable, amount outstanding), its attempts, the caller
(the owner, or a guest link and what it may do), the rail asked for and the rails available, the
amount, and the time.

- `_checkout_step` builds the facts under the order lock and acts on the answer.
- The read path builds the same kind of facts without the lock and maps the answer to a screen
  state. No condition is stated twice. G1-A's held-payment check lives in the function.
- Owner states: ready, resumable (with its rail), settling, guest paying, in progress, under
  review.
- Guest states: ready, in progress, paid, inactive. "In progress" is one neutral message for
  every case where the guest must wait or must not pay again. It never says who is paying.
- For the same facts and the same time, the gate and the read path agree. A screen cannot predict
  a later webhook, and a refusal after an older read is not a disagreement.
- The payout preflight is not part of the function. Leave it where it is (C1).

**G-F2. On the phone, one owner per order** (`mobile/lib/features/requests/checkout_section.dart`,
`mobile/lib/features/guest/guest_pay_screen.dart`, `guest_payment_sheet.dart`). Plan rule R9: the
checkout state of an order is read by one Riverpod provider and by nothing else. Every tap
outcome (accepted, refused, an error) invalidates that provider, so it reads again. No screen
sets the state from the answer of another call. Build no helper class for this.
**[Guess]** A rebuilt provider drops the result of its earlier build. Prove it with the test
"two reads answered in reverse order". If it does not hold, keep one request counter inside that
provider and accept only the newest. Say which you used.

**The "under review" state on screen.** The owner's section and the guest page show G1-A's
state: a payment for this order is being checked, do not pay again. No surface says "nothing was
charged" for a held payment: not the app, not the guest web page.

## 3. What you remove

The conditions restated in `next_checkout`. Any screen logic that decides by itself what the
server would accept.

## 4. What is not yours

Money rules and dispositions (G1-A) and jobs (G1-B). If the gate needs a fact they do not expose,
add the read, not a second rule. The rails against the payout preflight (C1). The guest page's
capability rules (closed family G-A).

## 5. Tests

Red first: the round-7 should-fix "an older successful read re-enables a refused action", on
both phone screens.

- **Property, on the server:** for every state of G1-A's table, what the read path offers the
  owner and the guest equals what the gate accepts for the same facts and time.
- **The four surfaces** (owner detail, deposit summary, guest web page, guest screen in the app):
  each owner state and each guest state draws its own message; a paid order; a cancelled order.
- **On the phone:** a refused tap followed by an older read; two reads answered in reverse
  order; a failed refresh keeps the last good state and says so.

## 6. Done when

1. The finding is a test, red before and green after, and every case of section 5 passes.
2. New strings exist in English, French and Arabic. Screenshots in English and Arabic at 360 px:
   the "being checked" state on the owner section and on the guest screen, and the staff form of
   G1-A.
3. The pull request description lists, per rule (G-D, G-E, G-F): the rule, where its one
   mechanism lives, its tests, and the evidence table of all three briefs.
4. The phase document and the status entry are written (README rule 12).
5. Every CI check is green.
