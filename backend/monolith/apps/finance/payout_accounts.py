"""Stripe Connect account provisioning and the single readiness authority.

H2 owns exactly one question: *can this Traveler be paid in EUR through Stripe,
and if not, what is missing?* It answers it here and nowhere else. Views, the
admin console, the mobile projection and the webhook handler all read
`evaluate_readiness`; none of them re-derive it, because a second opinion about
whether money can move is how two surfaces come to disagree about a payout.

What this module deliberately does not do:

* create a Transfer, a bank Payout, a reversal or a cancellation — there is no
  such call in the Connect adapter at all;
* accept a connected-account id from a client. The server creates the account,
  binds it, and only ever reads back the id it stored;
* persist a raw Stripe Account, a bank object, an IBAN, a legal name or an
  Account Link. Only masks, codes, booleans and opaque provider ids survive.

Lock order (see `apps.core.financial_locks`): User -> TravelerPayoutMethod ->
StripePayoutAccount. Never a Deal. Provider I/O always happens *outside* every
transaction and every lock, and the result is applied under a short guarded
write. What keeps a creation tied to its declaration across the Stripe call is
a row, not a lock: the creation intent, committed under the method lock before
the request, which the preference write reads under the same lock (the freeze,
`creation_in_progress`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import transaction
from django.db.models import Exists, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_panel.services import record_admin_action
from .models import (
    FinanceHold,
    Payout,
    PayoutMethodVersion,
    PayoutProviderOperation,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from .providers.base import (
    ProviderCheckoutRejected,
    ProviderError,
)
from .payout_profiles import _traveler, member_refusal
from .providers.stripe_connect import EXPECTED_CONTROLLER, get_connect_gateway

logger = logging.getLogger(__name__)

POLICY_VERSION = "payout_profile_v1"

#: Stripe keeps an idempotency key's stored result for at least 24 hours. H0
#: allows replaying the identical request only inside a conservative window
#: below that; past it, the answer must be *retrieved*, never re-POSTed.
IDEMPOTENT_REPLAY_SECONDS = 23 * 3600

#: How far past an unclear creation's first request the recovery listing
#: reaches: beyond the last replay the window allows, with margin.
CREATION_LISTING_SECONDS = 25 * 3600

#: What Waçla tells Stripe the connected account actually does, so Stripe's
#: hosted onboarding does not have to ask the Traveler to describe a business.
#:
#: Stripe requires `business_profile.url` for these accounts and accepts
#: `business_profile.product_description` in its place when the account holder
#: has no website of their own. A Traveler carrying parcels has no website, so
#: this sentence is what removes the website question — not a URL invented for
#: them, and not Waçla's own site presented as theirs.
#:
#: Every clause here is something Waçla can assert from its own records: the
#: Traveler is independent, they transport parcels, they do so through this
#: marketplace, and they are paid after a delivery completes. It deliberately
#: does not call them a retailer, a merchant, a carrier company or an owner of
#: Waçla, because none of that is true.
#:
#: The Traveler does see it. Stripe calls `product_description` "internal-only",
#: meaning it is never shown to end customers, but hosted onboarding renders it
#: into the Business details step as an editable, pre-filled answer the account
#: holder confirms. Verified on the TEST flow. So this sentence has to read
#: plainly to a Traveler as well as usefully to Stripe's underwriting, and it is
#: theirs to correct if Waçla has it wrong. English because Stripe's own form
#: presents it in the onboarding locale and the underwriting reader is Stripe.
#:
#: Changing this string changes the account-creation fingerprint, which is the
#: point: a different assertion to Stripe is a different request.
TRAVELER_PRODUCT_DESCRIPTION = (
    "Independent traveler providing parcel transportation services through the "
    "Waçla marketplace and receiving compensation after completed deliveries."
)

#: The connected-account payout schedule this application requires. "Manual"
#: is an API scheduling mode: Stripe holds the balance until the platform
#: creates a payout. It is not an admin-click product flow, and H2 creates no
#: payout at all.
REQUIRED_PAYOUT_SCHEDULE = "manual"

#: Stripe `requirements.disabled_reason` values that mean a human decision has
#: gone against the account. None of these clear by collecting another field.
TERMINAL_DISABLED_REASONS = frozenset(
    {
        "listed",
        "other",
        "platform_paused",
        "rejected.fraud",
        "rejected.incomplete_verification",
        "rejected.listed",
        "rejected.other",
        "rejected.platform_fraud",
        "rejected.platform_other",
        "rejected.platform_terms_of_service",
        "rejected.terms_of_service",
    }
)

#: Reasons that mean Stripe is still looking at what was already submitted.
REVIEW_DISABLED_REASONS = frozenset(
    {"under_review", "requirements.pending_verification"}
)

#: The status vocabulary H1 defined on `TravelerPayoutMethod`. Readiness maps
#: provider state onto exactly these; Flutter never sees a Stripe requirement.
STATUS_SETUP_REQUIRED = "setup_required"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_READY = "ready"
STATUS_NEEDS_ATTENTION = "needs_attention"
STATUS_UNAVAILABLE = "unavailable"


class ConnectUnavailable(PermissionDenied):
    """Connect onboarding is switched off or not configured in this deployment."""

    code = "stripe_connect_unavailable"


class CountryUnsupported(ValidationError):
    """A payout-account country cannot hold a Stripe EUR account here.

    `country` is the country refused. `of_account` says whose it is: true when
    it is the country the Traveler's Stripe account was opened for, which no
    new declaration can change; false when it is a declared country, which a
    preference change naming an open country replaces.
    """

    code = "payout_country_unsupported"

    def __init__(self, message, *, country="", of_account=False):
        super().__init__(message)
        self.country = country
        self.of_account = of_account


class SetupInProgress(ValidationError):
    """A Stripe account is being created for the Traveler's EUR method.

    Until Stripe settles that creation, the euro method's country and
    "enabled" stay as they are: the creation can still produce an account,
    and only for them. Onboarding settles it; nothing else waits for Stripe.
    """

    code = "payout_setup_in_progress"


class AccountCountryMismatch(ValidationError):
    """The Traveler's active account was opened for another country.

    A connected account's country cannot change, and there is one active
    account per traveler, platform and mode, so it cannot serve a new
    declaration for a different country.
    """

    code = "stripe_account_country_mismatch"


class AccountKeptProviderError(ProviderError):
    """Stripe failed after the Traveler's account was bound, and it is kept.

    Raised when the payout schedule or the hosted link fails once the account
    and its method version are committed. The next onboarding call reuses that
    account and finishes the step that failed; it never creates a second one.
    """

    code = "provider_error_after_binding"


class PreferenceChanged(ValidationError):
    """The rows an onboarding call planned on changed under it, twice.

    Onboarding serves one declaration: the method version current when it
    started, and that version's country. When a conditional write finds its
    rows changed, or the method moved to another version before the account
    was bound or its link handed out, the call reads the rows again and runs
    once more from the top (`_once_more`). A second change answers this, and
    so does a call naming another country than the saved one. Nothing is
    bound over a newer choice and no link is returned; an account Stripe
    created in the meantime is kept, unbound.
    """

    code = "payout_preference_changed"


#: An account creation Stripe has given no definite answer for yet.
OUTSTANDING = ("prepared", "committed", "unknown")


def creation_in_progress(creation) -> bool:
    """The freeze: whether `creation` can still produce an account.

    The preference write refuses a change of the euro declaration while it
    holds (`payout_profiles._refuse_during_creation`), the read says so, and
    only onboarding settles it.
    """

    return creation is not None and creation.status in OUTSTANDING


@dataclass(frozen=True, slots=True)
class Readiness:
    """One authoritative verdict, plus the safe reason behind it."""

    status: str
    reason: str
    ready: bool


def allowed_countries() -> tuple:
    """The deployment's Connect country list, inside H0's FR/DE/ES ceiling.

    Empty by default. A country appears here because a real TEST onboarding was
    completed for it, not because Stripe's documentation lists it.
    """

    from config.settings.connect import CONNECT_COUNTRY_CEILING

    configured = [
        str(code).strip().upper()
        for code in getattr(settings, "STRIPE_CONNECT_ALLOWED_COUNTRIES", []) or []
    ]
    return tuple(code for code in CONNECT_COUNTRY_CEILING if code in configured)


def expected_mode() -> str:
    return str(getattr(settings, "STRIPE_CONNECT_EXPECTED_MODE", "test") or "test")


def require_connect_enabled() -> None:
    if not getattr(settings, "PAYOUT_PROFILES_ENABLED", False):
        raise ConnectUnavailable("Payout profiles are disabled.")
    if not getattr(settings, "STRIPE_CONNECT_ENABLED", False):
        raise ConnectUnavailable("Stripe Connect onboarding is disabled.")
    if not get_connect_gateway().is_configured():
        raise ConnectUnavailable("Stripe Connect is not configured in this deployment.")


def require_supported_country(country: str) -> str:
    """Validate a declared *account* country, not a nationality.

    Algeria is deliberately absent from every allowlist this architecture
    permits. An Algerian Traveler with a genuinely eligible French, German or
    Spanish account may pass Stripe's own checks; the product must never
    suggest a residency they do not have, so the answer for a declared DZ
    account is an explicit unsupported state plus the DZD manual rail.
    """

    code = str(country or "").strip().upper()
    permitted = allowed_countries()
    if code not in permitted:
        raise CountryUnsupported("This payout-account country is not supported.", country=code)
    return code


# --------------------------------------------------------------------------
# Readiness — the single evaluator
# --------------------------------------------------------------------------


def evaluate_readiness(
    account: StripePayoutAccount, *, holds_exist: bool = None
) -> Readiness:
    """Decide whether this connected account can actually receive EUR earnings.

    Ordered from "this is the wrong account entirely" down to "one more field".
    `details_submitted=true` alone is never sufficient — H0 is explicit about
    that, and Stripe's own object makes it obvious why: an account can have
    submitted details, an inactive transfers capability and no bank.

    `charges_enabled` is not consulted. No card-payment capability is requested
    for these accounts, so it is not an independent gate on being paid.
    """

    if holds_exist is None:
        holds_exist = active_account_holds(account).exists()

    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    if platform and account.platform_id != platform:
        return Readiness(STATUS_UNAVAILABLE, "platform_mismatch", False)
    if account.provider_mode != expected_mode():
        return Readiness(STATUS_UNAVAILABLE, "mode_mismatch", False)
    if not account.active:
        return Readiness(STATUS_UNAVAILABLE, "account_replaced", False)

    country = account.verified_country or account.declared_country
    if country not in allowed_countries():
        return Readiness(STATUS_UNAVAILABLE, "country_unsupported", False)

    if holds_exist:
        # A local compliance or treasury hold outranks anything the provider
        # says. Stripe being happy is not permission to pay.
        return Readiness(STATUS_NEEDS_ATTENTION, "compliance_hold", False)

    if not account.readiness_checked_at:
        return Readiness(STATUS_SETUP_REQUIRED, "readiness_unknown", False)

    if account.controller_summary and any(
        str(account.controller_summary.get(key) or "") != value
        for key, value in EXPECTED_CONTROLLER.items()
    ):
        return Readiness(STATUS_NEEDS_ATTENTION, "controller_unexpected", False)

    if account.default_currency and account.default_currency != "eur":
        return Readiness(STATUS_NEEDS_ATTENTION, "default_currency_unexpected", False)

    reason = account.disabled_reason
    if reason in TERMINAL_DISABLED_REASONS:
        return Readiness(STATUS_NEEDS_ATTENTION, "account_disabled", False)
    if reason in REVIEW_DISABLED_REASONS:
        return Readiness(STATUS_PENDING_REVIEW, "provider_review", False)

    capability = account.transfers_status
    if capability in ("", "unrequested"):
        return Readiness(STATUS_SETUP_REQUIRED, "transfers_not_requested", False)
    if capability == "pending":
        return Readiness(STATUS_PENDING_REVIEW, "transfers_pending", False)
    if capability != "active":
        # `inactive` with outstanding requirements is work the Traveler can do;
        # `inactive` with nothing due is a provider decision to escalate.
        if account.requirement_codes or account.past_due_codes:
            return Readiness(STATUS_SETUP_REQUIRED, "transfers_inactive", False)
        if account.pending_verification_codes:
            return Readiness(STATUS_PENDING_REVIEW, "transfers_verifying", False)
        return Readiness(STATUS_NEEDS_ATTENTION, "transfers_inactive", False)

    if not account.details_submitted:
        return Readiness(STATUS_SETUP_REQUIRED, "details_incomplete", False)
    if account.past_due_codes:
        return Readiness(STATUS_SETUP_REQUIRED, "requirements_past_due", False)
    if account.requirement_codes:
        return Readiness(STATUS_SETUP_REQUIRED, "requirements_due", False)
    if not account.eur_bank_present or not account.external_account_id:
        return Readiness(STATUS_SETUP_REQUIRED, "eur_bank_required", False)
    if account.pending_verification_codes:
        return Readiness(STATUS_PENDING_REVIEW, "provider_review", False)
    if not account.payouts_enabled:
        return Readiness(STATUS_PENDING_REVIEW, "payouts_not_enabled", False)
    if account.payout_schedule_interval != REQUIRED_PAYOUT_SCHEDULE:
        # The application controls disbursement timing. An account paying itself
        # out on Stripe's schedule would settle money this ledger has not
        # authorised, so it is not ready even though Stripe would allow it.
        return Readiness(STATUS_NEEDS_ATTENTION, "payout_schedule_unexpected", False)
    return Readiness(STATUS_READY, "", True)


def active_account_holds(account: StripePayoutAccount):
    """Open Finance holds scoped to this connected account."""

    return FinanceHold.objects.filter(account=account, cleared_at__isnull=True)


# --------------------------------------------------------------------------
# Local intent, provider call, guarded apply
# --------------------------------------------------------------------------


def _method_for(user, *, currency="EUR"):
    return TravelerPayoutMethod.objects.filter(
        traveler=user, currency=currency, method="stripe_connect"
    ).first()


def standing_accounts(traveler_id):
    """The Traveler's active account under this platform and mode: at most one."""

    return StripePayoutAccount.objects.filter(
        traveler_id=traveler_id,
        platform_id=str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or ""),
        provider_mode=expected_mode(),
        active=True,
    )


