# G1: guest checkout without a browser-session dependency (2026-11-25)

Phone test 2, finding 1.1, and package G1 of `docs/WASSLA_PHONE_TEST_2_PLAN.md` (section 4; builder
Claude Opus, extra high). Server only: `apps/finance` and `templates/payments`, plus, from the second
pass, one line of `config/settings/base.py` and the two Caddy files in `infra/vps`. No migration, no
Go, no Dart, no switch. Three new page strings, in English, French and Arabic. Nothing is deployed
by this change.

## The failure

The owner shared a guest payment link. The page opened; pressing its button answered "Forbidden (403)
CSRF verification failed". The shared payment shell sets `<meta name="referrer" content="no-referrer">`
so the token in the URL never travels onward. With that policy, Chromium submits a same-origin HTTPS
form with `Origin: null` and no Referer. Django's CSRF middleware checks a supplied Origin before the
form token, and `null` fails; with no Origin on HTTPS, the missing Referer fails instead. A valid hidden
token and cookie rescue neither. The new tests reproduce both refusals on `main` exactly as logged:
"Origin checking failed - null does not match any trusted origins" and "Referer checking failed - no
Referer".

## What changed

- **`guest_payment_page` is exempt from Django's CSRF check** (`@csrf_exempt` on that one view), and
  `templates/payments/guest.html` no longer renders `{% csrf_token %}`. Nothing else is exempt: no
  global middleware change, no trusted origin added, `Origin: null` trusted nowhere else.
- **Every guest page response carries `Referrer-Policy: no-referrer` and `Cache-Control: private,
  no-store`**, from `GuestPagePrivacyMiddleware` in `guest_web.py`, first in `MIDDLEWARE` and acting
  only on paths under `/pay/guest/`. So the 200 page, the 302 redirect to the provider, the 400
  validation page, the 404 dead-link page, the 409, 429 and 503 pages, the 405 and Django's own 500
  all carry both. Its header replaces the `SECURE_REFERRER_POLICY` value `SecurityMiddleware` set
  further in. The shell keeps its meta tag. (The first round used a view decorator; see the second
  pass, finding 2.)
- **Checkout reads the guest link again under the order lock.** `start_checkout` calls
  `_recheck_guest_link(order=..., link_id=...)` right after `_order_for_update`, before anything else
  happens under that lock. It reads the link `FOR NO KEY UPDATE`, filtered by its id **and this order**,
  and refuses with `GuestLinkInvalid` unless the link is still payable. The attempt is then bound to
  that locked row.
- **One validity rule.** `_guest_link_payable(link, order)` (not revoked, not used, not expired, order
  collecting, something outstanding) is used by both `resolve_guest_link` and the locked re-read,
  instead of a second copy of the condition.

The page's GET stays side-effect free (it reads, renders and sets no cookie), and the throttle, the
uniform dead-link page and the J7D already-paid page are unchanged. The view still passes
`actor_id=None` and never reads `request.user`.

## Why the exemption is safe

Django's CSRF check proves that a form came from a page the same browser loaded, so that a cookie
carrying someone's session cannot be ridden by another site. On this page no cookie carries authority:
the token in the path does, and possession of it is the whole capability: start a hosted checkout for
the one outstanding obligation the link names. The server chooses the amount, the currency and the
rail list; the order comes from the link; the attempt has no payer. A forged cross-site submission
would need the token, and whoever holds the token can already do everything the form does. The
provider still asks the payer to complete the payment, and only a signature-verified webhook or
provider reconciliation funds the order. A signed-in member who opens someone else's link pays as a
guest, exactly as a stranger would: the session is not read, so it can neither add authority nor
change who the attempt belongs to.

## The lock and the recheck

The page resolves the link with an ordinary read (`resolve_guest_link`), then calls `start_checkout`.
Before G1, nothing re-read the link after that first read: a revocation or a replacement committing in
between left the page holding a stale "valid" link, and checkout would bind a new attempt to a link the
owner had just stopped.

