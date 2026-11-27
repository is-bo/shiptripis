<!-- claude-projects-attribution: {"github_login":"is-bo"} -->
_Requested by **Ismail** · [project thread](https://claude.ai/code/project/chan_01RarBx7U8quQjusLrHDb17n?thread=cmsg_01RarBx7U8quQjusLrHDb17nM2fqq9YggmNc7nMmiURxfL)_

Package **G1** of `docs/WASSLA_PHONE_TEST_2_PLAN.md` (section 4), from finding 1.1. Builder: Claude Opus, extra high. Server (`apps/finance`, `templates/payments`), plus, from the second pass, one line of `config/settings/base.py` and the two Caddy files in `infra/vps`. From the fourth pass: migration `finance 0036` (three columns on the payment attempt, schema contract regenerated) and the app (one error code and two strings on the owner's payment screen and the guest pay screen). From the fifth pass: the owner's screen waiting on a settling payment. From the sixth pass: a fourth column, `checkout_final_at`, and a partial index in `0036` (the fifth pass's job kind is gone again), and the owner and guest screens follow the server's `checkout_state`. No Go, no switch. Strings in English, French and Arabic. Nothing deployed.

## The bug

The shared payment shell sets `<meta name="referrer" content="no-referrer">` so the token in the URL never travels onward. With it, Chromium submits the guest page's same-origin HTTPS form with `Origin: null` and no Referer. Django's CSRF middleware refuses both, so pressing "Pay" on a shared link answered "CSRF verification failed". The new tests reproduce both refusals on `main` with Django's own log lines: "Origin checking failed - null does not match any trusted origins" and "Referer checking failed - no Referer".

## What changed

- **`guest_payment_page` alone is exempt from Django's CSRF check** (`@csrf_exempt`), and `templates/payments/guest.html` no longer renders `{% csrf_token %}`. The link token in the path is the authority. The view never reads the session, so a signed-in member pays as a guest. No trusted origin added, `Origin: null` trusted nowhere else.
- **No referrer, no cache.** `GuestPagePrivacyMiddleware`, first in `MIDDLEWARE` and acting only under `/pay/guest/`, sets `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store` on every guest page response: 200, 302, 400, 404, 405, 409, 429, 503 and Django's own 500. The shell keeps its meta tag.
- **Checkout reads the link again under the order lock.** `start_checkout` calls `_recheck_guest_link` right after `_order_for_update`. It reads the link `FOR NO KEY UPDATE`, filtered by its id **and this order**, and refuses with the uniform `GuestLinkInvalid` unless the link is still payable. The attempt is bound to that locked row. `_guest_link_payable` is the one validity rule, used by both `resolve_guest_link` and the locked re-read.
- **Second to sixth passes** (below): neither proxy logs a request URI or Referer, and both send the private headers on errors they answer themselves; the guest throttle ignores sessions; a guest is never handed an open checkout; a checkout whose request died is recovered under its own key with its frozen request; no order history carries a checkout URL. Since the sixth pass: a provider event binds only to the attempt that stored the id it names; a checkout is live until its provider confirms it can take no payment, whatever its attempt's status; one routine settles a checkout and one durable job follows each live checkout to its end, re-armed by the job loop; no checkout is handed out or opened while another of the order's is live; the screens offer only what the server says the next tap meets.
- Unchanged: GET has no side effects, the uniform dead-link page, the already-paid page, `actor_id=None`, amounts, provider idempotency, and webhook-only settlement.

### Lock and recheck design

Revoking (`revoke_guest_link`) and replacing (`create_guest_link`) lock the order row, then the live link. `start_checkout` does the same: order, then link, then the open attempt. Payment success locks the order aggregate first. Every path takes the order lock first, so no new lock-order edge is added. Provider calls (create, close, recover) run between the locked steps, never under a lock. With the order lock held, the re-read is final:

- a stop that committed before the lock is refused (`guest_link_invalid`, no attempt, uniform page);
- a stop that comes after finds the open guest checkout and is refused itself (`guest_checkout_in_progress`, unchanged);
- expiry, use or a closed order between the two reads is refused in the same words;
- a link paired with another order finds no row and is refused.

The app's JSON guest checkout calls the same `start_checkout`, so it gets the recheck as well. The only change it can show is in a race: an order that closes between the read and the lock now answers `guest_link_invalid` (404), which is what `resolve_guest_link` already promises for every dead link.

## Second-pass review (Astra 6.2 rejected `4337d9c`; all five findings accepted and fixed)

Rows 4 and 5 were reworked in the third pass (next section).

| # | Finding | Outcome |
| --- | --- | --- |
| 1 (blocker) | Caddy's error logger wrote a guest token (request URI, Referer) for a failed proxy call, e.g. a 502 while the app is down. | **Fixed** with a regex filter, replaced in the third pass (A) by dropping both fields. |
| 2 | A framework-built 500 skipped the private headers. | **Fixed.** `GuestPagePrivacyMiddleware`, first in `MIDDLEWARE`, replaces the view decorator. `test_a_server_error_on_the_page_is_private_too`. |
| 3 | A signed-in session lifted the guest throttle. | **Fixed.** `GuestPaymentThrottle.get_cache_key` keys by client address whatever `request.user` is. `test_a_session_does_not_lift_the_guest_bound`. |
| 4 | A second holder with another receipt address overwrote the open session's address and was handed its URL. | **Fixed**, then reworked in the third pass (D): no guest is handed an open checkout at all. |
| 5 | A matching request superseded an attempt whose provider call was still out. | **Fixed**, then reworked in the third and fourth passes (B, C, and the claim column). |

## Third-pass review (Astra 6.2 rejected `f1fe565`; all six findings accepted and fixed in `bff55e2`)

Astra's review of `d99c838` found A, D, E and F fixed and B and C partly fixed; the fourth pass finishes B and C.

| # | Finding | Outcome |
| --- | --- | --- |
| A (blocker) | An encoded route prefix (`/pay%2Fguest/…`) defeated the log regex. | **Fixed as the lead asked: no regex.** Both Caddyfiles drop `request>uri` and `request>headers>Referer` from every log entry; handled errors (F) are kept in a DEBUG-level `proxy_errors` log with the same fields dropped. `test_proxy_logs.py`: 8 paths (plain and encoded) × 2 Referers per proxy, no URI, no Referer, no 8-character run of the token anywhere in the output. Real Caddy 2.10.0 and 2.8.4. |
| B (blocker) | The guest's retry superseded the owner's attempt locally while the owner's URL stayed payable. | **Fixed** for checkout in the third pass (`close_checkout` per rail; supersede only once the provider confirms), and for expiry, reconciliation and recovery races in the fourth pass. |
| C | A worker dying after Stripe created the session led to a second session under a fresh key. | **Fixed** in the third pass (recovery under the same key), finished in the fourth (frozen request, lost create answer kept, claim column). |
| D | The address check let a link holder confirm the first payer's receipt address. | **Fixed.** A guest is never handed an open checkout, so the answer never depends on the address. |
| E | With receipts off, JSON kept an optional email the browser never sends. | **Fixed** at the shared boundary; the fourth pass also keeps the webhook from putting one back. |
| F | Proxy-generated 502s lacked the private headers. | **Fixed.** `handle_errors` in both Caddyfiles sets `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store`. |

## Fourth-pass review (Astra 6.2 rejected `d99c838`; all nine findings accepted and fixed in `0b088be`)

`0b088be` is one commit on top of the reviewed head `d99c838`; `1643afc` only records the local suite results in the write-up. `main` had only docs since, so it is not merged in. No force-push.

**The rule now.** Three columns on the attempt carry what the third pass kept in memory or read from `updated_at` (migration `0036`):

- `checkout_request`: the create request, frozen when the attempt is written. The first call and every recovery send exactly it.
- `opening_until`: the claim. The request that creates an attempt owns it for two minutes; a request that recovers it claims it the same way.
- `close_requested_at`: set under the order lock before a provider is asked to close the checkout. From then on it is handed to no one, its own payer included, and any request may finish the close.

| The open attempt | What the caller gets |
| --- | --- |
| Settling (`processing`) | `CheckoutInProgress`, nothing touched |
| A checkout stored, closed by its provider in this request | replaced |
| A checkout stored, opened by this member, same rail and amount, not lapsed, no close requested | handed back |
| A checkout stored, anything else | close recorded, then closed at its provider; replaced only once it confirms, else `CheckoutInProgress` |
| No checkout stored, claim live | `CheckoutInProgress` |
| No checkout stored, claim lapsed, Stripe or mock, under 10 minutes old | claimed, recovered with its frozen request, looked at again |
| No checkout stored, recovery refused while this claim still owns it, too old, or Chargily | replaced: its URL never left the server |

A checkout URL leaves the server only in the answer of a checkout call (owner JSON, guest JSON, guest page redirect), and only after it is stored on an open attempt.

| # | Finding | Outcome |
| --- | --- | --- |
| 1 (blocker) | The expiry job expired an attempt on the local clock while its Stripe session stayed payable, even a `processing` one. | **Fixed.** `expire_checkout_attempt`: settling is left alone; a checkout is closed at its provider with no lock held, and the attempt expires only once the provider confirms; collecting is left to its payment; anything else is retried. The order stays reserved meanwhile. |
| 2 (blocker) | Reconciliation replayed a create on an ended attempt, recovery stored its URL, and order history showed every attempt's URL. | **Fixed.** The reconcile job and the staff action never repeat a create (`checkout_never_handed_out`). Recovery stores only on an attempt still waiting, and closes the checkout otherwise. `PaymentAttemptSerializer` has no `checkout_url`; only the checkout answer (`CheckoutAttemptSerializer`) does. The app's "Continue your payment" asks the checkout endpoint again. |
| 3 (blocker) | A refused recovery could drop a checkout stored meanwhile; the job bypassed the claim; Stripe's "key in use" read as a refusal. | **Fixed.** A stored checkout is always examined first; abandoning needs the same claim to still own a handleless attempt; the job no longer recovers; Stripe's 409 and `idempotency_key_in_use` are `ProviderUnavailable`. |
| 4 | A create whose answer was lost failed the attempt. | **Fixed.** The attempt keeps its key and the next tap recovers it; recovery is tried for 10 minutes. |
| 5 | Recovery rebuilt callback URLs from current settings. | **Fixed.** The frozen `checkout_request`. The mock now refuses a reused key with other parameters, as Stripe does. |
| 6 | A close confirmed by a request that then died was forgotten. | **Fixed.** `close_requested_at`, written before the provider call. |
| 7 | With receipts off, a signed completion put an address back and queued a receipt. | **Fixed.** Reconciliation replaces only an address given at checkout. |
| 8 | The app showed a generic failure for `checkout_in_progress`. | **Fixed.** "A payment is already under way" on both app surfaces, in three languages; a settling payment no longer offers "Continue". |
| 9 | The two-tap test accepted any second redirect; the mock closed a processing checkout. | **Fixed.** Distinct redirects, one per attempt, each replaced attempt closed; the mock answers "collected" for a processing checkout. |

**Money.** No amount, fee, currency or settlement change. Settlement still comes only from the signed webhook or provider reconciliation. What changes is which checkout may still collect, and that the order stays reserved while its checkout might.

## Fifth-pass review (Astra 6.2 rejected `1643afc`; two blockers and eight should-fix findings accepted and fixed in `a0b48be`)

`a0b48be` is one commit on top of the reviewed head `1643afc`. `main` had only docs since, so it is not merged in. No force-push.

| # | Finding | Outcome |
| --- | --- | --- |
| 1 (blocker) | A late `checkout.session.expired` from an abandoned checkout matched the order's newest handleless attempt and expired it after its URL was handed out. | **Fixed.** Every checkout carries its attempt id in its metadata (Stripe, Chargily, mock) and the parsers return it. Events bind by checkout id, then payment id, then that attempt id, and only to an attempt without a checkout on the order the event names; the order-only fallback is gone. Under the lock, `reconcile_attempt` ignores an event about another checkout than the one stored; a success of that kind raises and is kept for a human. |
| 2 (blocker) | Order cancellation and closure to collection bulk-cancelled attempts without closing their checkouts. | **Fixed.** `_stop_collecting_attempts` ends each open attempt under the order lock, records the close intent and schedules a durable `checkout_close` job (new kind, migration `0036`) that closes the checkout at its provider after commit and retries until it confirms. A settling payment is left to its own outcome; a success on a cancelled order lands unapplied and is refunded, as before. |
| 3 | A failed delayed Stripe payment stayed "processing" forever. | **Fixed.** The session is fetched with its payment intent; `requires_payment_method` or `canceled` is failed, anything else still processing. |
| 4 | Close work stopped after eight tries. | **Fixed.** The expiry and close jobs get 32 runs, about six days with the capped backoff; an exhausted job is logged at error level and can be retried by staff. |
| 5 | With receipts off, the stored event kept the payer's address. | **Fixed.** The normalised event keeps an address only for an attempt opened with one; Stripe's scrubber drops `customer_email`. |
| 6 | The technical admin showed the hosted URL and the frozen request. | **Fixed.** `PaymentAttemptAdmin` lists an explicit field set without them. |
| 7 | A recovery refused for credentials abandoned the key. | **Fixed.** Unreachable, not configured or misconfigured keeps the attempt and key and answers `CheckoutInProgress`. |
| 8 | The claim was dated before the lock wait. | **Fixed.** The clock is read once the locks are held. |
| 9 | An attempt could outlive its provider's checkout. | **Fixed.** The provider's stated expiry (Stripe `expires_at`) moves the attempt's expiry earlier and reschedules its jobs; reuse is refused past it. |
| 10 | A settling owner payment offered Pay. | **Fixed.** The owner screen shows "We're still confirming your payment" with "Check again", no rail choice. |

**Money.** No amount, fee, currency or settlement change. What changes is which attempt a provider event may touch, and that a cancelled order's checkouts are closed at the provider.

## Sixth-pass review (Astra 6.2 rejected `a0b48be`; three blockers and seven should-fix findings accepted and fixed in `4e4c0ea`)

`4e4c0ea` is one commit on top of the reviewed head `a0b48be`. `main` had only docs since, so it is not merged in. No force-push.

**Fixed at the cause.** Every correlation and closing finding since the third pass came from one of two mistakes, patched where each surfaced: events were bound by guesses (order reference, then an attempt id in metadata), and whether a checkout can take money was read from the attempt's status. Both are replaced:

- **Binding:** an event binds only to the attempt that stored the checkout id it names, or the payment id recorded with its success. Nothing else binds it; an event naming nothing we stored is ignored, and a success of that kind is kept for a human. Complete because a checkout's id is stored before its URL leaves the server. The metadata and reference fallbacks, `attempt_reference` and the lock-time `another_checkout` check are removed.
- **Liveness:** `checkout_final_at` (new column, partial index) is set only on a provider's word, an outcome it reported or a close it confirmed. `LIVE_CHECKOUT` is the one definition.
- **One routine, one job:** `settle_checkout` reads the provider, records any outcome through `reconcile_attempt`, and closes a checkout no longer wanted; replacement, expiry, order closure and the settle job (`provider_reconcile`) all use it. The settle job completes only when the checkout is final, defers without spending retries while a payment settles or is being made, and the job loop re-arms one for any live checkout without it (`arm_live_checkouts`), old code's rows included. The fifth pass's `checkout_close` job and `close_ended_checkout` are removed.

| # | Finding | Outcome |
| --- | --- | --- |
| 1 (blocker) | The metadata fallback accepted a missing or invalid order reference; PaymentIntent events skipped the session check. | **Fixed** by the binding rule: no metadata or reference binding at all. A card decline (`payment_intent.payment_failed`) ends nothing. |
| 2 (blocker) | A close that found the checkout collected only logged it; nothing recorded or refunded the payment. | **Fixed.** The provider is read before any close; a collected checkout keeps its settle job, which records the payment once made: unapplied and refunded on a cancelled order. |
| 3 (blocker) | Sessions superseded by old code stayed live after the upgrade. | **Fixed.** Live is the provider's fact, so such a session is settled before the order hands out or opens anything, and the sweep arms a job for it. No data migration. |
| 4 | A Stripe card decline after the session was stored never matched and exhausted its job. | **Fixed.** Ignored: the payer may retry in the same session. |
| 5 | Chargily's 30-minute default lifetime was not stated. | **Fixed.** `expires_at = created_at + 30 min` (`CHECKOUT_LIFETIME`). |
| 6 | Chargily's hosted URL was stored and shown on the provider-event page. | **Fixed.** `url` and `checkout_url` scrubbed before storage (and Stripe's `url`). |
| 7 | Chargily's string `livemode` was isolated as another mode. | **Fixed.** `"true"`/`"false"` become booleans after the signature is verified; anything else is still refused. |
| 8 | A pre-upgrade row with `checkout_request={}` made recovery raise a 500. | **Fixed.** An attempt with no usable frozen request is refused like a provider refusal and replaced; its key is not replayed with rebuilt parameters. |
| 9 | The owner screen offered Continue on a disabled rail and during an opening claim. | **Fixed.** The server's `checkout_state` drives the section: Continue only when the owner's own checkout is handed back on a rail still available; "a payment is under way" with Check again while a checkout opens. |
| 10 | The guest screen kept Pay enabled while settling and after `checkout_in_progress`. | **Fixed.** The guest quote carries a neutral `checkout_state`; the screen shows Check again in place of Pay, and the guest web page says a payment is under way. |

**Money.** No amount, fee, currency or settlement change. What changes is which attempt an event may touch, and that a payment taken through any checkout the server handed out is always recorded: applied, or unapplied and refunded.

## Seventh-pass review (Astra 6.2 rejected `4e4c0ea`; the blocker and seven should-fix findings in scope fixed in `NEWSHORT`)

`NEWSHORT` is one commit on top of the reviewed head `4e4c0ea`. `main` had only docs since, so it is not merged in. No force-push.

**No data from before G1.** The app has never been live (CLAUDE.md: no users, spend nothing on legacy data). Findings that exist only for rows, URLs, events or deadlines left by code before G1 are declared not applicable and nothing is built for them: the stored-payload display, the pre-G1 attempt association, the inherited one-hour Chargily deadline, two URLs issued by old code, inherited conflicts and stored string `livemode` values. G1 added no path that exists only for old rows. The round-6 test about "a checkout old code ended" is renamed to what it tests, an attempt that ended before its provider confirmed the close, with the same assertions.

| # | Finding | Outcome |
| --- | --- | --- |
| Blocker 2 | A success with an unverifiable or mismatched amount made the checkout final, and neither the settle job nor staff reconciliation read the provider again, so the payment could never be applied or refunded. | **Fixed.** "Can still collect" and "payment accounted for" are two facts. While a reported payment is unaccounted for (`UNVERIFIED_PAYMENT`, also the attention queue's rule), its settle job and the staff action read the provider; only a verified answer applies it, with the amount and currency checks unchanged. The job retries with backoff, is not archived while the payment is open, and stops on a staff resolution. |
| Should-fix | A close asked for while the settle job ran was deferred until expiry. | **Fixed.** A request during a run sets the job's next time (under the job's row lock, never earlier than now), which the run's own deferral or retry keeps; the settle routine re-reads the attempt after the provider call. |
| Should-fix | Chargily `processing` was ignored, and a confirmed collecting checkout read as ready. | **Fixed.** Both are recorded as settling, so the gate, expiry and screens wait; a payable checkout on an ended attempt is also shown as under way. |
| Should-fix | Revoking a guest link left its ended attempt's checkout payable. | **Fixed.** The guard counts any payable checkout opened through the link. |
| Should-fix | Continue could not open from a deposit summary and stayed after its rail was refused. | **Fixed.** The order names the rail Continue opens (`resume_provider`); a refused rail re-reads the order. |
| Should-fix | A guest tap that found the payment made showed an inactive link. | **Fixed.** It shows the paid page, as reopening the link does. |
| Should-fix | Chargily's `livemode` accepted case and padding variants. | **Fixed.** Only the exact `"true"` and `"false"` are read. |
| Nit | The decline test lost its `card_declined` assertion. | **Fixed.** Restored. |

Replay also binds again by the stored ids on every run instead of reading the association stored with the event.

**Money.** No amount, fee, currency or settlement change. A payment whose amount could not be accepted now stays in front of staff and is read until it is accounted for.

## Done when

| Done when | Evidence |
| --- | --- |
| A fresh valid guest link reaches hosted test checkout through the public HTTPS flow even with cookies unavailable. | `BrowserCheckoutTests.test_a_fresh_payer_without_cookies_reaches_hosted_checkout`: over HTTPS with `Origin: null` and no Referer, with CSRF enforced, the page sets no cookie and renders no CSRF token. The tap gets a 302 to the hosted test checkout, the browser never holds a cookie, and the attempt has no payer, carries the link and charges the server's amount. `test_a_submission_with_neither_origin_nor_referer_is_accepted` covers the case with neither header. The rewritten j2 `test_the_shared_page_hands_the_payer_to_the_provider` also passes. The real-phone check is O2, after an approved deployment (not done here). |
| A stale or invalid capability cannot start a payment. Amount, actor and order remain server-owned, and sensitive link data stays out of references, logs and outbound navigation. | **Stale or invalid links:** `test_a_dead_link_starts_nothing_however_the_browser_submits`; `test_a_link_stopped_while_the_payer_taps_starts_no_payment`; `CheckoutRecheckTests` (9); `GuestPageRaceTests.test_a_revocation_committing_while_the_payer_taps_stops_the_payment` (real threads). **Server-owned values:** `test_fields_the_payer_adds_cannot_steer_the_payment` (20 forged fields change nothing); `test_a_signed_in_member_pays_as_a_guest_and_gains_nothing`; one checkout that can collect per order on every path, order cancellation included (third to fifth passes). **Sensitive data:** `test_the_token_stays_out_of_the_provider_logs_and_navigation`; `test_every_guest_response_is_private_and_sends_no_referrer` and the 500 test; `test_proxy_logs.py`; `test_no_order_history_carries_a_checkout_url`. |

## Tests

All page submissions go through `Client(enforce_csrf_checks=True)` over HTTPS, posted as Chromium posts them under the shell, unless a test says otherwise.

- `test_j7c_guest_link_ux.py`, `BrowserCheckoutTests` (19).
- `test_guest_payment.py`: `CheckoutRecheckTests` (9) and `OpenCheckoutTests` (26 after the fourth pass).
- `test_stripe.py` `StripeCloseCheckoutTests` (5) and `test_a_key_still_in_use_is_retryable_not_a_refusal`; `test_chargily.py` `ChargilyCloseCheckoutTests` (4).
- `test_recovery.py` `test_expiry_closes_its_checkout_outside_any_transaction` (real transactions).
- `test_concurrency.py` (PostgreSQL, real threads): `GuestPageRaceTests` (4) and `CheckoutRaceTests.test_two_simultaneous_checkouts_leave_exactly_one_open_attempt`.
- `infra/vps/tests/test_proxy_logs.py` (2).
- App: `phase_j7d_payment_result_test.dart` (`continuing asks the server, which hands the checkout back`, `a payment already under way is waited for, not opened`) and `guest_pay_test.dart` (`a payment already under way is waited for, in words`).
- Fifth pass: `OpenCheckoutTests` (35 now: the late abandoned-checkout event, the event bound before its checkout was stored, order cancellation and closure to collection closing the checkout, an order closed while a checkout opens, a settling payment outliving its order's cancellation, recovery refused for credentials, the claim's full window, the provider's own expiry, receipts off on the stored event); `TechnicalRecordsTests` (the technical attempt page); `test_stripe.py` `StripeReconcileTests` (3), `test_a_checkout_reports_when_stripe_stops_it_collecting`, `test_an_event_names_the_attempt_its_checkout_was_opened_for`; Chargily's paid-event test carries the attempt id. App: `phase_j7c_guest_payer_test.dart` `the Sender / a guest paying by a delayed method is waited for, not offered Pay`.

- Sixth pass: `OpenCheckoutTests` gains the checkout old code ended (cancelled and expired), the job loop's sweep, a settle job re-armed after running out, a cancelled order's collected payment refunded, a payment being made followed to its end, an unusable frozen request replaced, and the three `checkout_state` tests (owner, every screen, guest with the web page); `test_stripe.py` `test_a_declined_card_and_a_session_never_stored_bind_to_nothing` (endpoint); `test_chargily.py` the stated expiry (2), the published webhook shape with mode enforcement and no URL kept, and an unknown `livemode`. App: `an open checkout on a rail switched off is not continued`, `a checkout being opened is waited for, not continued`, `the Sender's own open checkout is continued`, `a link opened while its payment is settling offers no Pay`.

- Seventh pass: `OpenCheckoutTests` gains an unverifiable success read until accounted for, staff reconciliation reading the provider for it, a run-out settle job on it not archived, a staff resolution ending the reads, a close asked for during the settle job's run (also dated before its claim), a cancellation during the provider's answer, a payable checkout on an ended attempt waited for on every screen, a link whose ended attempt can still be paid not revoked, a guest tap that finds the payment made, and the rail Continue opens; `test_chargily.py` the exact mode literals and Chargily's `processing`. App: `a summary with no history continues on the rail it names`, `a rail refused while the screen is open is not offered again`.

Each fourth-pass test fails with its fix removed (10 server mutations, 2 app mutations). Each fifth-pass test fails with its fix removed (14 server mutations, one app mutation that fails both delayed-method tests). Each sixth-pass test fails with its fix removed (16 server mutations). Each seventh-pass test fails with its fix removed (16 server mutations, 2 app).

**Rewritten tests** (CLAUDE.md: a test of a changed rule is rewritten). First round: page submissions in j7c `ReceiptEmailTests` and `PublicPageTests`, and j2 `test_the_shared_page_hands_the_payer_to_the_provider`, now submit through the CSRF-enforcing browser shape, no assertion removed. Second pass: the two-tap and simultaneous-checkout races assert one provider session and skip no row. Third pass (they encoded the reuse of an open guest checkout or the address refusal, which D removes): the second-tap and second-holder page tests, the two-tap and held-provider races, the owner tap in `test_a_signed_in_member_pays_as_a_guest_and_gains_nothing`, and the two waiting-page tests. The guest email tests in `test_phase6c_email_events.py` run with transactional email on (E). Fourth pass: `age_past_the_opening_window` and the j7c owner race lapse the claim column instead of ageing `updated_at`; in `test_a_lost_checkout_that_cannot_be_recovered` an unreachable provider releases the claim, so the next tap tries the same key at once (finding 4); the j7d "return from the provider" fixture has no URL in order history, as the server no longer sends one (finding 2). The two-tap race is stricter, not looser. Fifth pass: the Chargily create test expects the attempt id in the checkout's metadata (finding 1); the app test `payment screen refreshes from captured and failed events` opened on the Sender's own settling payment and expected the rail choice, and now expects the "still confirming" notice and no rail choice (finding 10), then runs the captured and failed events as before. No assertion was removed or loosened. Sixth pass (the full list is in the write-up): the Stripe `test_a_failed_payment_intent_is_reported_as_failed` is now `test_a_declined_card_ends_nothing`; the fifth pass's metadata-binding tests go with the binding they tested, and the Chargily tests return to their fourth-pass form; the event-binding tests now expect an event naming an unstored checkout to bind to nothing; a payment taken before its webhook is now recorded by the next tap (and a settling one marked settling); the order-closure tests follow the settle job instead of `checkout_close`; the guest quote's key allowlist (three tests) includes `checkout_state`; the app's `a payment already under way is waited for, in words` now expects Check again instead of Pay, and the app fixtures carry the server's `checkout_state`. Seventh pass: `test_a_payment_being_made_holds_off_expiry_and_is_followed_to_its_end` now expects the attempt recorded as settling (expiry answers `attempt_settling`, was `attempt_collecting`) and also asserts what the owner and guest are told; the Stripe decline test gets its `card_declined` assertion back; the j7c and j7d app fixtures carry `resume_provider`. No assertion about money, funding or what a payer is handed was removed or loosened.

## Screenshots (360 px)

`docs/screenshots/g1/`. Web page: the HTML is the real view's, rendered through Django's test client with transactional email on. App: widget tests with the app's fonts at 360 × 760. No state scrolls horizontally; Arabic is right to left.

| State | English | Arabic |
| --- | --- | --- |
| Guest page | `guest-page-en.png` | `guest-page-ar.png` |
| Validation (invalid receipt address) | `guest-validation-en.png` | `guest-validation-ar.png` |
| Completion (link reopened after payment) | `guest-completed-en.png` | `guest-completed-ar.png` |
| Guest page: a payment is already under way | `guest-in-progress-en.png` | `guest-in-progress-ar.png` |
| App, owner's payment screen: a payment is already under way (fourth pass) | `app-owner-in-progress-en.png` | `app-owner-in-progress-ar.png` |
| App, guest pay screen: a payment is already under way (fourth pass) | `app-guest-in-progress-en.png` | `app-guest-in-progress-ar.png` |
| App, owner's payment screen: a payment still settling (fifth pass) | `app-owner-settling-en.png` | `app-owner-settling-ar.png` |
| App, owner's payment screen: a checkout being opened (sixth pass) | `app-owner-opening-en.png` | `app-owner-opening-ar.png` |
| App, guest pay screen: Check again in place of Pay (sixth pass) | `app-guest-check-again-en.png` | `app-guest-check-again-ar.png` |

## Checks

CHECKS7

After the sixth pass, on Linux against PostgreSQL 16 and Redis 7 with CI's settings: `ruff check .` clean; `makemigrations --check --dry-run` no changes; `build_helper_instructions --check` up to date; schema contract regenerated (the new column and its partial index, nothing else). The 26 files on the changed paths (guest payment, Stripe, Chargily, recovery, the three concurrency files, lock order, webhooks, adapter, contracts, provider currency and HTTP, j2 guest payer, j7c, j7d, invariants, jobs and payouts, operations, posting deposit, protection, worker snapshot, admin console, the two marketplace switch files): 668 passed, 0 failed, after the j2 guest payer allowlist was given the new key. Each of the 16 server fixes, reverted alone, fails its tests. App: `dart format` and `flutter analyze --fatal-infos` clean; the seven touched test files 223 passed. CI on `4e4c0ea`: all 11 checks green, Schema drift and the four Django shards included.

After the fifth pass, on Linux against PostgreSQL 16 and Redis 7 with CI's settings: `ruff check .` clean; `makemigrations --check --dry-run` no changes; `build_helper_instructions --check` up to date; the job kind added to `0036` changes choices only and emits no SQL, so the schema contract is unchanged. The finance files on the changed paths (guest payment, Stripe, Chargily, recovery, the three concurrency files, lock order, webhooks, j7c, j7d, invariants, jobs and payouts): 389 passed, 0 failed. App: `dart format` and `flutter analyze --fatal-infos` clean; the whole `flutter test` suite failed only on the phase 8ff4 test rewritten above, which passes since. CI on `a0b48be`: all 11 checks green, Schema drift and the four Django shards included.

After the fourth pass, on Linux against PostgreSQL 16 and Redis 7 with CI's settings: `ruff check .` clean; `makemigrations --check --dry-run` no changes; schema contract regenerated from a fresh migrate (three new columns, nothing else); whole `apps/finance` and `apps/admin_panel` suites 1,425 passed, 0 failed. App: `dart format` and `flutter analyze --fatal-infos` clean, whole `flutter test` suite 1,671 passed. CI on `1643afc`: all 11 checks green.

Earlier rounds: first round, whole `apps/finance` 1,145 passed; second pass, CI all 11 checks green at `f1fe565`; third pass, 215 passed in the guest, race and provider files and `infra/vps/tests` 38 passed with the real Caddy binary.

## For the gate

- Astra re-review of the seventh pass (`4e4c0ea..NEWSHORT`), under the no-old-data rule: an unaccounted payment kept and read until resolved, a close during a running settle job, the collecting state, and the screens' `next_checkout` with `resume_provider`.
- Deploy note: on its first cycles after a deploy, the sweep arms a settle job for every older checkout not yet confirmed final, and each asks its provider once (test mode on the server today).
- After F1 merges, rerun the integrated finance suite (plan, G1).
- O2 after an approved deployment: a fresh synthetic link through public HTTPS in Android Chrome, an embedded browser, and with a Wassla login open; Stripe test rail.

Phase document: `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md` (second to seventh-pass reviews, handoff). Status entry in `docs/IMPLEMENTATION_STATUS.md`. The board is the lead's.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01BBEhQeGEaYoiHRgC47foGH