def in_this_environment(account) -> bool:
    """Whether `account` was opened under the configured platform and mode.

    Only such an account can be onboarded, refreshed or paid here. A method
    can still be bound to one from another platform or mode, which stays its
    recorded history until onboarding binds this environment's account.
    """

    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    return account.platform_id == platform and account.provider_mode == expected_mode()


def account_country(account) -> str:
    """The country an account was opened for, as readiness reads it."""

    return account.verified_country or account.declared_country


def account_country_refusal(country: str, account) -> ValidationError | None:
    """Whether the Traveler's active `account` can serve a declaration of `country`.

    A connected account never changes country, and a Traveler has one active
    account per platform and mode. So once one exists, only it can serve the
    method: its own country must be open, and the declaration must name it.
    """

    opened_for = account_country(account)
    if opened_for not in allowed_countries():
        return CountryUnsupported(
            "The Stripe payout account's country is not supported.",
            country=opened_for,
            of_account=True,
        )
    if opened_for != country:
        return AccountCountryMismatch("The Stripe payout account was opened for another country.")
    return None


def onboarding_incomplete(account) -> bool:
    """Whether a hosted onboarding link still has work to do for this account.

    True while Stripe is still collecting from the Traveler, or while the
    application's payout schedule is unconfirmed (onboarding provisions it),
    unless Stripe has closed the account. Readiness can say "pending review"
    for such an account, because a pending capability outranks missing details
    there; the Traveler still has to be offered the link.
    """

    if account.disabled_reason in TERMINAL_DISABLED_REASONS:
        return False
    return bool(
        not account.details_submitted
        or account.requirement_codes
        or account.past_due_codes
        or account.payout_schedule_interval != REQUIRED_PAYOUT_SCHEDULE
    )


