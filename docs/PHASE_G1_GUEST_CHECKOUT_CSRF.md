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

At this pass, an attempt reaching its own expiry was still expired locally without asking the
provider, and the app showed its generic failure for `checkout_in_progress`. The fourth pass fixes
both (findings 1 and 8 below).

## Fourth-pass review

Astra 6.2 rejected `d99c838`: A, D, E and F fixed, B and C partly, three new blockers and six
should-fix findings, all leaving a second checkout that could collect or a gap in the lead's B and C
instructions. Each is fixed on this branch in one commit on top of `d99c838`. As before, no fix
changes an amount, a fee, a currency or what funds an order.

**The rule now.** Three columns on the attempt carry what the third pass kept in memory or read from
`updated_at` (migration `0036`, schema contract regenerated):

- `checkout_request`: the create request, frozen when the attempt is written. The first call and
  every recovery send exactly it.
- `opening_until`: the claim. The request that creates an attempt owns it for two minutes; a request
  that recovers it claims it the same way. No other write moves it.
- `close_requested_at`: set under the order lock before a provider is asked to close the checkout.
  From then on it is handed to no one, its own payer included, and any request may finish the close.

| The open attempt | What the caller gets |
| --- | --- |
| Settling (`processing`) | `CheckoutInProgress`, nothing touched |
| A checkout stored, closed by its provider in this request | replaced |
| A checkout stored, opened by this member, same rail and amount, not lapsed, no close requested | handed back (`created=False`) |
| A checkout stored, anything else | close requested and recorded, then closed at its provider; replaced only once it confirms, else `CheckoutInProgress` |
| No checkout stored, its claim live | `CheckoutInProgress` |
| No checkout stored, claim lapsed, Stripe or mock, under 10 minutes old | claimed, recovered with its frozen request, looked at again |
| No checkout stored, recovery refused while this claim still owns it, too old, or Chargily | replaced: its URL never left the server |

A checkout's URL leaves the server only in the answer of a checkout call (the owner's, the guest
app's or the guest page's redirect), and only after it is stored on an open attempt. So an attempt with no checkout stored was never handed out and nobody can have paid it.

### 1. The expiry job ended an attempt its provider could still collect (blocker)

`handle_attempt_expiry` marked any open attempt expired on the local clock (one hour), while a Stripe
session stays payable for 24 hours, and even marked a `processing` one expired.

- **Fix.** The job calls `expire_checkout_attempt`. Under the order lock: a `processing` attempt is
  left to its own outcome (`attempt_settling`); one with no checkout stored ends now, unless its
  claim is live (the job waits); one with a checkout gets `close_requested_at`. Then, with no lock
  held, its provider is asked to close it. Only a confirmed close expires the attempt. A checkout
  that took or is taking a payment is left to that payment (`attempt_collecting`), and anything
  else is retried by the job, the order staying reserved meanwhile. Webhooks and the provider
  reconcile job end it as before.
- **Check.** `test_expiry_closes_the_checkout_before_the_order_takes_another`,
  `test_expiry_keeps_a_checkout_its_provider_has_not_closed` (both surfaces then wait; the job's
  next run finishes), `test_a_payment_taken_before_its_webhook_holds_off_expiry_and_replacement`,
  `test_expiry_waits_for_the_request_still_opening_a_checkout`, the expiry step added to
  `test_a_payment_settling_is_never_replaced`, and
  `test_expiry_closes_its_checkout_outside_any_transaction` (real transactions).

### 2. Reconciliation replayed a create, and order history showed every URL (blocker)

The reconcile job repeated create for an attempt with no checkout stored, whatever its status;
recovery stored the URL even on an ended attempt; and the owner's order history serialized every
attempt's URL, a guest's included.

- **Fix.** The reconcile job never repeats a create: an attempt with no checkout stored was never
  handed out, so there is nothing to learn (it waits while the attempt is open, then answers
  `checkout_never_handed_out`). The staff "reconcile" action refuses such an attempt with the same
  code, on every rail. `recover_checkout_attempt` stores a checkout only on an attempt still
  `created` with none stored; one that ended meanwhile has the recovered checkout closed, never
  stored. Order history (`PaymentAttemptSerializer`) carries no `checkout_url`; only the checkout
  endpoint's answer (`CheckoutAttemptSerializer`) does. The app's "Continue your payment" now asks
  the checkout endpoint again instead of opening a URL from history.
