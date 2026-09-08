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
StripePayoutAccount. Never a Deal. Provider I/O always happens *outside* the
transaction, and the result is applied under a short guarded write.
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
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_panel.services import record_admin_action
from .models import (
    FinanceHold,
    PayoutMethodVersion,
    PayoutProviderOperation,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from .providers.base import ProviderError, ProviderUnavailable
from .providers.stripe_connect import EXPECTED_CONTROLLER, get_connect_gateway

logger = logging.getLogger(__name__)

POLICY_VERSION = "payout_profile_v1"

#: Stripe keeps an idempotency key's stored result for at least 24 hours. H0
#: allows replaying the identical request only inside a conservative window
#: below that; past it, the answer must be *retrieved*, never re-POSTed.
IDEMPOTENT_REPLAY_SECONDS = 23 * 3600

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
    """The declared payout-account country cannot hold a Stripe EUR account here."""

    code = "payout_country_unsupported"


class AccountCreationUnresolved(ValidationError):
    """A previous account creation's outcome is unknown and must be investigated.

    Deliberately not "try again". A second POST after an ambiguous create is
    exactly how a Traveler ends up with two connected accounts, one of which
    nobody is tracking.
    """

    code = "stripe_account_unresolved"


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
        raise CountryUnsupported("This payout-account country is not supported.")
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


def _creation_identity(method, country: str, version: int = 1) -> tuple:
    """H0's stable account-creation identity: platform + mode + method + version."""

    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    mode = expected_mode()
    key = f"acct_create:{platform}:{mode}:{method.public_reference}:v{version}"
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                platform,
                mode,
                str(method.public_reference),
                country,
                "eur",
                "individual",
                sorted(EXPECTED_CONTROLLER.items()),
                version,
            ],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return key, fingerprint, platform, mode


@transaction.atomic
def _prepare_account_creation(*, user, method_id, country):
    """Record the durable local intent before any external POST.

    The operation row exists first and carries the stable idempotency key, so a
    process that dies between here and Stripe leaves behind the exact identity
    needed to find out what happened rather than a blank space.
    """

    User.objects.select_for_update(no_key=True).get(pk=user.pk)
    method = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
        pk=method_id
    )
    existing = (
        StripePayoutAccount.objects.filter(
            traveler=method.traveler,
            platform_id=str(
                getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or ""
            ),
            provider_mode=expected_mode(),
            active=True,
        )
        .select_for_update(no_key=True)
        .first()
    )
    if existing:
        return method, existing, None

    key, fingerprint, platform, mode = _creation_identity(method, country)
    operation = PayoutProviderOperation.objects.filter(idempotency_key=key).first()
    if operation:
        if operation.request_fingerprint != fingerprint:
            # Same identity, different request. The country changed after an
            # account creation was already committed under this key; that needs
            # a new method version, not a silently different account.
            raise ValidationError("Account creation replay conflicts with its request.")
        if (
            operation.status in ("accepted", "reconciled")
            and operation.provider_object_id
        ):
            # The account exists at Stripe but no local row does. Reconcile.
            return method, None, operation
    else:
        operation = PayoutProviderOperation.objects.create(
            method=method,
            kind="account_create",
            account_scope=platform,
            provider_mode=mode,
            sequence=PayoutProviderOperation.objects.filter(method=method).count() + 1,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            currency="EUR",
        )
    now = timezone.now()
    PayoutProviderOperation.objects.filter(pk=operation.pk).update(
        status="committed",
        first_request_at=operation.first_request_at or now,
        last_request_at=now,
    )
    operation.refresh_from_db()
    return method, None, operation


def _apply_snapshot(account: StripePayoutAccount, snapshot, *, observed_at):
    """Write a provider observation, but only if it is newer than what we hold.

    Two refreshes can be in flight at once — a webhook and a manual refresh, or
    two webhooks. Whichever *request* was issued later wins, regardless of which
    response came back first, so a slow old fetch can never regress readiness
    that a newer fetch already advanced.
    """

    with transaction.atomic():
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
        _sync_method_status(current, verdict)
        return current, True


def _sync_method_status(account: StripePayoutAccount, verdict: Readiness) -> None:
    """Project the account's verdict onto the Traveler's EUR method row.

    The method keeps its own readiness separate from the enabled preference, so
    a Traveler who turns EUR off and back on does not have to redo onboarding.
    """

    version = (
        PayoutMethodVersion.objects.filter(stripe_account=account)
        .order_by("-sequence")
        .first()
    )
    method = version.method if version else _method_for(account.traveler)
    if not method:
        return
    TravelerPayoutMethod.objects.filter(pk=method.pk).exclude(
        status=verdict.status, status_reason=verdict.reason
    ).update(
        status=verdict.status,
        status_reason=verdict.reason,
        updated_at=timezone.now(),
    )


def refresh_account(account: StripePayoutAccount, *, gateway=None):
    """Retrieve authoritative state from Stripe and re-evaluate readiness.

    The provider call happens outside every business transaction and outside
    every lock. A provider outage leaves the last known readiness in place —
    it never changes a payout currency and never invents a ready account.
    """

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