def _creation_key(method, attempt: int) -> str:
    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    return f"acct_create:{platform}:{expected_mode()}:{method.public_reference}:v{attempt}"


def _creation_operation(method) -> tuple:
    """The method's account creation in this platform and mode, and its attempt.

    Found by its idempotency key, which names this platform, mode and method,
    so an operation from another platform or mode is never this environment's.
    A failed attempt with no provider object is passed over, because Stripe
    refused it and created nothing, and so is one whose account Finance
    retired (`retire_account`), so the next onboarding opens a new account;
    anything else is the one creation the next onboarding call deals with, so
    a method never has two in flight.
    """

    attempt = 1
    while True:
        key = _creation_key(method, attempt)
        operation = (
            PayoutProviderOperation.objects.filter(idempotency_key=key)
            .annotate(retired=Exists(StripePayoutAccount.objects.filter(
                creation_operation_key=key, active=False)))
            .first()
        )
        refused = operation and operation.status == "failed" and not operation.provider_object_id
        if not operation or not (refused or operation.retired):
            return attempt, operation
        attempt += 1


def current_creation(method):
    """The account creation the next onboarding call for `method` deals with."""

    return _creation_operation(method)[1] if method else None


def _creation_identity(method, declaration, attempt: int) -> tuple:
    """H0's stable account-creation identity, tied to the declaration it serves.

    The key names the platform, mode, method and attempt. The fingerprint
    covers the whole request and the declaration version it was made for, so
    an operation is replayable for a declaration exactly when its fingerprint
    is that declaration's: same version, same country, same request text.
    """

    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    mode = expected_mode()
    key = _creation_key(method, attempt)
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                platform,
                mode,
                str(method.public_reference),
                str(declaration.public_reference),
                declaration.country,
                "eur",
                "individual",
                sorted(EXPECTED_CONTROLLER.items()),
                TRAVELER_PRODUCT_DESCRIPTION,
                attempt,
            ],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return key, fingerprint, platform, mode


def onboarding_refusal(country: str, *, standing, creation) -> ValidationError | None:
    """The one decision for EUR onboarding, made by the read and by the write.

    In order: the Traveler's active account in this platform and mode, which
    alone can serve the method (`account_country_refusal`); then a creation
    still in progress, which only onboarding can settle, whatever the country
    is now; then the declared country itself. The read treats the last one as
    no obstacle to a new setup, which starts with the preference change that
    names an open country.
    """

    if standing is not None:
        return account_country_refusal(country, standing)
    if creation_in_progress(creation):
        return None
    if country not in allowed_countries():
        return CountryUnsupported(
            "This payout-account country is not supported.", country=country
        )
    return None