- **Check.** `test_no_order_history_carries_a_checkout_url`,
  `test_the_reconciliation_job_never_reopens_a_lost_checkout` (no create, no URL, staff refused),
  `test_a_recovery_that_finds_its_attempt_ended_stores_and_shows_nothing`, and the app tests
  `continuing asks the server, which hands the checkout back` and `going back to the payment resumes
  the same session` (history without a URL).

### 3. A refused recovery could drop a checkout stored meanwhile (blocker)

The third pass kept refused recoveries in a set checked before the attempt's stored checkout, the
job bypassed the claim, and Stripe's "key in use" conflict was read as a refusal.

- **Fix.** The set is gone. A stored checkout is always looked at first, so one stored meanwhile goes
  through a confirmed close. An attempt is abandoned after a refusal only if it still has no
  checkout and the same claim (`opening_until`) still owns it. The job no longer recovers (2).
  Stripe's 409, and any `idempotency_key_in_use`, is now `ProviderUnavailable`: the caller waits.
- **Check.** `test_a_checkout_stored_after_its_recovery_was_refused_is_closed_first`, and
  `test_a_key_still_in_use_is_retryable_not_a_refusal` (Stripe adapter, 409 and 400).

### 4. A create whose answer was lost failed the attempt (should-fix)

- **Fix.** On Stripe and the mock, `ProviderUnavailable` from create keeps the attempt `created` with
  its key and releases the claim, so the next tap recovers that checkout. A failed create marks the
  attempt failed only while it still has no checkout stored. Recovery is tried for ten minutes
  (`CHECKOUT_RECOVERY_LIMIT`), because Stripe replays a failed first answer for the same key; after
  that the attempt is abandoned, which is safe since its URL never left the server.
- **Check.** `test_a_create_whose_answer_was_lost_is_recovered_not_opened_twice`.

### 5. A recovery rebuilt the request from current settings (should-fix)

- **Fix.** `_checkout_request` returns the request frozen in `checkout_request` (callback URLs,
  description, metadata, receipt address). The mock now refuses a key reused with other parameters,
  as Stripe does.
- **Check.** `test_a_lost_checkout_is_recovered_after_the_public_address_changed`.

### 6. A close confirmed by a request that then died was forgotten (should-fix)

- **Fix.** `close_requested_at` is written before the provider call, and an attempt carrying it is
  never handed out, by reuse or by its creating request. Any later request closes it again (closing
  a closed checkout confirms it closed) and replaces it.
- **Check.** `test_a_close_whose_request_died_is_finished_never_handed_out`.

### 7. With receipts off, the webhook put an address back (should-fix)

- **Fix.** Reconciliation replaces only an address the guest gave at checkout. An attempt opened with
  receipts off has none, is given none, and no receipt is owed for it.
- **Check.** `test_with_receipts_off_no_surface_keeps_or_sends_an_address` now runs through a signed
  completion that carries an address: none is kept and no guest message is queued.

### 8. The app showed a generic failure for `checkout_in_progress` (should-fix)

- **Fix.** The owner's payment screen and the guest pay screen show "A payment is already under way"
  with "Someone, perhaps you, is already paying this. Try again in a few minutes." (French and Arabic
  as on the guest page). The owner's screen also rereads the order, so a guest paying is shown as
  such. A settling payment no longer offers "Continue".
- **Check.** App tests `a payment already under way is waited for, not opened` (owner) and `a
  payment already under way is waited for, in words` (guest). Screenshots below.

### 9. The two-tap test accepted any second redirect, and the mock closed a processing checkout (should-fix)

- **Fix.** The race test now requires each redirect to be a distinct attempt opened by those taps, and
  each replaced attempt to be closed at the provider. The mock answers "collected" for a checkout
  processing at the provider, so it is never replaced before its webhook.