def _bind_account(*, method, operation, snapshot, country, observed_at):
    """Create the local account row and version-bind it to the method.

    H0 allows exactly one verified binding when an initially incomplete Stripe
    setup obtains its first account; a later *replacement* account is a new
    immutable method version, never an edit of the old one.
    """

    platform = str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")
    mode = expected_mode()
    with transaction.atomic():
        locked = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
            pk=method.pk
        )
        existing = StripePayoutAccount.objects.filter(
            platform_id=platform,
            provider_mode=mode,
            provider_account_id=snapshot.account_id,
        ).first()
        if existing:
            if existing.traveler_id != locked.traveler_id:
                raise ValidationError("This connected account belongs to another user.")
            account = existing
        else:
            account = StripePayoutAccount.objects.create(
                traveler=locked.traveler,
                platform_id=platform,
                provider_account_id=snapshot.account_id,
                provider_mode=mode,
                declared_country=country,
                creation_operation_key=operation.idempotency_key,
                status="setup_required",
                status_reason="onboarding_required",
            )
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            status="accepted",
            provider_object_id=snapshot.account_id,
            provider_request_id=snapshot.request_id[:255],
            last_request_at=timezone.now(),
        )
        current = locked.current_version
        # A method version is immutable in H1 — the model refuses `update()` and
        # a PostgreSQL trigger refuses a raw one — so binding an account is a
        # *new* version, never an edit of the version that recorded only the
        # Traveler's country preference. The earlier version stays readable as
        # the record of what was consented to and when.
        if not current or current.stripe_account_id != account.pk:
            sequence = (
                locked.versions.order_by("-sequence")
                .values_list("sequence", flat=True)
                .first()
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
        record_admin_action(
            actor=locked.traveler,
            action="payout_account.bound",
            target=account,
            after={
                "country": country,
                "mode": mode,
                "operation": str(operation.public_reference),
            },
        )
    return _apply_snapshot(account, snapshot, observed_at=observed_at)[0]


def _recover_account_creation(*, method, operation, country, gateway):
    """Resolve an ambiguous account creation without ever creating a second one.

    Two safe routes, in order:

    1. Inside Stripe's idempotency retention window, replay the byte-identical
       request under the same key. Stripe returns the original account.
    2. Past that window, *look for* the account by the internal method
       reference stamped into its metadata, bounded by the operation's own
       first-request time.

    If neither resolves it, this blocks. It never POSTs a fresh create, because
    "the retry window expired" is not evidence that nothing was created.
    """

    first = operation.first_request_at or operation.created_at
    age = (timezone.now() - first).total_seconds()
    if age <= IDEMPOTENT_REPLAY_SECONDS:
        return gateway.create_account(
            country=country,
            idempotency_key=operation.idempotency_key,
            metadata=_account_metadata(method, operation),
        )
    found = gateway.find_account_by_metadata(
        key="shiptrip_method",
        value=str(method.public_reference),
        created_gte=int(first.timestamp()) - 60,
    )
    if found is None:
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(status="unknown")
        raise AccountCreationUnresolved(
            "A previous Stripe account creation for this payout method has an "
            "unresolved outcome and requires Finance review."
        )
    return found


def _account_metadata(method, operation) -> dict:
    """Opaque internal references only. No name, no email, no Deal contents."""

    return {
        "shiptrip_method": str(method.public_reference),
        "shiptrip_operation": str(operation.public_reference),
        "shiptrip_env": expected_mode(),
    }


def ensure_account(*, actor, country="", gateway=None):
    """Create or reuse this Traveler's one Stripe connected account.

    Idempotent by construction: one active account per traveler/platform/mode is
    a database constraint, the creation identity is stable, and an ambiguous
    outcome is recovered rather than retried.
    """

    require_connect_enabled()
    gateway = gateway or get_connect_gateway()
    method = _method_for(actor)
    if not method or not method.enabled:
        raise ValidationError("Enable the EUR payout preference first.")
    declared = require_supported_country(
        country
        or (method.current_version.country if method.current_version else "")
        or method.country_code
    )
    # Assert who this credential is before creating anything under it.
    gateway.platform_identity()

    method, existing, operation = _prepare_account_creation(
        user=actor, method_id=method.pk, country=declared
    )
    if existing:
        return existing
    if operation.status in ("accepted", "reconciled") and operation.provider_object_id:
        # The account exists at Stripe but this database has no row for it.
        # Read it back and bind; the observation stamp is taken before the call
        # so a slower answer can never look newer than it is.
        observed_at = timezone.now()
        snapshot = gateway.retrieve_account(operation.provider_object_id)
        return _bind_account(
            method=method,
            operation=operation,
            snapshot=snapshot,
            country=declared,
            observed_at=observed_at,
        )

    observed_at = timezone.now()
    try:
        snapshot = gateway.create_account(
            country=declared,
            idempotency_key=operation.idempotency_key,
            metadata=_account_metadata(method, operation),
        )
    except ProviderUnavailable:
        # Transport loss is not "failed, safe to resend with a new key". The
        # operation stays committed and the next attempt recovers this identity.
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(status="unknown")
        raise
    except ProviderError:
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(status="failed")
        raise

    account = _bind_account(
        method=method,
        operation=operation,
        snapshot=snapshot,
        country=declared,
        observed_at=observed_at,
    )
    if account.payout_schedule_interval != REQUIRED_PAYOUT_SCHEDULE:
        account = _provision_schedule(account, gateway=gateway, actor=actor)
    return account


def resume_account(*, actor, gateway=None):
    """Recover an account whose creation outcome is unknown, then bind it."""

    require_connect_enabled()
    gateway = gateway or get_connect_gateway()
    method = _method_for(actor)
    if not method:
        raise ValidationError("Enable the EUR payout preference first.")
    operation = (
        PayoutProviderOperation.objects.filter(
            method=method, kind="account_create", status__in=("committed", "unknown")
        )
        .order_by("-sequence")
        .first()
    )
    if not operation:
        return ensure_account(actor=actor, gateway=gateway)
    version = method.current_version
    country = require_supported_country(version.country if version else "")
    observed_at = timezone.now()
    snapshot = _recover_account_creation(
        method=method, operation=operation, country=country, gateway=gateway
    )
    return _bind_account(
        method=method,
        operation=operation,
        snapshot=snapshot,
        country=country,
        observed_at=observed_at,
    )


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
    return payload


def resolve_state_account(payload: dict) -> StripePayoutAccount:
    """Load the account a signed state names, checking every binding again.

    Signature validity is not authority on its own. The account must still
    belong to the named user, still sit under the configured platform, and still
    be in the expected mode; any of those can have changed since the link was
    minted.
    """

    account = StripePayoutAccount.objects.filter(
        public_reference=payload["a"],
        traveler_id=payload["u"],
        platform_id=payload["p"],
        provider_mode=payload["d"],
    ).first()
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
    audit log, not to a notification, not to this process's own logs.
    """

    gateway = gateway or get_connect_gateway()
    account = ensure_account(actor=actor, country=country, gateway=gateway)
    method = _method_for(actor)
    state = sign_onboarding_state(user=actor, method=method, account=account)
    return_url = _state_url(
        getattr(settings, "STRIPE_CONNECT_ONBOARDING_RETURN_URL", ""), state
    )
    refresh_url = _state_url(
        getattr(settings, "STRIPE_CONNECT_ONBOARDING_REFRESH_URL", ""), state
    )
    link = gateway.create_account_link(
        account_id=account.provider_account_id,
        return_url=return_url,
        refresh_url=refresh_url,
    )
    record_admin_action(
        actor=actor,
        action="payout_account.onboarding_link_issued",
        target=account,
        after={"expires_at": link.expires_at, "mode": account.provider_mode},
    )
    return {"account": account, "url": link.url, "expires_at": link.expires_at}


def _state_url(base: str, state: str) -> str:
    if not base:
        raise ConnectUnavailable("Connect onboarding return URLs are not configured.")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}state={state}"


def open_dashboard(*, actor, gateway=None) -> str:
    """A single-use Express Dashboard URL for the account's own owner.

    This is how a Traveler changes their bank details without ShipTrip ever
    holding them. The URL is never stored, logged, emailed or pushed.
    """

    require_connect_enabled()
    gateway = gateway or get_connect_gateway()
    method = _method_for(actor)
    account = None
    if method and method.current_version and method.current_version.stripe_account_id:
        account = method.current_version.stripe_account
    if not account or not account.active or account.traveler_id != actor.pk:
        raise ValidationError("No Stripe payout account is set up for this Traveler.")
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
    """What the mobile app is allowed to know about Stripe setup.

    Statuses and safe reason codes, a masked account reference, and which
    actions make sense next. No requirement payload, no bank data, no account
    id, no link.
    """

    enabled = bool(getattr(settings, "STRIPE_CONNECT_ENABLED", False))
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
        "available": enabled and bool(supported),
        "status": status,
        "status_reason": reason,
        "country": country,
        "supported_countries": supported,
        "account_reference": mask_account(account.provider_account_id)
        if account
        else None,
        "mode": account.provider_mode if account else None,
        "bank_present": bool(account.eur_bank_present) if account else False,
        "checked_at": account.readiness_checked_at if account else None,
        "can_start_onboarding": bool(
            enabled and supported and status != STATUS_UNAVAILABLE
        ),
        "can_manage": bool(account and account.details_submitted and enabled),
        "payouts_execution_enabled": False,
    }


def mask_account(account_id: str) -> str:
    """`acct_1TLW…maTz` — enough to correlate, not enough to act on."""

    value = str(account_id or "")
    if len(value) <= 12:
        return value
    return f"{value[:9]}…{value[-4:]}"
