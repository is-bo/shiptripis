# G1: guest checkout without a browser-session dependency (2026-11-25)

Phone test 2, finding 1.1, and package G1 of `docs/WASSLA_PHONE_TEST_2_PLAN.md` (section 4; builder
Claude Opus, extra high). Server only: `apps/finance` and `templates/payments`. No migration, no Go,
no Dart, no new string, no switch. Nothing is deployed by this change.

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
  no-store`**, through one decorator, `_private`, wrapping the view outside `require_http_methods`. So
  the 200 page, the 302 redirect to the provider, the 400 validation page, the 404 dead-link page, the
  409, 429 and 503 pages and the 405 all carry both. The view's header wins over
  `SECURE_REFERRER_POLICY`, which `SecurityMiddleware` only sets when absent. The shell keeps its meta
  tag.
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
- **Two taps at the same moment.** One-open-attempt-per-order still decides: the later tap may
  supersede an attempt whose handoff had not been stored yet, and that earlier request then shows "try
  again" (503). A browser shows only the latest navigation, which goes to the one live checkout. This
  is existing `start_checkout` behaviour, kept as the package requires.
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
- two taps: the same checkout URL, one attempt; the signed event delivered twice funds once (one
  `deal_funding`); a tap after payment shows the already-paid page and starts nothing;
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

New, `apps/finance/tests/test_concurrency.py`, `GuestPageRaceTests` (2, PostgreSQL, real threads):

- a revocation holds the order lock, uncommitted; the payer's tap reads the still-valid link, enters
  checkout and is observed waiting; the revocation commits; the tap answers the uniform page and no
  attempt exists;
- two taps at once leave exactly one open attempt, every handed-off tap went to it, and delivering
  success for every attempt the provider knows funds the order once.

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

## Checks

Locally, against PostgreSQL (embedded cluster, `config.settings.test_pg`):

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes.
- Guest suites (j7c, guest payment, j2 guest payer, concurrency guest race): 81 passed.
- Whole `apps/finance` suite: **1,145 passed, 0 failed**. A first run on this machine lost its
  database partway through (the embedded server crashed with Windows status `0xC0000142`, and child
  processes failed to start with the same code), so it was rerun on a fresh cluster.

CI on the PR's commit: all checks green, Schema drift and the four Django shards included.

## Handoff

- **Board:** G1 built, PR open. No migration, so no contract regeneration; Schema drift is expected
  green.
- **Gate, second pass (strongest-model package).** For Astra: that a session never adds authority on
  the guest page; that the lock order (order, link, attempt) adds no edge against revoke, replace and
  payment success; that the race tests assert real outcomes; that a failed, repeated or superseded
  attempt cannot fund twice; that no response or log line carries the token.
- **After merge:** rerun the integrated finance suite once F1 is merged too (plan section 4, G1).
- **O2 after an approved deployment** (plan section 3): a fresh synthetic link through public HTTPS in
  Android Chrome, an embedded browser if available, and once with a Wassla login open; Stripe test rail
  (Chargily is not a guest rail); check hosted checkout, return and the verified test webhook.