Revoking (`revoke_guest_link`) and replacing (`create_guest_link`) both lock the order row first, then
the live link row. `start_checkout` now does the same: order, then link, then the open attempt. Payment
success takes the order aggregate (order first), then the attempt, then marks the link used. Every path
takes the order lock first, so the new link lock adds no new lock-order edge and cannot deadlock.

With the order lock held, the re-read is final:

| What happens | Order of events | Result |
| --- | --- | --- |
| Owner revokes or replaces first | revocation commits, then checkout takes the order lock | the re-read sees the link stopped: `guest_link_invalid`, no attempt, uniform page (409) |
| Revocation in progress when the payer taps | checkout waits on the order lock, revocation commits | same as above (real-thread test) |
| Payer taps first | checkout commits an open attempt, then revocation takes the lock | revocation finds the open guest checkout and is refused (`guest_checkout_in_progress`), unchanged |
| Link expires or is used between the two reads | either order | the re-read refuses |
| Order closes between the two reads | either order | the re-read refuses with the same `guest_link_invalid` |
| A caller pairs a link with another order | any | the filter by order finds nothing: `guest_link_invalid` |

Provider idempotency and retries are untouched: the attempt is still written first, its key still goes
to the provider, the provider call still runs outside the transaction, and a failed provider call
still marks the attempt failed.

## Recorded decisions

- **The app's JSON guest checkout gets the same recheck.** It calls the same `start_checkout`, and the
  lock lives there, so this is the one home for the rule. Its view code is unchanged. Its only
  visible difference is in a race: an order that closes between the read and the lock now answers the
  uniform `guest_link_invalid` (404) instead of `order_not_collectable` (409 with the order status),
  which is what `resolve_guest_link` already promises for every dead link.
- **A link stopped mid-tap answers the uniform page with status 409**, the status the page already used
  for a checkout refusal. A prober cannot use it: reaching that branch takes a token that resolved.
- **Two taps at the same moment.** The later tap waits on the order lock. If the first tap's
  provider call is still out, it is asked to wait (second pass, finding 5). Once the first checkout
  is open, a guest's later tap closes it at the provider and opens its own (third pass, B and D).
  Either way the order has one checkout that can collect.
- **Logs.** The guest page's own log lines name the order id only. Django's `django.request` logger
  repeats the concrete path on 4xx/5xx; production keeps it at ERROR and its formatter replaces that
  message with the route template (`test_deployment_safety`). The CSRF refusal, which also logged the
  path, can no longer happen on this page.

## Tests

All page submissions below go through `Client(enforce_csrf_checks=True)` over HTTPS, posted as
Chromium posts them under the shell (`Origin: null`, no Referer) unless the test says otherwise.

New, `apps/finance/tests/test_j7c_guest_link_ux.py`, `BrowserCheckoutTests` (13):

- a fresh payer with no cookies: the page renders no CSRF token and sets no cookie, the tap redirects
  to the hosted test checkout, the browser ends with no cookie, the attempt has no payer, is bound to
  the link, charges the server's amount, and the order stays pending;
- `Origin` and `Referer` both absent: accepted;
- a signed-in unrelated member, then the signed-in owner, pay as a guest (payer stays empty, one
  attempt); the member still gets 403 on the order and on its link; a session does not rescue a dead
  link;
- expired, revoked, used and never-issued links: uniform 404 page, no attempt, private headers;
- a link revoked, replaced or expired between the page's read and checkout (resolve patched to stop the
  link after reading it): uniform page, no attempt;
- the other ordering: once the payer is at the provider, revocation is refused and the link stays live;
- two taps: the second closes the first checkout and opens its own (third pass; before it, the
  same URL); the signed event delivered twice funds once (one `deal_funding`); a tap after payment
  shows the already-paid page and starts nothing;
- provider failure through the real service (gateway raises): "Payments are paused", attempt failed,
  nothing funded, the link still renders and the retry hands off to a new attempt that funds once;