def _declaration_of(method, asserted: str = ""):
    """The declaration an onboarding call serves: the method's current version.

    The country always comes from that version. A country in the request is
    only an assertion that the caller saw the same declaration; a country
    change is the preference PATCH's, which checks the revision.
    """

    if not method or not method.enabled or not method.current_version_id:
        raise ValidationError("Enable the EUR payout preference first.")
    declaration = method.current_version
    asserted = str(asserted or "").strip().upper()
    if asserted and asserted != declaration.country:
        raise PreferenceChanged("The request names another country than the saved preference.")
    return declaration


def _require_unchanged(locked, declaration_id) -> None:
    """Start the call again when the locked method no longer serves its declaration."""

    if not locked.enabled or locked.current_version_id != declaration_id:
        raise PreferenceChanged("The payout preference changed during onboarding.")


@dataclass(frozen=True, slots=True)
class _Onboarding:
    """What one onboarding call does, decided under the method lock.

    Either the Traveler's standing `account` already serves `declaration`, or
    Stripe is asked about `operation`: `create` sends (or replays) its request,
    `retrieve` reads back the account it is known to have created, and `search`
    looks for that account without being able to create one.
    """

    declaration: PayoutMethodVersion
    account: StripePayoutAccount | None = None
    operation: PayoutProviderOperation | None = None
    call: str = ""


@transaction.atomic
def _plan_onboarding(*, user, method_id, declaration_id) -> _Onboarding:
    """Decide the call under the locks, and record a new intent before any POST.

    An operation's request is sent only for the declaration it was made for,
    while that declaration is current, its country open, and Stripe still
    replays the key. An older or superseded intent, or one whose country has
    since closed, is only ever looked for, so its request is never sent for
    the first time later. A new intent is committed with its key before Stripe
    hears of it, under the method lock the preference write reads it under:
    from then on the declaration is frozen until the creation is settled, and
    a process that dies in between leaves the exact identity needed to find
    out what happened. Eligibility is read on the locked User row.
    """

    _traveler(User.objects.select_for_update(no_key=True).get(pk=user.pk))
    method = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(pk=method_id)
    _require_unchanged(method, declaration_id)
    declaration = method.current_version
    standing = standing_accounts(method.traveler_id).select_for_update(no_key=True).first()
    attempt, operation = _creation_operation(method)
    refusal = onboarding_refusal(declaration.country, standing=standing, creation=operation)
    if refusal is not None:
        raise refusal
    if standing:
        if not _destination_of(method, standing):
            _bind(method, standing, declaration.country)
        return _Onboarding(declaration, account=standing)
    key, fingerprint, platform, mode = _creation_identity(method, declaration, attempt)
    now = timezone.now()
    if operation is None:
        operation = PayoutProviderOperation.objects.create(
            method=method,
            kind="account_create",
            account_scope=platform,
            provider_mode=mode,
            sequence=PayoutProviderOperation.objects.filter(method=method).count() + 1,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            currency="EUR",
            status="committed",
            first_request_at=now,
            last_request_at=now,
        )
        return _Onboarding(declaration, operation=operation, call="create")
    if operation.status == "failed":
        raise ValidationError("A failed creation already has a provider identity.")
    if operation.provider_object_id:
        # The account exists at Stripe but this database has no row for it.
        return _Onboarding(declaration, operation=operation, call="retrieve")
    age = (now - (operation.first_request_at or operation.created_at)).total_seconds()
    if (
        operation.request_fingerprint == fingerprint
        and age <= IDEMPOTENT_REPLAY_SECONDS
        and declaration.country in allowed_countries()
    ):
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(last_request_at=now)
        return _Onboarding(declaration, operation=operation, call="create")
    return _Onboarding(declaration, operation=operation, call="search")


def _apply_snapshot(account: StripePayoutAccount, snapshot, *, observed_at):
    """Write a provider observation, but only if it is newer than what we hold.

    Two refreshes can be in flight at once — a webhook and a manual refresh, or
    two webhooks. Whichever *request* was issued later wins, regardless of which
    response came back first, so a slow old fetch can never regress readiness
    that a newer fetch already advanced.
    """

    with transaction.atomic():
        # Canonical order: the Traveler's method, then the account. Onboarding
        # holds the method while it reads the standing account, so taking the
        # account first here would be the opposite order and a deadlock.
        method = _lock_method_for(account.traveler_id)
        current = StripePayoutAccount.objects.select_for_update(no_key=True).get(
            pk=account.pk
        )
        if current.readiness_checked_at and current.readiness_checked_at >= observed_at:
            return current, False
        if snapshot.account_id != current.provider_account_id:
            raise ValidationError(
                "Provider answered for a different connected account."
            )
        observed_mode = (
            ("live" if snapshot.livemode else "test")
            if snapshot.livemode is not None
            else current.provider_mode
        )
        if observed_mode != current.provider_mode:
            # A test account cannot become the live destination by being read
            # with a live key, and vice versa.
            raise ValidationError("Connected account mode does not match its record.")
        deadline = None
        if snapshot.current_deadline:
            deadline = datetime.fromtimestamp(snapshot.current_deadline, tz=UTC)
        # Truncated at the provider boundary. These are enum-shaped fields with
        # narrow columns, and a provider answer that does not fit one is a
        # readiness projection to bound, not a database error to raise.
        current.verified_country = snapshot.country[:2]
        current.default_currency = snapshot.default_currency[:3]
        current.transfers_status = snapshot.transfers_capability[:24]
        current.payouts_enabled = snapshot.payouts_enabled
        current.details_submitted = snapshot.details_submitted
        current.requirement_codes = snapshot.requirement_codes
        current.past_due_codes = snapshot.past_due_codes
        current.pending_verification_codes = snapshot.pending_verification_codes
        current.requirements_deadline = deadline
        current.disabled_reason = snapshot.disabled_reason[:64]
        current.controller_summary = snapshot.controller
        current.external_account_id = snapshot.eur_bank_account_id[:255]
        current.eur_bank_present = snapshot.eur_bank_present
        current.payout_schedule_interval = snapshot.payout_schedule_interval[:16]
        current.readiness_checked_at = observed_at
        current.readiness_generation = current.readiness_generation + 1
        verdict = evaluate_readiness(current)
        previous_status = current.status
        current.status = verdict.status
        current.status_reason = verdict.reason
        current.save(
            update_fields=[
                "verified_country",
                "default_currency",
                "transfers_status",
                "payouts_enabled",
                "details_submitted",
                "requirement_codes",
                "past_due_codes",
                "pending_verification_codes",
                "requirements_deadline",
                "disabled_reason",
                "controller_summary",
                "external_account_id",
                "eur_bank_present",
                "payout_schedule_interval",
                "readiness_checked_at",
                "readiness_generation",
                "status",
                "status_reason",
            ]
        )
        _sync_method_status(method, current, verdict)
        if previous_status != verdict.status and _destination_of(method, current):
            from .payout_reconciliation import notify_profile_state

            notify_profile_state(method, state=verdict.status,
                                 key=f"eur:{current.public_reference}:{current.readiness_generation}")
        return current, True