- **Check.** The race test (three runs), and the processing test in finding 1.

**Each new test fails with its fix removed** (checked by reverting each fix in turn: 10 server
mutations, 2 app mutations).

**Tests rewritten to the new rule:** `age_past_the_opening_window` and the j7c owner race now lapse
the claim (`opening_until`) instead of ageing `updated_at`. In
`test_a_lost_checkout_that_cannot_be_recovered`, an unreachable provider now releases the claim, so
the next tap tries the same key at once (finding 4) instead of waiting out the window. The j7d
"return from the provider" fixture no longer carries a URL in the order history, as the server no
longer sends one. The two-tap race test is stricter, not looser.

**Screenshots** (360 px, from widget tests with the app's fonts):
`docs/screenshots/g1/app-owner-in-progress-{en,ar}.png` and
`docs/screenshots/g1/app-guest-in-progress-{en,ar}.png`.

## Fifth-pass review

Astra 6.2 rejected `1643afc`: findings 1, 3, 4, 5, 6, 8 and 9 of the fourth pass fixed; 2, 7, B and C
partly; two new blockers and eight should-fix findings. Each is fixed on this branch, in one commit
on top of `1643afc`. No fix changes an amount, a fee, a currency or what funds an order.

### 1. A late event from an abandoned checkout could expire the attempt opening now (blocker)

An event naming a checkout that was never stored fell back to the order's newest attempt with no
checkout stored, which could be the one opening at that moment. Applied once that one had stored and
handed out its URL, it expired it, and the next tap opened a second checkout beside a payable one.

- **Fix.** Every checkout carries its attempt id in its metadata: Stripe (session and payment
  intent, as before), Chargily (now, beside the reference) and the mock. The event parsers return it
  (`ProviderEvent.attempt_reference`), and `_match_attempt` binds by the checkout, then the payment,
  then that attempt id, and only to an attempt still without a checkout and on the order the event
  names. The order-only fallback is gone. `reconcile_attempt` takes the event's checkout id and,
  under the lock, ignores an event about another checkout than the one stored
  (`another_checkout`); a success of that kind raises, so the money is kept for a human.
- **Check.** `test_a_late_event_from_an_abandoned_checkout_never_ends_the_one_opening`,
  `test_an_event_bound_before_its_checkout_was_stored_is_read_again_under_lock`, and the adapter
  tests `test_an_event_names_the_attempt_its_checkout_was_opened_for` (Stripe session and payment
  intent) and `test_a_paid_event_is_a_success_and_carries_our_reference` (Chargily).

### 2. Cancelling an order left its issued checkout able to charge (blocker)

`cancel_order` and `close_order_to_collection` cancelled every open attempt in bulk without asking
any provider, so a URL already handed out could still take a payment.

- **Fix.** Both call `_stop_collecting_attempts`. Under the order lock, each open attempt ends at
  once, so nothing funds the order from it. One whose checkout was stored also gets
  `close_requested_at` and a durable `checkout_close` job (new job kind, migration `0036`), which
  asks its provider to close the checkout after the transaction commits and is retried until the
  provider confirms (`close_ended_checkout`). A payment already settling is not cancelled: its own
  outcome ends it, and a success lands as unapplied and is refunded, as before.
- **Check.** `test_cancelling_the_order_closes_the_checkout_a_payer_holds` (a refused close is
  retried, then confirmed), `test_closing_the_order_to_collection_closes_its_checkout_too`,
  `test_an_order_closed_while_a_checkout_opens_has_nothing_to_close`,
  `test_a_payment_settling_outlives_its_orders_cancellation`.

### 3. A failed delayed payment was polled as settling forever (should-fix)

- **Fix.** `fetch_attempt` reads the session with its payment intent expanded. A completed, unpaid
  session whose intent is `requires_payment_method` or `canceled` is failed; any other is still
  processing.
- **Check.** `StripeReconcileTests` (both outcomes, and the expanded request).

### 4. Close work ran out after eight tries (should-fix)

- **Fix.** The expiry job and the new close job get 32 runs (`CHECKOUT_CLOSE_ATTEMPTS`). With the
  capped backoff that is about six days, longer than any rail keeps a checkout collecting on its own
  (Stripe at most a day). An exhausted job is logged at error level, stays visible in the staff job
  list and can be retried there; an open attempt with a close requested is also closed again by the
  next checkout tap.
- **Check.** Asserted on both jobs in `test_cancelling_the_order_closes_the_checkout_a_payer_holds`.

### 5. With receipts off, the stored event kept the payer's address (should-fix)

- **Fix.** The normalised event keeps the provider's address only for an attempt opened with a guest
  receipt address. Stripe's payload scrubber also drops the session's `customer_email`.
- **Check.** `test_with_receipts_off_no_surface_keeps_or_sends_an_address` now also checks the
  stored event, raw and normalised; `test_the_stored_payload_carries_no_customer_pii` covers
  `customer_email`.

### 6. The technical admin showed the hosted URL and the frozen request (should-fix)

- **Fix.** `PaymentAttemptAdmin` lists an explicit set of fields, without `checkout_url` and
  `checkout_request`.
- **Check.** `TechnicalRecordsTests.test_the_technical_attempt_page_shows_no_checkout_url_or_request`
  renders the page as the owner.

### 7. A recovery refused for credentials abandoned the key (should-fix)

- **Fix.** A recovery that meets `ProviderUnavailable`, `ProviderNotConfigured` or
  `ProviderConfigurationInvalid` keeps the attempt and its key, releases the claim and answers
  `CheckoutInProgress` (`RECOVERY_RETRYABLE_ERRORS`). Only a definite refusal abandons it, and only
  within the ten-minute recovery window.
- **Check.** `test_a_recovery_refused_for_its_credentials_keeps_the_key`.

### 8. The claim was dated before the lock wait (should-fix)

- **Fix.** `_checkout_step` reads the clock once the order and attempt locks are held.
- **Check.** `test_a_claim_runs_its_full_window_from_when_it_is_granted` (a five-minute lock wait).

### 9. An attempt could outlive its provider's checkout (should-fix)

- **Fix.** `CheckoutResult.expires_at` carries the provider's own expiry when it states one (Stripe's
  `expires_at`; the mock in tests). `_store_checkout`, for the first call and for a recovery, moves
  the attempt's `expires_at` to the earlier of the two and reschedules its expiry and reconciliation
  jobs. Reuse is refused past it.
