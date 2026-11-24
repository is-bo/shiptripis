"""A member deletes their own account (App Store 5.1.1(v), Google Play User Data).

The one rule for deleting an account. The app shows what stands in the way
(`blockers`) and then asks for the deletion; the server checks everything
again under a lock on the member's row and decides.

**What must be finished first.** Nothing a deletion would leave half done:
an open request or a published journey (cancelling those has its own refund
and notice rules, which the member runs from the app), a delivery that has not
closed, a payout or refund that has not reached the member, an open dispute.
Each blocker has a stable code the app words.

**What deletion does.** The account can never sign in again and everything
that identifies the member is wiped from it: email (replaced by an address
that cannot receive mail, so the real one is free to sign up again), name,
phone, region, language, password, linked Google and Apple identities, sign-in
and email codes, every session and push device, the inbox, notification
settings, route alerts, the public profile and the profile photo (its stored
object is deleted once the deletion commits). Pending emails to the member
are cancelled.

**What stays.** The records other people and the law rely on: deliveries,
payments, refunds, payouts and their payout details, ID check decisions,
reviews, problem reports, disputes and chat history. They keep pointing at the
emptied account row, which is why deletion empties the row rather than
removing it (every such reference is `PROTECT`).

**Sign in with Apple.** A member who has an Apple identity must have it
revoked (`apple_revoke`). The app sends a fresh authorization code; the server
revokes before it deletes, so a refused or unreachable Apple leaves the
account untouched and the member can try again.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import apple_revoke, photos, sessions
from .models import EmailVerificationCode, OAuthIdentity, PasswordResetCode

#: An open request: posted (or waiting for its deposit) and not yet closed.
BLOCKER_REQUESTS = "open_requests"
#: A journey that is published or under way.
BLOCKER_JOURNEYS = "active_journeys"
#: A delivery (as sender or traveler) that has not closed.
BLOCKER_DELIVERIES = "open_deliveries"
#: A payout to the member that has not been paid or cancelled.
BLOCKER_PAYOUTS = "pending_payouts"
#: A refund to the member that has not finished.
BLOCKER_REFUNDS = "pending_refunds"
#: A dispute on one of the member's deliveries that is still open.
BLOCKER_DISPUTES = "open_disputes"

#: In the order the app lists them.
BLOCKERS = (
    BLOCKER_DELIVERIES,
    BLOCKER_DISPUTES,
    BLOCKER_PAYOUTS,
    BLOCKER_REFUNDS,
    BLOCKER_REQUESTS,
    BLOCKER_JOURNEYS,
)

_CLOSED_REQUEST_STATUSES = ("completed", "cancelled", "expired")
_OPEN_JOURNEY_STATUSES = ("pending_verification", "active", "in_progress")
_CLOSED_DEAL_STATUSES = (
    "completed",
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
    "payment_failed",
)
_SETTLED_PAYOUT_STATUSES = ("paid", "cancelled")
_OPEN_REFUND_STATUSES = ("pending", "processing")

#: The domain of the address a deleted account keeps. `.invalid` is reserved
#: (RFC 2606): no mail can ever be delivered there.
DELETED_EMAIL_DOMAIN = "deleted.wassla.invalid"


class AccountDeletionRefused(Exception):
    """Deletion refused, with a stable code, an HTTP status and extra fields."""

    def __init__(self, code: str, status: int, **fields):
        super().__init__(code)
        self.code = code
        self.status = status
        self.fields = fields

    @property
    def payload(self) -> dict:
        return {"code": self.code, **self.fields}


@dataclass(frozen=True, slots=True)
class DeletionCheck:
    """What the app needs to show before the member confirms."""

    blockers: tuple[str, ...]
    password_required: bool
    apple_authorization_required: bool


def blockers_for(user) -> tuple[str, ...]:
    """Every blocker that stands for ``user`` now, in `BLOCKERS` order."""

    from apps.deals.models import Deal
    from apps.disputes.models import Dispute
    from apps.finance.models import PaymentRefund, Payout
    from apps.parcels.models import ParcelRequest
    from apps.trips.models import Journey

    party = Q(sender=user) | Q(traveler=user)
    found = {
        BLOCKER_REQUESTS: ParcelRequest.objects.filter(sender=user)
        .exclude(status__in=_CLOSED_REQUEST_STATUSES)
        .exists(),
        BLOCKER_JOURNEYS: Journey.objects.filter(
            traveler=user, status__in=_OPEN_JOURNEY_STATUSES
        ).exists(),
        BLOCKER_DELIVERIES: Deal.objects.filter(party)
        .exclude(status__in=_CLOSED_DEAL_STATUSES)
        .exists(),
        BLOCKER_PAYOUTS: Payout.objects.filter(traveler=user)
        .exclude(status__in=_SETTLED_PAYOUT_STATUSES)
        .exists(),
        BLOCKER_REFUNDS: PaymentRefund.objects.filter(order__owner=user)
        .filter(Q(status__in=_OPEN_REFUND_STATUSES) | Q(requires_manual_action=True))
        .exists(),
        BLOCKER_DISPUTES: Dispute.objects.filter(
            Q(deal__sender=user) | Q(deal__traveler=user),
            status__in=Dispute.ACTIVE_STATUSES,
        ).exists(),
    }
    return tuple(code for code in BLOCKERS if found[code])


def has_apple_identity(user) -> bool:
    return OAuthIdentity.objects.filter(
        user=user, provider=OAuthIdentity.Provider.APPLE
    ).exists()


def hold_active_member(user_id: int) -> bool:
    """Lock a member's row the way deletion does; False once it is not active.

    Opening something deletion waits for (a request, a published journey)
    takes this lock first, so it either commits before deletion reads its
    blockers again or sees the account already gone.
    """

    return (
        get_user_model()
        .objects.select_for_update(no_key=True)
        .filter(pk=user_id, is_active=True)
        .exists()
    )


def check(user) -> DeletionCheck:
    return DeletionCheck(
        blockers=blockers_for(user),
        password_required=user.has_usable_password(),
        apple_authorization_required=has_apple_identity(user),
    )


def delete_account(user, *, password: str = "", apple_authorization_code: str = "") -> None:
    """Delete ``user``'s account, or raise `AccountDeletionRefused`.

    The checks that need no lock run first, so a wrong password or a blocker
    costs no call to Apple. Apple is asked before the row is locked, because a
    network call must not hold a lock; the blockers are then read again under
    the lock, so nothing opened in between is left behind.
    """

    if user.is_staff:
        raise AccountDeletionRefused("staff_account", 403)
    if user.has_usable_password() and not user.check_password(password or ""):
        raise AccountDeletionRefused("password_incorrect", 400)
    blockers = blockers_for(user)
    if blockers:
        raise AccountDeletionRefused("account_deletion_blocked", 409, blockers=list(blockers))
    apple_subject = (
        OAuthIdentity.objects.filter(user=user, provider=OAuthIdentity.Provider.APPLE)
        .values_list("subject", flat=True)
        .first()
    )
    if apple_subject is not None:
        if not apple_authorization_code:
            raise AccountDeletionRefused("apple_authorization_required", 409)
        try:
            apple_revoke.revoke_with_authorization_code(
                apple_authorization_code, apple_subject=apple_subject
            )
        except apple_revoke.AppleRevokeRefused as exc:
            raise AccountDeletionRefused("apple_authorization_refused", 400) from exc
        except apple_revoke.AppleRevokeUnavailable as exc:
            raise AccountDeletionRefused("apple_revoke_unavailable", 503) from exc

    with transaction.atomic():
        locked = (
            get_user_model()
            .objects.select_for_update(no_key=True)
            .filter(pk=user.pk, is_active=True)
            .first()
        )
        if locked is None:
            raise AccountDeletionRefused("account_deleted", 410)
        blockers = blockers_for(locked)
        if blockers:
            raise AccountDeletionRefused(
                "account_deletion_blocked", 409, blockers=list(blockers)
            )
        _erase(locked)


def _erase(user) -> None:
    from apps.discovery.models import PublicProfile, RouteAlert
    from apps.notifications.models import (
        Notification,
        NotificationPreference,
        OutboundMessage,
        PushDevice,
    )
    from apps.notifications.outbox import cancel_message

    sessions.end_all_sessions(user)
    PushDevice.objects.filter(user=user).delete()
    Notification.objects.filter(recipient=user).delete()
    NotificationPreference.objects.filter(user=user).delete()
    for key in OutboundMessage.objects.filter(
        recipient_user=user, status=OutboundMessage.Status.PENDING
    ).values_list("key", flat=True):
        cancel_message(key=key, reason="account_deleted")
    # Mail already sent stays as a record of what was sent, without the address.
    OutboundMessage.objects.filter(recipient_user=user).update(
        to_email=f"deleted-{user.pk}@{DELETED_EMAIL_DOMAIN}"
    )
    RouteAlert.objects.filter(user=user).delete()
    # Other members' alerts that follow this member stop: there is nothing
    # left for them to follow.
    RouteAlert.objects.filter(subject_user=user, is_active=True).update(
        is_active=False, deactivated_at=timezone.now()
    )
    PublicProfile.objects.filter(user=user).delete()
    photos.erase(user)
    OAuthIdentity.objects.filter(user=user).delete()
    PasswordResetCode.objects.filter(user=user).delete()
    EmailVerificationCode.objects.filter(user=user).delete()

    user.email = f"deleted-{user.pk}@{DELETED_EMAIL_DOMAIN}"
    user.username = f"deleted-{user.pk}"
    user.full_name = ""
    user.first_name = ""
    user.last_name = ""
    user.phone = ""
    user.wilaya = ""
    user.preferred_language = ""
    user.is_active = False
    user.is_email_verified = False
    user.is_phone_verified = False
    user.deleted_at = timezone.now()
    user.set_unusable_password()
    user.save()