- forbidden fields (amount, currency, provider amount, order, order id, another order's reference and
  token, payer, actor, user, link id, guest email with email off, idempotency key, checkout and success
  URLs, status) change nothing, and the other order gets no attempt;
- private headers on the page, the Arabic page, a dead link, 405, 429, the 302 and the already-paid page;
- the token, its hash and its seed appear in no field of the request sent to the provider, not in the
  redirect, and in no log line (all loggers at DEBUG, `django.request` excepted as above);
- CSRF still guards a session-authorized form: the staff console's refund form, with a valid CSRF
  cookie and token, is refused for `Origin: null` and for no Origin or Referer, and without the token
  from the site's own origin; with the token from the site's own origin it is let through; the same
  staff browser's shell submission to the guest page pays as a guest;
- only the signed webhook funds: returning to `/pay/<ref>/return?result=success` changes nothing, a
  forged signature is a 400 and moves nothing, the signed event pays and marks the link used.

New, `apps/finance/tests/test_guest_payment.py`, `CheckoutRecheckTests` (9), on `start_checkout`
with a link object read before the change: a live link opens the checkout; revoked, replaced, expired,
used, order closed and paired with another order are each refused with `GuestLinkInvalid` and no
attempt; the owner's own checkout needs no link; the app's JSON guest checkout gets the same recheck
(404 `guest_link_invalid`, no attempt).

New, `apps/finance/tests/test_concurrency.py`, `GuestPageRaceTests` (2 here, PostgreSQL, real threads;
the second pass adds a third):

- a revocation holds the order lock, uncommitted; the payer's tap reads the still-valid link, enters
  checkout and is observed waiting; the revocation commits; the tap answers the uniform page and no
  attempt exists;
- two taps at once leave exactly one attempt, which holds the provider's only session; every
  handed-off tap went to it, any other tap was asked to wait, and the signed success funds the order
  once (tightened in the second pass: it counts the provider's sessions and skips no row).

Rewritten to the new rule (the browser shape with CSRF on, previously a CSRF-off `APIClient`): the four
page submissions in `ReceiptEmailTests` and `PublicPageTests` (j7c) and
`test_the_shared_page_hands_the_payer_to_the_provider` (j2). Their assertions are unchanged; the email
test now also asserts no attempt after the second invalid address and the private headers on the 400.

**The tests depend on the fix.** Against `main`'s production code, 27 of these tests fail: the 13
browser tests and the 5 rewritten tests (with the logged 403s), the 7 refusal tests in
`CheckoutRecheckTests` and both concurrency tests. With only `_recheck_guest_link` disabled, 9 fail:
the 7 refusal tests, the mid-tap test in `BrowserCheckoutTests` and the real-thread race. All pass
with the fix.

## Screenshots

`docs/screenshots/g1/`, the real view's HTML (rendered through Django's test client, transactional
email on, as on the server) captured by headless Edge with a true 360 px mobile viewport (device
metrics override, 2x):

- `guest-page-en.png`, `guest-page-ar.png`: the payable page;
- `guest-validation-en.png`, `guest-validation-ar.png`: the 400 after an invalid receipt address;
- `guest-completed-en.png`, `guest-completed-ar.png`: the link opened again after payment.

No state scrolls horizontally (`scrollWidth` equals the 360 px viewport in all six). The rail shows the
local test rail; on the server it is the card rail. The page's look is unchanged by G1; the only markup
change is the removed hidden token field.

The second pass added an "opening" state and an address-conflict state. The third pass replaces
both with one state, so their screenshots are removed:

- `guest-in-progress-en.png`, `guest-in-progress-ar.png`: "A payment is already under way", with a
  "Try again" button that resends the same rail and address. Captured from a real second tap (with
  another receipt address) while the open checkout could not be closed at the provider, rendered by
  the real view through Django's test client and photographed by Playwright's Chromium at 360 px
  (2x, mobile). Neither scrolls horizontally (`scrollWidth` 360); the Arabic page is right to left.

## Second-pass review