def _lock_method_for(traveler_id):
    return (
        TravelerPayoutMethod.objects.select_for_update(no_key=True)
        .filter(traveler_id=traveler_id, currency="EUR", method="stripe_connect")
        .first()
    )


def _destination_of(method, account) -> bool:
    """Whether `account` is the method's current destination."""

    return bool(
        method
        and method.current_version_id
        and method.current_version.stripe_account_id == account.pk
    )


def _sync_method_status(method, account: StripePayoutAccount, verdict: Readiness) -> None:
    """Project the account's verdict onto the locked EUR method it serves.

    The method keeps its own readiness separate from the enabled preference, so
    a Traveler who turns EUR off and back on does not have to redo onboarding.
    Only the method's current destination speaks for it: an account kept
    unbound, or one a newer declaration has replaced, leaves its status alone.
    """

    if not _destination_of(method, account):
        return
    TravelerPayoutMethod.objects.filter(pk=method.pk).exclude(
        status=verdict.status, status_reason=verdict.reason
    ).update(
        status=verdict.status,
        status_reason=verdict.reason,
        updated_at=timezone.now(),
    )


#: Payout states in which Stripe work on an account has begun and is not
#: finished: a transfer committed or sent, or a failure Finance must resolve.
PAYOUT_IN_PROGRESS = ("processing", "sent", "failed")


def retire_account(*, actor, account_id: int, reason: str) -> StripePayoutAccount:
    """Finance retires a Traveler's Stripe account, so the next onboarding opens a new one.

    The way out for an account opened for the wrong country, which Stripe
    never changes. The account stops being the Traveler's standing account
    and the creation that produced it is passed over (`_creation_operation`).
    Funded payout instructions keep naming it; execution refuses an inactive
    account. Refused while a payout to it is in progress. Under the Payout
    locks, then the method's, then the account's (`apps.core.financial_locks`);
    execution reads the account again after its Payout lock.
    """

    from .payout_profiles import require_capabilities

    require_capabilities(actor, "retry_payouts", "view_payouts")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.", code="reason_required")
    traveler_id = StripePayoutAccount.objects.values_list("traveler_id", flat=True).get(
        pk=account_id
    )
    with transaction.atomic():
        payouts = list(
            Payout.objects.select_for_update(no_key=True, of=("self",))
            .filter(Q(stripe_account_id=account_id)
                    | Q(active_instruction_version__stripe_account_id=account_id))
            .order_by("pk")
        )
        method = _lock_method_for(traveler_id)
        account = StripePayoutAccount.objects.select_for_update(no_key=True).get(pk=account_id)
        if not account.active:
            raise ValidationError(
                "This Stripe payout account is already retired. Nothing was changed.",
                code="already_retired",
            )
        if any(payout.status in PAYOUT_IN_PROGRESS for payout in payouts):
            raise ValidationError(
                "A payout to this account is in progress. Retire the account once "
                "that payout is paid or cancelled.",
                code="payout_in_progress",
            )
        before = {"active": True, "status": account.status,
                  "status_reason": account.status_reason, "country": account_country(account)}
        account.active = False
        verdict = evaluate_readiness(account)
        account.status, account.status_reason = verdict.status, verdict.reason
        account.save(update_fields=["active", "status", "status_reason"])
        _sync_method_status(method, account, verdict)
        record_admin_action(
            actor=actor,
            action="payout_account.retired",
            target=account,
            before=before,
            after={"active": False, "status": account.status,
                   "status_reason": account.status_reason},
            reason=reason,
        )
    return account


def refresh_account(account: StripePayoutAccount, *, gateway=None):
    """Retrieve authoritative state from Stripe and re-evaluate readiness.

    The provider call happens outside every business transaction and every
    row lock. A provider outage leaves the last known readiness in place —
    it never changes a payout currency and never invents a ready account.
    """

    from .mode_safety import require_object_mode

    require_object_mode(account.provider_mode)
    gateway = gateway or get_connect_gateway()
    observed_at = timezone.now()
    snapshot = gateway.retrieve_account(account.provider_account_id)
    return _apply_snapshot(account, snapshot, observed_at=observed_at)


def _provision_schedule(account: StripePayoutAccount, *, gateway, actor=None):
    """Set and then verify the application-controlled payout schedule.

    Configuration, audited, and re-read. Writing the setting is not evidence
    that it took: the verdict below only accepts `manual` because a subsequent
    retrieve reported it.
    """

    gateway.set_payout_schedule(
        account_id=account.provider_account_id, interval=REQUIRED_PAYOUT_SCHEDULE
    )
    record_admin_action(
        actor=actor or account.traveler,
        action="payout_account.schedule_provisioned",
        target=account,
        after={"interval": REQUIRED_PAYOUT_SCHEDULE},
    )
    updated, _ = refresh_account(account, gateway=gateway)
    return updated