- **Check.** `test_an_owner_is_never_handed_a_checkout_its_provider_expired`, and
  `test_a_checkout_reports_when_stripe_stops_it_collecting` (adapter).

### 10. A settling owner payment offered Pay (should-fix)

- **Fix.** The owner's payment screen shows a payment that is settling as "We're still confirming
  your payment" with "Check again", before any resume or rail choice (existing strings in English,
  French and Arabic). A guest's settling payment keeps the "someone else is paying" notice, even past
  the attempt's own expiry.
- **Check.** App tests `the Sender paying by a delayed method is waited for, not offered Pay` and
  `a guest paying by a delayed method is waited for, not offered Pay`.
- **Screenshots** (360 px, from a widget test of the whole payment screen with the app's fonts):
  `docs/screenshots/g1/app-owner-settling-{en,ar}.png`.

**Each new test fails with its fix removed** (14 server mutations, one app mutation): the order-only
event fallback put back; the lock-time checkout recheck removed; no close job on cancellation; a
settling payment cancelled with its order; the expiry job's 32 runs removed; credential errors
abandoning the key; the clock read before the locks; the provider's expiry ignored; the address kept
in the normalised event; `customer_email` kept by Stripe's scrubber; every completed, unpaid Stripe
session read as processing; the admin's full field list; and the attempt id dropped by the Chargily
and Stripe parsers. On the app, the settling branch removed fails both delayed-method tests.

**Tests rewritten to the new rule** (CLAUDE.md: a test that encoded a rule since changed): the
Chargily create test now expects the attempt id in the checkout's metadata (finding 1). The app test
`payment screen refreshes from captured and failed events` (phase 8ff4) opened on the Sender's own
settling payment and expected the rail choice; it now expects the "still confirming" notice and no
rail choice (finding 10), then goes on to the captured and failed events as before. No assertion was
removed or loosened.

## Sixth-pass review

Astra 6.2 rejected `a0b48be`: round-3 #7 and round-4 #3, #5 to #8 and #10 fixed; round-3 #2, round-4
#1, #2, #4 and #9, B and C partly; three new blockers and seven should-fix findings. This is the sixth
round, so the recurring findings were traced to their causes first and fixed there, in one commit on
top of `a0b48be`. No fix changes an amount, a fee, a currency or what funds an order.

### The two causes behind six rounds of findings

Every checkout-correlation and closing finding since the third pass is one of two mistakes, each
patched where it surfaced instead of where it lived:

1. **Events were bound by guesses.** An event was matched by the checkout or payment id we stored,
   and failing that by something the event carried: the order reference, then (fifth pass) an
   attempt id in metadata. Anything able to open a checkout on the same provider account writes
   those, so each fallback had a variant that bound an event to the wrong attempt (round-4 #1, fifth
   pass #1, sixth-pass blocker 1).
2. **Whether a checkout can take money was read from the attempt's status.** "Open" was taken to mean
   "can collect" and "ended" to mean "cannot", while only the provider knows. Each path that ends an
   attempt (replacement, expiry, cancellation, closing to collection, old code before G1) did part
   of the close-and-reconcile work, and each left a gap: a cancelled order's checkout still payable,
   a collected payment never recorded, a superseded session still live after the upgrade (round-4
   #2 and #4, fifth pass #2, sixth-pass blockers 2 and 3, B).

### The rules now

- **An event binds only to the attempt that stored the provider object it names** (`_match_attempt`):
  its checkout id, else the payment id recorded with its success. Nothing else an event carries
  binds it. An event naming nothing we stored is ignored (`unknown_checkout`), and a success of that
  kind raises, so the money is kept, retried and left for a human. This is complete because a
  checkout's id is stored before its URL leaves the server: nobody can pay through a checkout we have
  not stored. The order-reference and attempt-id fallbacks, `ProviderEvent.attempt_reference`,
  `_reference_uuid` and the lock-time `another_checkout` comparison are removed, and Chargily's
  metadata is back to the reference alone.
- **A checkout is live until its provider confirms it can take no further payment.** The attempt
  records that fact in a new column, `checkout_final_at`, set only on a provider's word: an outcome
  it reported (paid, failed, expired, cancelled), or its confirmation that the checkout closed.
  `LIVE_CHECKOUT` (stored checkout, not final, not succeeded) is the one definition, with a partial
  index. The attempt's status no longer says anything about the checkout.
- **One routine decides what becomes of a checkout: `settle_checkout`.** It reads the provider first
  and records a final outcome through `reconcile_attempt`, so money paid through the checkout always
  lands (applied, or unapplied and refunded when the order is gone). A checkout still wanted is left
  open; any other is closed, and only the provider's confirmation makes it final. A payment settling
  or being made answers "still live". The in-request replacement, the expiry job, the settle job and
  order closure all go through it; `_close_checkout`, `close_ended_checkout` and the fifth pass's
  `checkout_close` job kind are removed.
- **One durable obligation follows a live checkout to its end: its settle job**
  (`provider_reconcile:<attempt>`). It completes only when the checkout is final, is deferred (without
  spending its retries) while a payment settles or is being made, and is retried while the provider
  answers nothing usable. `_arm_checkout_settle` arms it again from whatever state an earlier run
  left. The job loop's new sweep (`arm_live_checkouts`, from `run_due_jobs`) gives every live
  checkout without a pending settle job one, so no retry budget, outage, or code path (old code
  included) can leave a live checkout unwatched.
- **No checkout is handed out or opened while another of the order's checkouts is live.**
  `_checkout_step` looks for any live checkout on the order, whatever its attempt's status, and
  settles it first, with no lock held; only the provider's confirmation lets the next look go on.
  The rule for handing a member their own checkout back is one function, `_hands_back`, used by the
  checkout path and by what the screens offer.

### Blockers

1. **An early event could bind by metadata to the wrong attempt** (services.py:2227, stripe.py:585).
   Fixed by the first rule: no binding by metadata or reference at all, so there is nothing to
   collide with. A `payment_intent.payment_failed` no longer ends anything (see should-fix 1).
   *Check:* `test_an_event_naming_a_checkout_never_stored_binds_to_nothing`,
   `test_a_late_event_from_an_abandoned_checkout_never_ends_the_one_opening` (rewritten, below), and
   the Stripe endpoint test `test_a_declined_card_and_a_session_never_stored_bind_to_nothing`.
2. **A close that found the checkout collected recorded nothing** (services.py:1855, jobs.py:327).
   Closing is now part of settling: the provider is read before any close, a collected checkout
   answers "still live" and the settle job reads it again five minutes later, its retries untouched,
   until the payment's outcome is recorded; on a cancelled order it lands as unapplied and is
   refunded. A refused or failed provider call keeps the job (retried, then re-armed by the sweep).
   *Check:* `test_a_cancelled_orders_checkout_that_took_a_payment_refunds_it`,
   `test_a_payment_being_made_holds_off_expiry_and_is_followed_to_its_end`,
   `test_a_settle_job_that_ran_out_is_armed_again_until_the_checkout_is_final`.
3. **Sessions superseded by old code stayed live after the upgrade** (0036, services.py:1583). Live
   is read from the provider's word, not the status, so a session old code left cancelled, expired
   or superseded without closing is live, settled before the order hands out or opens anything, and
   watched by the sweep. No data migration: the same rule covers every row.
   *Check:* `test_a_checkout_old_code_ended_is_closed_before_any_other_opens` (cancelled and
   expired, with the close refused first) and
   `test_the_job_loop_arms_every_live_checkout_left_without_a_settle_job`, on rows left as old code
   left them (no close, no job).

### Should-fix

1. **A Stripe card decline exhausted its job.** `payment_intent.payment_failed` is ignored: the payer
   may try again in the same session, which only its own session's events end
   (`checkout.session.async_payment_failed` for a delayed method, or the session read by the settle
   job). *Check:* `test_a_declined_card_ends_nothing` (rewritten, below) and the endpoint test above.
2. **Chargily's 30-minute lifetime was not stated.** The adapter returns
   `expires_at = created_at + 30 minutes` (`CHECKOUT_LIFETIME`), or from the time of the request when
   the answer carries no `created_at`, so the attempt ends and is never handed back past it.
   *Check:* `test_a_checkout_states_when_chargily_stops_it_collecting`,
   `test_a_checkout_without_its_creation_time_ends_no_later_than_stated`, and the existing
   `test_an_owner_is_never_handed_a_checkout_its_provider_expired` for the tap past the deadline.
3. **Chargily's hosted URL was stored and shown on the provider-event page.** Both scrubbers drop
   hosted-URL keys before anything is stored: `url` and `checkout_url` for Chargily, `url` for
   Stripe. *Check:* `test_the_published_webhook_shape_passes_the_mode_check_and_keeps_no_url` (the
   published shape), `test_the_stored_payload_carries_no_customer_pii` (Stripe).
4. **Chargily's string `livemode` was isolated as another mode.** After the signature is verified,
   and on Chargily's own API answers, `"true"` and `"false"` become booleans; any other value is left
   for the strict mode check to refuse. *Check:* the published-shape test with mode enforcement on
   (a test event passes, a live one is refused) and
   `test_a_livemode_that_is_neither_true_nor_false_is_left_to_be_refused`.
5. **A row with no frozen request made recovery raise a 500.** Recovery needs the request frozen on
   the attempt; one that has none, or one that no longer fits, is refused like a create the provider
   refused (`checkout_request_unusable`), so the attempt is abandoned and replaced. Its key is not
   replayed with rebuilt parameters, which C forbids, and nothing is lost: a checkout behind that key
   was never stored, so its URL never left the server. *Check:*
   `test_a_lost_checkout_with_no_request_to_repeat_is_replaced_not_a_500` (through the API),
   `test_a_lost_checkout_whose_request_no_longer_fits_is_replaced`.
6. **and 7. The screens offered what the server would refuse.** The server now says what the next
   tap meets (`checkout_state`): on the owner's order payload `ready`, `resumable` (their own checkout,
   handed back by `_hands_back`, on a rail still available), `guest_paying` (a link holder's checkout
   can still be paid, or their payment is settling), `in_progress` (a checkout is being opened) or
   `settling`; on the guest quote only `ready` or `in_progress`, with nothing about who is paying.
   The app's payment section is driven by it alone (the client-side `isUnderWay`, `isSettling` and
   `canResume` are removed): Continue only when resumable, the rails when the old rail is off. The
   guest screen replaces Pay with "Check again", which reads the quote again, while the server says
   a payment is under way or after a tap was told so; the guest web page opened in that state says
   so and offers to look again. Existing strings only, in English, French and Arabic.
   *Check:* server `test_the_owner_is_offered_their_checkout_only_while_it_is_handed_back`,
   `test_a_checkout_being_opened_or_settling_is_waited_for_on_every_screen`,
   `test_a_guests_payment_is_shown_to_the_owner_as_theirs` (with the web page); app
   `an open checkout on a rail switched off is not continued`,
   `a checkout being opened is waited for, not continued`,
   `the Sender's own open checkout is continued`,
   `a payment already under way is waited for, then checked again`,
   `a link opened while its payment is settling offers no Pay`.
   *Screenshots* (360 px, widget tests with the app's fonts): the owner's payment screen while a
   checkout is being opened, `docs/screenshots/g1/app-owner-opening-{en,ar}.png`, and the guest
   screen with "Check again" in place of Pay, `app-guest-check-again-{en,ar}.png`. The guest web
   page opened in that state looks like `guest-in-progress-{en,ar}.png`; only its button now reloads
   the page instead of resubmitting a choice.

**Each new test fails with its fix removed** (16 server mutations): the job loop's sweep; the
live-checkout gate in `_checkout_step`; reading the provider before closing; a collected checkout
treated as final; order closure arming the settle job; the provider fact recorded by
`reconcile_attempt`; the unusable-request guard; the rail-availability condition and the opening
claim in `checkout_state`; the guest page's in-progress branch; Chargily's livemode normalisation, URL
scrub and stated expiry; Stripe's URL scrub; the declined card mapped back to failed; and the settle
job armed when a close cannot be confirmed. On the app, each new test fails against the fifth pass's
attempt-derived chooser or guest footer.

**Tests rewritten to the new rule** (CLAUDE.md: a test that encoded a rule since changed). No
assertion about money, funding or what a payer is handed was removed or loosened.

- `test_a_failed_payment_intent_is_reported_as_failed` (Stripe adapter) is now
  `test_a_declined_card_ends_nothing`: a decline is ignored (should-fix 1).
- `test_an_event_names_the_attempt_its_checkout_was_opened_for` (Stripe adapter) and the attempt-id
  assertions of the Chargily create and paid-event tests, added in the fifth pass, are removed with
  the metadata binding they tested; the Chargily tests are back to their fourth-pass form.
  `test_a_reference_that_is_not_a_uuid_matches_no_order` goes with `_reference_uuid`.
- `test_an_event_bound_before_its_checkout_was_stored_is_read_again_under_lock` is now
  `test_an_event_naming_a_checkout_never_stored_binds_to_nothing`, and
  `test_a_late_event_from_an_abandoned_checkout_never_ends_the_one_opening` expects that event bound
  to nothing instead of to the abandoned attempt (blocker 1). The live attempt's assertions are kept.
- `test_a_checkout_that_took_a_payment_is_not_replaced`: the next tap now reads the provider and
  records the payment, so it is told the link is used, and the order is paid before the webhook.
- `test_a_payment_taken_before_its_webhook_holds_off_expiry_and_replacement`: a payment settling at
  the provider is now recorded as settling by the first tap (status `processing`, expiry
  `attempt_settling`); the case of a close refused while the checkout is still open moved to the new
  `test_a_payment_being_made_holds_off_expiry_and_is_followed_to_its_end`.
- The four order-closure tests now follow the settle job (`provider_reconcile`) instead of the removed
  `checkout_close` job, with the same retried-then-confirmed close; the two that asserted no close
  job now assert the settle job ends without asking the provider, or defers while a payment settles.
- The guest quote's key allowlist (three tests: two in the guest payment file, one in j2 guest
  payer) includes `checkout_state`.
- App: `a payment already under way is waited for, in words` expected Pay to stay; it now expects
  "Check again" (should-fix 7). The phase 8ff4, j7c and j7d fixtures carry the server's
  `checkout_state`, as the server now sends it.

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

After the fourth pass, the same way:

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes. Schema contract regenerated
  from a fresh migrate with `pg_dump` 16: three new columns, nothing else.
- The whole `apps/finance` and `apps/admin_panel` suites: 1,425 passed, 0 failed.
- App: `dart format`, `flutter analyze --fatal-infos` clean; the whole `flutter test` suite: 1,671
  passed.

After the fifth pass, on Linux against PostgreSQL 16 and Redis 7 with CI's settings:

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes. `build_helper_instructions
  --check`: up to date. The job kind added to `0036` changes choices only and emits no SQL, so the
  schema contract is unchanged.
- The finance files on the changed paths (guest payment, Stripe, Chargily, recovery, the three
  concurrency files, lock order, webhooks, j7c, j7d, invariants, jobs and payouts): 389 passed, 0 failed.
- App: `dart format` and `flutter analyze --fatal-infos` clean. The whole `flutter test` suite failed
  only on the phase 8ff4 test rewritten above, which passes since.
- The whole Django and app suites run in CI on the pushed commit, as the project runs long suites on
  GitHub.

After the sixth pass, the same way:

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes. `build_helper_instructions
  --check`: up to date. Schema contract regenerated: the new column and its partial index, nothing
  else.
- The 26 files on the changed paths (guest payment, Stripe, Chargily, recovery, the three concurrency
  files, lock order, webhooks, adapter, contracts, provider currency and HTTP, j2 guest payer, j7c,
  j7d, invariants, jobs and payouts, operations, posting deposit, protection, the worker snapshot,
  the admin console and the two marketplace switch files): 668 passed, 0 failed, after the j2 guest
  payer allowlist was given the new key (listed above).
- Mutation checks: each of the 16 server fixes, reverted alone, fails its tests.
- App: `dart format` and `flutter analyze --fatal-infos` clean; the seven touched test files: 223
  passed.
- The whole Django and app suites run in CI on the pushed commit.

## Handoff

- **Board:** G1 built, PR open. Migration `finance 0036` adds four nullable or defaulted columns to
  the payment attempt (`checkout_request`, `opening_until`, `close_requested_at`,
  `checkout_final_at`) and the partial index `fin_attempt_live_checkout_idx`; no job kind. The schema
  contract is regenerated in the same commit.
- **Gate, second pass (strongest-model package).** Astra 6.2 rejected `4337d9c` (five findings),
  `f1fe565` (six findings), `d99c838` (three blockers, six should-fix), `1643afc` (two blockers,
  eight should-fix) and `a0b48be` (three blockers, seven should-fix); all are fixed (see the second
  to sixth-pass sections). Astra re-reviews the sixth pass before merge.
- **Deploy (Ismail's approval).** The proxy changes (findings 1, A and F) reach the server only with a
  release: update the `/opt/wacla` checkout to the merged commit and `vps deploy` the image built from
  it. No configuration or secret changes. On its first cycles the job loop's sweep arms a settle job
  for every older checkout not yet confirmed final, and each asks its provider once (test mode on the
  server today), so those rows end as their providers report.
- **After merge:** rerun the integrated finance suite once F1 is merged too (plan section 4, G1).
- **O2 after an approved deployment** (plan section 3): a fresh synthetic link through public HTTPS in
  Android Chrome, an embedded browser if available, and once with a Wassla login open; Stripe test rail
  (Chargily is not a guest rail); check hosted checkout, return and the verified test webhook.