Findings 4 and 5 below were reworked in the third pass (next section): the address check of
finding 4 is gone, and the opening wait of finding 5 now covers recovery too.

Astra 6.2 rejected the pull request at `4337d9c` with five findings. The lead accepted all five, and
each is fixed on this branch. Provider idempotency and webhook-only settlement are unchanged, and no
fix changes what is charged or what funds an order.

### 1. Guest tokens in the proxies' error logs (blocker)

Neither proxy writes access logs, but Caddy's `http.log.error` logger records the request of a failed
proxy call, URI and headers included: a guest page request answered 502 while the app was down
wrote its token into the proxy log.

- **Fix.** Both proxies, the edge (`infra/vps/Caddyfile`) and the gateway inside the app image
  (`infra/vps/gateway.Caddyfile`), configure the default logger, which is where `http.log.error`
  writes, with a `filter` format. It rewrites `request>uri` and `request>headers>Referer`, replacing
  the segment after `/pay/guest/` or `/api/payments/guest/` with `REDACTED`. Everything else in the
  entry is kept.
- **Check.** `infra/vps/tests/test_proxy_logs.py` starts each shipped Caddyfile with its upstream
  absent (a local `caddy` binary, or the image pinned in `compose.yml` through Docker; the CI job
  `vps-readiness` has Docker). It sends the page path, the JSON path and the JSON checkout path with
  a guest Referer and asserts three 502s, three `http.log.error` entries whose URI and Referer read
  `REDACTED`, and the token nowhere in the proxy's output. Red before the fix, green after, locally
  on Caddy 2.10.0 (the production image's version) and 2.8.4; `caddy validate` passes on both.
- **Deploy.** Nothing to configure. The edge file is read from the `/opt/wacla` checkout when the
  caddy container starts, and `vps deploy` stops and starts it; the gateway file is copied into the
  app image. So the normal release procedure (`infra/vps/README.md`, "Release commands": update the
  checkout to the merged commit, then `vps deploy` the image built from it) applies both. The admin
  API is off, so there is no live reload: until a release, or a `vps stop` and `vps start` of the
  updated checkout for the edge alone, the running proxies keep logging the URI of a failed request.

### 2. A server error skipped the private headers

The first round set the headers in a view decorator. An exception in the view, or in a middleware
after the session one, becomes Django's 500 only after that decorator has unwound, so the 500 left
without them.

- **Fix.** `GuestPagePrivacyMiddleware`, first in `MIDDLEWARE`, sets both headers on every response
  under `/pay/guest/`, the 500 included. The decorator is gone.
- **Check.** `test_a_server_error_on_the_page_is_private_too`: a failure raised in the view (the
  throttle's cache read) and one raised in `SessionMiddleware` each answer a 500 with both headers.

### 3. A signed-in session lifted the guest throttle

`GuestPaymentThrottle` extended DRF's `AnonRateThrottle`, which does not throttle an authenticated
request. The page runs behind the session middleware, so a member's cookie took it out of the guest
bound.

- **Fix.** `GuestPaymentThrottle.get_cache_key` keys by client address whatever `request.user` is.
  The page, the JSON guest endpoints and the provider-return page (which shares `_throttled`) share
  that one bucket per address, signed in or not.
- **Check.** `test_a_session_does_not_lift_the_guest_bound`: strangers exhaust an address's budget,
  then a signed-in member from it gets 429 on the page and the JSON surface; a member's own requests
  exhaust a second address for a stranger and for the member's tap.

### 4. An open checkout's receipt address was overwritten

A second holder of the link, with another receipt address, was handed the open hosted session (whose
provider page carries the first holder's address) and overwrote the address stored on the attempt.

- **Fix.** For a matching open guest checkout, `start_checkout` compares the address (ignoring case).
  A different one, an empty one included, raises `GuestCheckoutInProgress`: nothing is written and
  the session's URL is not returned. The same address is handed the same checkout. The page shows
  the refusal under the email field (409) so the payer can correct theirs; with receipts off there is
  no field, so it shows the opening state below. The JSON surface answers 409
  `guest_checkout_in_progress`, the code the app already knows.
- **Check.** `OpenCheckoutTests` (another address and an empty one refused, address and URL kept, one
  provider session; the same address in other case reuses; the JSON answer carries no URL) and
  `test_a_second_holder_with_another_address_is_not_shown_the_checkout` on the page.

### 5. A second checkout while the first was at the provider

An open attempt with no URL yet, because its provider call was still out, was superseded by the next
matching request, which then opened a second provider session under a new key. The first request
then found its attempt cancelled and returned a session with an empty URL (the page said "payments
are paused"; the JSON answered 201 with an empty `checkout_url`).

- **Fix.** A matching attempt with no URL created within `CHECKOUT_OPENING_WINDOW` (2 minutes) is
  treated as still opening: the caller gets `CheckoutInProgress` (409 `checkout_in_progress`,
  retryable), the attempt keeps its idempotency key and nothing is superseded. The window is far
  above the provider call's bound (3.05 s to connect, 15 s to read, no retries), so an older such
  attempt belongs to a request that died and is superseded as before. After the provider call,
  `start_checkout` returns only an open attempt with a URL; one superseded meanwhile (another rail,
  another payer) raises `CheckoutInProgress` instead of handing out a closed session. The page shows
  "Your payment page is being opened" with a button that resends the same choices.
- **Money.** A session is only ever handed out with its own attempt's URL, so no one is sent to a
  superseded checkout. Waiting instead of superseding means one provider session per double tap,
  where there were two. Settlement still comes only from the signed webhook or reconciliation.
- **Check.** `OpenCheckoutTests`: a call made while the first is at the provider is refused and finds
  the attempt `created` without a URL under the same key; afterwards one attempt, one provider
  session, and the retry reuses it. An attempt whose request died is refused inside the window and
  superseded after it. An owner paying while the guest's checkout opens leaves the guest a 409
  `checkout_in_progress` with no URL. The page tests cover both waits. `GuestPageRaceTests` (real
  threads on PostgreSQL): the first tap's provider call is held open, the second tap on its own
  connection is asked to wait, then one attempt, the same key, one provider session, and the retry is
  handed it. `test_two_taps_at_once_leave_one_checkout_and_fund_once` and
  `CheckoutRaceTests.test_two_simultaneous_checkouts_leave_exactly_one_open_attempt` now assert the
  mock provider's session count and skip no row without a handle. `MockGateway.checkout_session_ids`
  is the provider-side count.

**The tests depend on the fixes.** Against the first-round code (`4337d9c`), the five new page tests
fail. With only the `start_checkout` changes reverted (the classes kept so the files import), the six
`OpenCheckoutTests` and the held-provider race fail. The two barrier races pass on both: with an
instant test provider they rarely reach the in-flight window, which is why the held-provider test
exists.

## Third-pass review

Astra 6.2 rejected the re-review at `f1fe565`: two blockers and four should-fix findings. The lead
accepted all six (A to F below) and added binding instructions to B and C. Each is fixed on this
branch, in one commit on top of `f1fe565`. No fix changes an amount, a fee, a currency or what funds
an order: settlement still comes only from the signed webhook or provider reconciliation. What
changes is which checkout may still collect.

**The rule now.** An order has at most one checkout that can collect. `start_checkout` takes up to
three short looks at the order's open attempt under the order lock (`_checkout_step`), and makes
each provider call between them with no lock held:

| The open attempt | What the caller gets |
| --- | --- |
| Settling (`processing`: a delayed method was authorised) | `CheckoutInProgress`, nothing touched |
| No hosted URL yet, last written under 2 minutes ago | `CheckoutInProgress`: its request is still at the provider |
| No hosted URL, older, on a rail whose create is idempotent (Stripe, mock) | claimed, then recovered under its own key with the same parameters, then looked at again |
| No hosted URL, older, recovery refused for good, or a rail with nothing to recover by (Chargily) | replaced: its URL, if a checkout was opened at all, never left the server |
| Opened by this signed-in member, same rail, same amount, not lapsed | handed back to that member (`created=False`) |
| Anything else (a guest, another payer, another rail or amount, lapsed) | closed at its provider; replaced only once the provider confirms it closed, else `CheckoutInProgress` |

`CheckoutInProgress` is 409 `checkout_in_progress` on the JSON surfaces and the translated "A payment
is already under way" page on the guest page, the same for every holder whatever they sent.

### A. Proxy error logs still carried an encoded token (blocker)

Caddy logs the URI as the client sent it. `/pay%2Fguest/<token>` defeated the round-2 regex, while
Gunicorn still decoded it to the guest page.

- **Fix.** As the lead asked, no regex: both Caddyfiles drop `request>uri` and
  `request>headers>Referer` from every log entry. `handle_errors` (finding F) makes Caddy record a
  handled error at debug level, so each file keeps those entries in a second logger,
  `proxy_errors`, limited to `http.log.error` at DEBUG, with the same two fields dropped. The
  default logger excludes `http.log.error`, so nothing is logged twice. Neither proxy has access
  logs.
- **Check.** `test_proxy_logs.py` sends eight paths (plain, `%2F` and `%2f` separators, an encoded
  letter, an encoded slash before the token) times two Referers (plain and encoded) to each shipped
  Caddyfile with its upstream absent. It asserts sixteen 502s, sixteen `http.log.error` entries,
  none with a URI or a Referer, and no run of eight characters of the token anywhere in the
  proxy's output. Passes on Caddy 2.10.0 (the production image's version) and 2.8.4 with the real
  binaries; fails on the round-2 files (they keep the URI); `caddy validate` passes on both files
  and both versions.

### B. A superseded checkout stayed payable (blocker)

The owner paying while the guest's checkout opened left the guest a "Try again" that superseded the
owner's attempt locally and opened a new one, while the owner's hosted URL could still be paid.

- **Fix.** The lead's instruction: never leave a superseded attempt payable. Each rail's gateway
  gained `close_checkout`: Stripe `POST /v1/checkout/sessions/{id}/expire`, Chargily
  `POST /checkouts/{id}/expire`, and the mock. A refused expiry is answered by reading the checkout:
  expired, failed or cancelled is closed; paid, complete or processing has collected; anything else
  raises. `start_checkout` supersedes an attempt whose checkout was handed out only after its
  provider confirmed it closed (`CHECKOUT_CLOSED`). An error, a timeout, a checkout still open, or one
  that has taken or is taking a payment answers `CheckoutInProgress`, and the attempt stays open
  for its payment, if any, to settle it. The same rule applies when the same payer switches rail or
  amount. The provider call runs after the order lock is released, so a slow provider holds no lock
  and the lock order is unchanged.
- **Stripe** expires only an `open` session, atomically: a payer cannot complete it afterwards.
  **Chargily** expires only a `pending` checkout and answers success only once it has (400 when
  already expired, 403 for any other status, per its API reference), so a successful expire is the
  confirmation.
- **Check.** `test_another_holder_replaces_the_checkout_once_it_is_closed`,
  `test_a_checkout_its_provider_cannot_close_is_not_replaced` (an outage and a refusal, for a guest
  and the owner, on both surfaces), `test_a_checkout_that_took_a_payment_is_not_replaced` (paid at
  the provider, webhook not yet in: refused, then the webhook funds once),
  `test_the_owner_on_another_amount_or_a_lapsed_checkout_closes_it_first`, and the extended
  owner/guest race on both surfaces: the guest is asked to wait, then the guest's retry closes the
  owner's checkout before opening its own. Every one asserts that exactly one checkout is payable at
  the provider (`MockGateway.is_payable`). `GuestPageRaceTests.test_no_lock_is_held_while_a_provider_closes_a_checkout`
  (real threads, PostgreSQL) holds the provider's close open and takes the order row from another
  connection with a 2 s lock timeout meanwhile. Adapter tests for Stripe and Chargily cover the
  expire call, each refusal answered by a read, a checkout still open, and an outage.

### C. A checkout whose worker died was opened twice (should-fix)

Stripe created a session, the worker died before storing it, and a retry after two minutes opened a
second session under a fresh key.

- **Fix.** `_checkout_request(attempt)` builds the provider request from the attempt alone; the
  first call and every recovery use it, so the key and the parameters are identical (the lead's
  instruction). An attempt with no URL past the opening window, on Stripe or the mock, is recovered
  with `recover_checkout_attempt` before anything else: the member who opened it is handed it, anyone
  else gets it closed and replaced. A recovery the provider cannot answer now leaves the caller
  waiting; one refused for good, or a rail without an idempotent create (Chargily), is abandoned and
  replaced, because its URL never left the server. The provider reconcile job reads the same
  `RECOVERABLE_CHECKOUT_PROVIDERS`.
- **Check.** `test_a_checkout_whose_worker_died_is_recovered_not_opened_twice` (the provider opens
  it, the process dies, a retry inside the window waits, one past it is handed the same checkout;
  two creates with the same request, one provider session),
  `test_a_guest_checkout_whose_worker_died_is_recovered_then_closed`,
  `test_a_lost_checkout_that_cannot_be_recovered` (unreachable, refused, and a rail without
  recovery).

### D. The address check told a link holder whose address opened the checkout (should-fix)

- **Fix.** A guest is never handed an open checkout: nothing a link holder sends tells the one who
  opened it from another. Each guest tap closes the open checkout (B) and opens one of its own, so
  every holder gets the same kind of answer whatever address they send. The address refusal
  (`GuestCheckoutInProgress` at checkout) and its page copy are removed. The code stays in use where
  it already was: revoking or replacing a link while a guest pays.
- **Check.** `test_the_address_a_holder_sends_changes_nothing_they_are_told` (JSON: the same, another
  case and another address each get a new checkout with the same fields),
  `test_a_second_holder_gets_their_own_checkout_whatever_the_address` (page), and
  `test_a_checkout_that_cannot_be_closed_shows_everyone_the_same_wait` (four holders, receipts on and
  off, one identical page apart from the echoed address field).

### E. With receipts off, the JSON surface kept an address (should-fix)

- **Fix.** `start_checkout` drops the address when `guest_receipt_email_required()` is false, for
  every surface: nothing kept on the attempt, nothing sent to the provider.
- **Check.** `test_with_receipts_off_no_surface_keeps_or_sends_an_address`. The guest email tests in
  `test_phase6c_email_events.py` now run with transactional email on, the state they test.

### F. Proxy 502s lacked the private headers (should-fix)

- **Fix.** Both Caddyfiles answer every error they generate through `handle_errors`, which sets
  `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store`. It is not limited by a path
  match an encoded URL could slip past. Responses from Django are untouched (they are not proxy
  errors), and the gateway's default `?Referrer-Policy` stays as it was.
- **Check.** The proxy test asserts both headers on all sixteen 502s; `test_email.py` pins the
  gateway's two Referrer-Policy lines.

### Lead's review of the saved work

The round's work was saved unfinished when Ismail paused all Claude work. Finishing it, three
cases were tightened, each with a test that fails without it:

- **A payment settling is never replaced.** An open attempt in `processing` answers
  `CheckoutInProgress` on every surface before any provider call
  (`test_a_payment_settling_is_never_replaced`).
- **A checkout closed in this request is never handed out.** An attempt this request closed is
  replaced even if it matches the caller by the next look
  (`test_a_checkout_closed_in_this_request_is_never_handed_out`).
- **One request at a time recovers a lost checkout.** The request that starts a recovery claims the
  attempt (its `updated_at`) for the opening window, which now runs from an attempt's last write.
  Another request meanwhile waits and calls no provider, so Stripe never sees the key twice at once
  (`test_one_request_at_a_time_recovers_a_lost_checkout`).

**Tests rewritten to the new rule** (CLAUDE.md: a test that encoded a rule since changed): the
second-tap and second-holder page tests, `test_two_taps_at_once_leave_one_payable_checkout_and_fund_once`,
`test_a_tap_while_the_first_is_at_the_provider_keeps_its_key` (the retry now replaces), the owner tap
in `test_a_signed_in_member_pays_as_a_guest_and_gains_nothing`, and the two "opening" page tests (new copy). They
expected the reuse of an open guest checkout or the address refusal, which D removes. The three
address tests and the dead-opening test of the second pass are replaced by the D and C tests above.

**What G1 does not change.** An attempt that reaches its own expiry (one hour by default) is
expired locally without asking the provider, as before G1. A Stripe session lives 24 hours unless
closed, and Chargily expires its checkouts after 30 minutes. A payer who completes such an old page
after another checkout funded the order is charged, and the existing late-success path records that
payment as unapplied and refunds it. Closing at expiry too is a possible follow-up; it is outside
this package. The app has no dedicated copy for `checkout_in_progress` and shows its generic failure
message; the guest page has its own.

## Checks

Locally, against PostgreSQL (embedded cluster, `config.settings.test_pg`):

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes.
- Guest suites (j7c, guest payment, j2 guest payer, concurrency guest race): 81 passed.
- Whole `apps/finance` suite: **1,145 passed, 0 failed**. A first run on this machine lost its
  database partway through (the embedded server crashed with Windows status `0xC0000142`, and child
  processes failed to start with the same code), so it was rerun on a fresh cluster.

CI on the PR's commit: all checks green, Schema drift and the four Django shards included.

After the second pass, the same way:

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes.
- The guest and race files (j7c, guest payment, j2 guest payer, 6c email events, concurrency): 138
  passed.
- Whole `apps/finance` suite: 1,031 passed, and no test failed outside nine files. That run lost its
  embedded database partway, with the same Windows `0xC0000142` crash as before: every failure was a
  lost connection or a child process that could not start. The nine files were rerun on a fresh
  cluster: 231 passed.
- `infra/vps/tests`: `test_proxy_logs.py` passes on Caddy 2.10.0 and 2.8.4. The other unit tests pass
  except four that need Unix (`fcntl`, `os.getloadavg`) and cannot run on Windows; CI runs them on
  Linux, together with the Docker path of the proxy test.

After the third pass, on Linux against PostgreSQL 16 and Redis 7 with CI's settings:

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes.
- The guest, race and provider files (j7c, guest payment, concurrency, 6c email events, j2 guest
  deposit, Stripe, Chargily): 215 passed. The three tests added for the lead's review, and the
  extended lost-checkout test, fail against the saved work and pass with it.
- `infra/vps/tests`: 38 passed, with the real Caddy 2.10.0 binary; `test_proxy_logs.py` also on
  2.8.4.
- The whole Django suite runs in CI on the pushed commit (four shards), as the project runs long
  suites on GitHub.

## Handoff

- **Board:** G1 built, PR open. No migration, so no contract regeneration; Schema drift is expected
  green.
- **Gate, second pass (strongest-model package).** Astra 6.2 rejected `4337d9c` (five findings) and
  `f1fe565` (six findings); all are fixed (see "Second-pass review" and "Third-pass review"). Astra
  re-reviews the third pass before merge.
- **Deploy (Ismail's approval).** The proxy changes (findings 1, A and F) reach the server only with a
  release: update the `/opt/wacla` checkout to the merged commit and `vps deploy` the image built from
  it. No configuration or secret changes.
- **After merge:** rerun the integrated finance suite once F1 is merged too (plan section 4, G1).
- **O2 after an approved deployment** (plan section 3): a fresh synthetic link through public HTTPS in
  Android Chrome, an embedded browser if available, and once with a Wassla login open; Stripe test rail
  (Chargily is not a guest rail); check hosted checkout, return and the verified test webhook.