def _bind_version(locked, account, country):
    """Make `account` the locked method's current destination.

    A method version is immutable in H1 — the model refuses `update()` and a
    PostgreSQL trigger refuses a raw one — so binding an account is a *new*
    version, never an edit of the version that recorded only the Traveler's
    country preference. The earlier version stays readable as the record of
    what was consented to and when.
    """

    current = locked.current_version
    if current and current.stripe_account_id == account.pk:
        return
    sequence = (
        locked.versions.order_by("-sequence").values_list("sequence", flat=True).first()
        or 0
    ) + 1
    content = [
        str(locked.public_reference),
        sequence,
        "EUR",
        country,
        str(account.public_reference),
        POLICY_VERSION,
    ]
    version = PayoutMethodVersion.objects.create(
        method=locked,
        sequence=sequence,
        rail="stripe_transfer",
        currency="EUR",
        country=country,
        stripe_account=account,
        policy_version=POLICY_VERSION,
        consent_at=timezone.now(),
        created_by=locked.traveler,
        content_hash=hashlib.sha256(json.dumps(content).encode()).hexdigest(),
    )
    locked.current_version = version
    locked.revision += 1
    locked.save(update_fields=["current_version", "revision", "updated_at"])


def _bind(locked, account, country, *, operation=None) -> None:
    """Bind `account` to the locked method, and project its locked readiness.

    `account` is the row as locked inside this transaction, so the method's
    status is read from what the account says now, not from an earlier copy
    a webhook may have overtaken.
    """

    _bind_version(locked, account, country)
    after = {"country": country, "mode": account.provider_mode}
    if operation is not None:
        after["operation"] = str(operation.public_reference)
    record_admin_action(
        actor=locked.traveler, action="payout_account.bound", target=account, after=after
    )
    _sync_method_status(locked, account, evaluate_readiness(account))


def _ask_stripe(method, plan: _Onboarding, gateway):
    """Make the one Stripe call the plan names, and record a failure safely.

    Outside every transaction and lock. A failure is written only onto an
    operation that is still outstanding with no known account, so a late
    answer never overwrites what is already known: a timeout cannot turn a
    recorded refusal back into an unknown, and nothing turns an accepted
    creation into a failed one. When that conditional write finds the
    operation already settled by another call, this call starts again from
    the rows as they are now.

    Only Stripe refusing the creation request itself marks it `failed`, the
    one status that lets a later call use a new key: Stripe ran that request,
    keeps its refusal for this key, and created nothing under it. A 401 or 403
    is refused before Stripe runs a request, and a failed search says nothing
    about whether the account exists, so both leave the outcome unknown.

    The search lists every account created around the operation's first
    request and looks for this operation's own reference, stamped into the
    account's metadata, never for the method's: another attempt's account is
    not this one's. Stripe's list calls have no search delay, so a complete
    listing with no match past the replay window, when this server sends the
    key no more, proves Stripe holds no account for it: the creation failed,
    and the call starts again with a fresh attempt.
    """

    operation = plan.operation
    if plan.call == "retrieve":
        return gateway.retrieve_account(operation.provider_object_id)
    outstanding = PayoutProviderOperation.objects.filter(
        pk=operation.pk, status__in=OUTSTANDING, provider_object_id=""
    )
    if plan.call == "create":
        try:
            return gateway.create_account(
                country=plan.declaration.country,
                idempotency_key=operation.idempotency_key,
                metadata=_account_metadata(method, operation),
                product_description=TRAVELER_PRODUCT_DESCRIPTION,
            )
        except ProviderCheckoutRejected:
            outstanding.update(status="failed")
            raise
        except ProviderError:
            if not outstanding.update(status="unknown"):
                raise PreferenceChanged("Another call settled this creation.") from None
            raise
    first = int((operation.first_request_at or operation.created_at).timestamp())
    try:
        found = gateway.find_account_by_metadata(
            key="shiptrip_operation",
            value=str(operation.public_reference),
            created_gte=first - 60,
            created_lte=first + CREATION_LISTING_SECONDS,
        )
    except ProviderError:
        if not outstanding.update(status="unknown"):
            raise PreferenceChanged("Another call settled this creation.") from None
        raise
    if found is not None and len(found) == 1:
        return found[0]
    now = timezone.now()
    if found == [] and now.timestamp() - first > IDEMPOTENT_REPLAY_SECONDS:
        outstanding.update(status="failed", last_observed_at=now)
        raise PreferenceChanged("Stripe holds no account for this creation.")
    if found:
        logger.warning("finance.account_creation_ambiguous operation=%s matches=%s",
                       operation.public_reference, len(found))
    elif found is None:
        logger.warning("finance.account_creation_listing_incomplete operation=%s",
                       operation.public_reference)
    if not outstanding.update(status="unknown", last_observed_at=now):
        raise PreferenceChanged("Another call settled this creation.")
    raise SetupInProgress("Stripe has not settled this account creation yet.")


def _record_account(*, method, plan: _Onboarding, snapshot, observed_at):
    """Record the account Stripe answered with, and bind it only if it still fits.

    Under the User lock, then the method's, then the account's. The account
    is always kept: a local row, and the operation `accepted` with its id, so
    it is never lost and never created twice, also for a Traveler no longer
    eligible. It becomes the destination only while the Traveler may still
    write payout setup, the method is enabled on the very declaration this
    call serves, and the account was opened for that declaration's country,
    still open (the one country decision, `account_country_refusal`). If the
    method's destination is already this account, the call has nothing
    left to do. Anything else keeps it unbound, and the call starts again
    from the rows as they now are, which give its answer.
    """

    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    mode = expected_mode()
    operation = plan.operation
    observed = str(snapshot.country or "").upper()[:2]
    with transaction.atomic():
        user = User.objects.select_for_update(no_key=True).get(pk=method.traveler_id)
        locked = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(pk=method.pk)
        account = (
            StripePayoutAccount.objects.select_for_update(no_key=True)
            .filter(platform_id=platform, provider_mode=mode,
                    provider_account_id=snapshot.account_id)
            .first()
        )
        if account and account.traveler_id != locked.traveler_id:
            raise ValidationError("This connected account belongs to another user.")
        if account is None:
            account = StripePayoutAccount.objects.create(
                traveler=locked.traveler,
                platform_id=platform,
                provider_account_id=snapshot.account_id,
                provider_mode=mode,
                declared_country=observed,
                creation_operation_key=operation.idempotency_key,
                status="setup_required",
                status_reason="onboarding_required",
            )
        recorded = PayoutProviderOperation.objects.filter(
            pk=operation.pk, provider_object_id__in=("", snapshot.account_id)
        ).update(
            status="accepted",
            provider_object_id=snapshot.account_id,
            provider_object_status="",
            provider_request_id=snapshot.request_id[:255],
            last_request_at=timezone.now(),
        )
        if not recorded:
            raise PreferenceChanged("This account creation already names another account.")
        served = locked.enabled and _destination_of(locked, account)
        fits = (
            member_refusal(user) is None
            and locked.enabled
            and locked.current_version_id == plan.declaration.pk
            and observed == plan.declaration.country
            and observed in allowed_countries()
        )
        if fits and not served:
            _bind(locked, account, observed, operation=operation)
        kept = not (served or fits)
        if kept:
            record_admin_action(
                actor=locked.traveler,
                action="payout_account.kept_unbound",
                target=account,
                after={"country": observed, "mode": mode,
                       "operation": str(operation.public_reference)},
            )
    account = _apply_snapshot(account, snapshot, observed_at=observed_at)[0]
    if kept:
        raise PreferenceChanged("The account no longer fits the payout preference.")
    return account


def _account_metadata(method, operation) -> dict:
    """Opaque internal references only. No name, no email, no Deal contents."""

    return {
        "shiptrip_method": str(method.public_reference),
        "shiptrip_operation": str(operation.public_reference),
        "shiptrip_env": expected_mode(),
    }


def _once_more(call):
    """Run one onboarding pass; when its rows changed under it, run it once more.

    The second pass reads every row again and decides from them alone. If its
    rows change too, `PreferenceChanged` is the answer.
    """

    try:
        return call()
    except PreferenceChanged:
        return call()


def _open_rail() -> None:
    require_connect_enabled()
    if not allowed_countries():
        # A closed rail comes before the Traveler's own setup, as on the read:
        # with no country open, nothing about one account changes the answer.
        raise CountryUnsupported("No payout-account country is open.")


def _account_pass(actor, country, gateway):
    """One onboarding pass, up to the bound account with its payout schedule."""

    method = _method_for(actor)
    declaration = _declaration_of(method, country)
    # Refused before any Stripe call; `_plan_onboarding` decides again under
    # the row locks.
    refusal = onboarding_refusal(
        declaration.country,
        standing=standing_accounts(actor.pk).first(),
        creation=current_creation(method),
    )
    if refusal is not None:
        raise refusal
    # Assert who this credential is before creating anything under it.
    gateway.platform_identity()

    plan = _plan_onboarding(user=actor, method_id=method.pk, declaration_id=declaration.pk)
    account = plan.account
    if account is None:
        # Dated before the call, so a slower answer can never look newer
        # than it is. A creation is dated by its first request: Stripe
        # answers a replay with the body it stored then.
        observed_at = (
            plan.operation.first_request_at if plan.call == "create" else timezone.now()
        )
        snapshot = _ask_stripe(method, plan, gateway)
        account = _record_account(method=method, plan=plan, snapshot=snapshot,
                                  observed_at=observed_at)
    # On every route to the account, so a call that reuses it after a
    # failed provisioning finishes the schedule instead of skipping it.
    if account.payout_schedule_interval != REQUIRED_PAYOUT_SCHEDULE:
        try:
            account = _provision_schedule(account, gateway=gateway, actor=actor)
        except ProviderError as exc:
            raise AccountKeptProviderError(
                "Stripe did not confirm the payout schedule.",
                provider_code=exc.provider_code,
            ) from exc
    return account


def ensure_account(*, actor, country="", gateway=None):
    """Create or reuse this Traveler's one Stripe connected account.

    Idempotent by construction: one active account per traveler/platform/mode is
    a database constraint, the creation identity is stable, and an ambiguous
    outcome is recovered rather than retried. The call serves one declaration,
    the method's current version, which its committed intent freezes until
    Stripe settles the creation. No lock is held while Stripe answers, so two
    calls can overlap: both send the same key, and Stripe creates one account.
    A call naming another country than the saved one binds nothing
    (`PreferenceChanged`).
    """

    _open_rail()
    gateway = gateway or get_connect_gateway()
    return _once_more(lambda: _account_pass(actor, country, gateway))

# --------------------------------------------------------------------------
# Hosted links and the signed return state
# --------------------------------------------------------------------------

_STATE_SALT = "shiptrip.payouts.stripe.onboarding.v1"


def sign_onboarding_state(*, user, method, account) -> str:
    """Bind a return/refresh URL to one user, method, account and mode.

    The state is the whole credential the return route has, so it grants
    exactly one capability: re-read this account's readiness from Stripe. It
    cannot mint a link, cannot reveal anything, and cannot mark anything ready.
    """

    payload = json.dumps(
        {
            "u": user.pk,
            "m": str(method.public_reference),
            "a": str(account.public_reference),
            "p": account.platform_id,
            "d": account.provider_mode,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return TimestampSigner(salt=_STATE_SALT).sign(payload)


def read_onboarding_state(state: str) -> dict:
    """Verify and unpack a return state, or refuse it."""

    ttl = int(getattr(settings, "STRIPE_CONNECT_STATE_TTL_SECONDS", 3600))
    try:
        raw = TimestampSigner(salt=_STATE_SALT).unsign(state, max_age=ttl)
        payload = json.loads(raw)
    except (SignatureExpired, BadSignature, ValueError, TypeError):
        raise ValidationError("This onboarding link is no longer valid.") from None
    if not isinstance(payload, dict) or set(payload) != {"u", "m", "a", "p", "d"}:
        raise ValidationError("This onboarding link is no longer valid.")
    # Shape-check even though the payload is signed. A state that reached here
    # is authentic, not necessarily well-formed, and the fields below go
    # straight into a typed query.
    if type(payload["u"]) is not int or any(
        not isinstance(payload[key], str) or not payload[key]
        for key in ("m", "a", "p", "d")
    ):
        raise ValidationError("This onboarding link is no longer valid.")
    return payload


def resolve_state_account(payload: dict) -> StripePayoutAccount:
    """Load the account a signed state names, checking every binding again.

    Signature validity is not authority on its own. The account must still
    belong to the named user, still sit under the configured platform, and still
    be in the expected mode; any of those can have changed since the link was
    minted.
    """

    try:
        account = StripePayoutAccount.objects.filter(
            public_reference=payload["a"],
            traveler_id=payload["u"],
            platform_id=payload["p"],
            provider_mode=payload["d"],
        ).first()
    except (ValueError, TypeError, ValidationError):
        raise ValidationError("This onboarding link is no longer valid.") from None
    if not account:
        raise ValidationError("This onboarding link is no longer valid.")
    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    if platform and account.platform_id != platform:
        raise ValidationError("This onboarding link is no longer valid.")
    if account.provider_mode != expected_mode():
        raise ValidationError("This onboarding link is no longer valid.")
    method = _method_for(account.traveler)
    if not method or str(method.public_reference) != payload["m"]:
        raise ValidationError("This onboarding link is no longer valid.")
    return account


def start_onboarding(*, actor, country="", gateway=None) -> dict:
    """Create/reuse the account and hand back one short-lived hosted URL.

    The URL is returned to the authenticated owner and nowhere else: not to the
    audit log, not to a notification, not to this process's own logs. It is
    handed out only in a transaction that finds the Traveler still eligible
    and the account still the destination of the version it was resolved on;
    the method in the answer is read in that same transaction. A changed
    version starts the call again, once.
    """

    _open_rail()
    gateway = gateway or get_connect_gateway()
    return _once_more(lambda: _link_pass(actor, country, gateway))


def _link_pass(actor, country, gateway) -> dict:
    from .payout_mobile import setup_gate
    from .payout_profile_api import method_projection

    account = _account_pass(actor, country, gateway)
    method = _method_for(actor)
    served = method.current_version_id
    state = sign_onboarding_state(user=actor, method=method, account=account)
    return_url = _state_url(getattr(settings, "STRIPE_CONNECT_ONBOARDING_RETURN_URL", ""), state)
    refresh_url = _state_url(getattr(settings, "STRIPE_CONNECT_ONBOARDING_REFRESH_URL", ""), state)
    try:
        link = gateway.create_account_link(
            account_id=account.provider_account_id,
            return_url=return_url,
            refresh_url=refresh_url,
        )
    except ProviderError as exc:
        # The account and its binding are committed by now; only the link
        # is missing, and the next call reuses the account.
        raise AccountKeptProviderError(
            "Stripe did not return an onboarding link.", provider_code=exc.provider_code
        ) from exc
    with transaction.atomic():
        user = _traveler(User.objects.select_for_update(no_key=True).get(pk=actor.pk))
        locked = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(pk=method.pk)
        if (
            not locked.enabled
            or locked.current_version_id != served
            or not _destination_of(locked, account)
        ):
            raise PreferenceChanged("The payout preference changed while the link was issued.")
        record_admin_action(
            actor=user,
            action="payout_account.onboarding_link_issued",
            target=account,
            after={"expires_at": link.expires_at, "mode": account.provider_mode},
        )
        answer = method_projection(locked, setup_gate(user))
    return {"method": answer, "url": link.url, "expires_at": link.expires_at}


def _state_url(base: str, state: str) -> str:
    if not base:
        raise ConnectUnavailable("Connect onboarding return URLs are not configured.")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}state={state}"


def destination_account(actor):
    """The Traveler's own account their EUR method is bound to, usable here.

    What refresh and dashboard access act on at Stripe, under the read's
    condition for offering them: bound, active, the Traveler's, and opened
    under the configured platform and mode. An account from another platform
    or mode is history, and its id means nothing to this platform's
    credential, so it is refused before any Stripe call.
    """

    method = _method_for(actor)
    version = method.current_version if method else None
    account = version.stripe_account if version else None
    if (
        not account
        or not account.active
        or account.traveler_id != actor.pk
        or not in_this_environment(account)
    ):
        raise ValidationError("No Stripe payout account is set up for this Traveler.")
    return method, account


def open_dashboard(*, actor, gateway=None) -> str:
    """A single-use Express Dashboard URL for the account's own owner.

    This is how a Traveler changes their bank details without Waçla ever
    holding them. The URL is never stored, logged, emailed or pushed.
    """

    require_connect_enabled()
    gateway = gateway or get_connect_gateway()
    _, account = destination_account(actor)
    if not account.details_submitted:
        # Stripe's Express Dashboard is for an onboarded account. Sending a
        # Traveler there mid-setup is a dead end; the onboarding link is the
        # correct next step and the API says so.
        raise ValidationError("Complete Stripe onboarding before managing payouts.")
    link = gateway.create_login_link(account_id=account.provider_account_id)
    record_admin_action(
        actor=actor, action="payout_account.dashboard_opened", target=account
    )
    return link.url


# --------------------------------------------------------------------------
# Safe projections
# --------------------------------------------------------------------------


def stripe_setup_projection(method) -> dict:
    """What the mobile app is allowed to know about Stripe setup readiness.

    Statuses and safe reason codes only. No requirement payload, no bank data,
    no account id, no link. Which actions the Traveler can take next is the H6A
    read model's answer (`payout_mobile.eur_method`), read from the same gates
    that refuse the write, and is deliberately not repeated here.
    """

    version = method.current_version if method else None
    account = version.stripe_account if version else None
    supported = list(allowed_countries())
    country = (version.country if version else "") or ""
    if account:
        verdict = evaluate_readiness(account)
        status, reason = verdict.status, verdict.reason
    elif country and country not in supported:
        status, reason = STATUS_UNAVAILABLE, "country_unsupported"
    else:
        status, reason = STATUS_SETUP_REQUIRED, "onboarding_required"
    return {
        "status": status,
        "status_reason": reason,
        "country": country,
        "supported_countries": supported,
        "account_reference": None,  # H6A: provider identifiers are not mobile data.
        "mode": account.provider_mode if account else None,
        "bank_present": bool(account.eur_bank_present) if account else False,
        "checked_at": account.readiness_checked_at if account else None,
        "payouts_execution_enabled": False,
    }


def mask_account(account_id: str) -> str:
    """`acct_1TLW…maTz` — enough to correlate, not enough to act on."""

    value = str(account_id or "")
    if len(value) <= 12:
        return value
    return f"{value[:9]}…{value[-4:]}"
