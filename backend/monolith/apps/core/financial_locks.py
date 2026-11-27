"""Canonical row-lock acquisition for cross-domain financial transitions.

Only rows a transition needs are locked, but any rows it does need are acquired
in this order::

    DeliveryRequest/ParcelRequest
    -> Match (ascending id)
    -> Offer (ascending id)
    -> Journey
    -> JourneyLeg (position, id)
    -> KYC/proof/User eligibility witnesses (acceptance only)
    -> Deal
    -> DealLegAllocation (journey leg, id)
    -> DealRecipient
    -> DealArrivalReport (ascending id)
    -> DealHandoverCode (ascending id)
    -> Dispute (ascending id)
    -> Rating (ascending id)
    -> PaymentOrder (ascending id)
    -> PaymentAttempt (ascending id)
    -> PaymentProviderEvent
    -> PaymentRefund (ascending id)
    -> Payout
    -> the traveler's payout-method set (transaction advisory lock)
    -> TravelerPayoutMethod (ascending id)
    -> StripePayoutAccount (ascending id)
    -> FinanceHold / payout allocations / attempts / operations (ascending id)
    -> append-only ledger rows
    -> ScheduledJob

A Deal's money can sit in two obligations -- its balance order and the
posting-deposit order whose cash was credited into that balance. Any transition that reaches more than one acquires the complete set in
ascending id order before processing them in its domain-specific refund order.

H1 profile writers lock User, then the method set (`lock_payout_method_set`),
then methods only. Two of them come first through one more lock, the traveler's
Stripe account setup (`hold_payout_account_setup`, `lock_payout_account_setup`):
EUR onboarding holds it, before User, for its whole call, Stripe calls
included, and every EUR preference write takes it before User. So a preference
change and an onboarding call for one traveler never overlap: the change waits
for the onboarding call to answer, or the call waits and serves the change.
Nothing else takes it, so funding, refresh and webhooks never wait on Stripe. Funding takes the same set lock after the Deal aggregate, so
it reads a traveler's methods before or after a whole preference change, never
half of one. Profile writers never lock prior Deals;
future account refresh must enqueue work after commit instead of acquiring a
Deal while holding an account. Future multi-Deal disbursements must lock the
union table-by-table, never loop this single-Deal helper after taking Payout.

Provider-event and ScheduledJob claims are deliberately short transactions.
They commit before acquiring any business or finance rows, so they are never a
reverse edge into this graph *through the locks they ask for*. They are still a
reverse edge through the locks PostgreSQL takes on their behalf; see below.

**Lock strength: every row here is taken `FOR NO KEY UPDATE`.**

Django emits every foreign key as `DEFERRABLE INITIALLY DEFERRED`, so an
`INSERT` does not check its parents when it runs -- it checks them at `COMMIT`,
by executing one ``SELECT 1 FROM <parent> WHERE id = $1 FOR KEY SHARE`` per
foreign key. Those referential-integrity locks fire in constraint-creation
order, which is model field order, and no application code chooses it. For
``finance_provider_event`` that order is `PaymentAttempt` then `PaymentOrder` --
the exact inverse of the order above. A writer that acquires the canonical order
explicitly and a writer that acquires the inverse order implicitly at commit is
a lock cycle, and it is not fixable by reordering application statements,
because one of the two orders is the database's.

It is fixable by lock *strength*. `FOR KEY SHARE` conflicts with exactly one
row-lock mode, `FOR UPDATE`. `FOR NO KEY UPDATE` -- the mode a plain `UPDATE`
statement takes anyway -- still conflicts with `FOR SHARE`, `FOR NO KEY UPDATE`
and `FOR UPDATE`, so two writers still exclude each other exactly as before, but
it does *not* conflict with `FOR KEY SHARE`. Taking these rows `FOR NO KEY
UPDATE` therefore removes every implicit reverse edge at once while changing
nothing about what two writers are allowed to do concurrently.

Concretely: acquire rows in this module through `select_for_update(no_key=True)`
-- never a bare `select_for_update()`. The stronger mode buys only the right to
delete a locked row or change its primary key, and no writer in this graph does
either; every row here is append-only or updated in place. The same rule applies
to every service that locks one of these rows directly (`apps.finance`,
`apps.disputes`, `apps.trips`, `apps.parcels`, `apps.matching`, the
`apps.admin_panel` review services, and the `BusinessSettingsVersion` rows that
`PaymentOrder`/`PaymentAttempt` reference). It is asserted structurally by
`apps.finance.tests.test_phase8df_lock_order`, which walks those modules' ASTs.

**Phase 4 placement.** Everything Phase 4 adds sits between `Deal` and
`PaymentOrder`. That single decision is what keeps the new edges acyclic:

* Handover confirmation locks Deal then codes, never codes then Deal. The
  legacy `apps.verification` path, which did the opposite (`HandoverCode`
  before `Match`), was removed in L1A; only its history table remains.
* Dispute opening and protection expiry are the two writers that race for the
  same money. Both enter through `lock_deal_aggregate` and then take `Dispute`
  and `Payout` in this order, so one of them always blocks on the Deal row and
  the loser re-reads committed state instead of a stale snapshot.
* Cancellation, dispute resolution and payout release all reach finance rows
  only after the whole domain aggregate is held, exactly as Phase 3B's payment
  reconciliation does.

**Phase I1A placement.** `DealArrivalReport` is Deal-owned child data and sits
with `DealRecipient`, before handover codes. An early-arrival report and a
delivery confirmation can be submitted in the same second by the same traveler;
both enter through `lock_deal_lifecycle`, so the second one blocks on the Deal
row and then reads the first one's committed state. Nothing in the arrival path
reaches a finance row at all -- the payout floor is a Deal column frozen at
funding -- so it adds no new edge into the money graph.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

#: First key of the two-key advisory lock `lock_payout_method_set` takes. Two-key
#: advisory locks never collide with the one-key locks used elsewhere.
PAYOUT_METHOD_SET_LOCK = 51420301

#: First key of the two-key advisory lock on a traveler's Stripe account setup.
PAYOUT_ACCOUNT_SETUP_LOCK = 51420302


@dataclass(frozen=True, slots=True)
class LockedRequestGraph:
    request: object
    matches: tuple[object, ...]
    offers: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class LockedDealAggregate:
    request_graph: LockedRequestGraph
    journey: object
    journey_legs: tuple[object, ...]
    deal: object
    allocations: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class LockedLifecycleAggregate:
    """A Deal aggregate plus every Phase 4 row that can change its money.

    Used by handover confirmation, delivery-code release, cancellation after
    funding, dispute opening and resolution, and the payout release gate — that
    is, by every writer that has to agree with every other writer about what
    state the Deal is in.
    """

    deal_aggregate: LockedDealAggregate
    recipient: object | None
    handover_codes: tuple[object, ...]
    disputes: tuple[object, ...]
    ratings: tuple[object, ...]
    #: Phase I1A early-arrival claims, ascending id. Locked with the rest of
    #: the aggregate rather than by each caller, so the traveler's report, the
    #: sender's confirmation, delivery confirmation and the payout release gate
    #: all approach this row from the one documented direction.
    arrival_reports: tuple[object, ...] = ()

    @property
    def deal(self):
        return self.deal_aggregate.deal

    @property
    def request_graph(self) -> LockedRequestGraph:
        return self.deal_aggregate.request_graph

    def active_dispute(self):
        """The one dispute that is currently freezing money, if any."""

        from apps.disputes.models import Dispute

        for row in self.disputes:
            if row.status in Dispute.ACTIVE_STATUSES:
                return row
        return None

    def open_arrival_report(self):
        """The one early-arrival claim still awaiting the sender, if any."""

        from apps.deals.models import DealArrivalReport

        for row in self.arrival_reports:
            if row.status in DealArrivalReport.OPEN_STATUSES:
                return row
        return None

    def confirmed_arrival_report(self):
        from apps.deals.models import DealArrivalReport

        for row in self.arrival_reports:
            if row.status == DealArrivalReport.Status.CONFIRMED:
                return row
        return None

    def code(self, kind: str):
        """The live code of one kind, or None."""

        from apps.handover.models import DealHandoverCode

        for row in self.handover_codes:
            if row.kind == kind and row.status in DealHandoverCode.LIVE_STATUSES:
                return row
        return None


@dataclass(frozen=True, slots=True)
class LockedPaymentAggregate:
    order: object
    request_graph: LockedRequestGraph | None
    deal_aggregate: LockedDealAggregate | None


def lock_request_graph(
    request_id: int, *, include_negotiation: bool
) -> LockedRequestGraph:
    from apps.matching.models import Match, Offer
    from apps.parcels.models import DeliveryRequest

    request = (
        DeliveryRequest.objects.select_for_update(
            no_key=True, of=("self", "parcelrequest_ptr")
        )
        .select_related("parcelrequest_ptr")
        .get(pk=request_id)
    )
    if not include_negotiation:
        return LockedRequestGraph(request=request, matches=(), offers=())

    matches = tuple(
        Match.objects.select_for_update(no_key=True)
        .filter(parcel_id=request_id)
        .order_by("pk")
    )
    offers = tuple(
        Offer.objects.select_for_update(no_key=True)
        .filter(match_id__in=[row.pk for row in matches])
        .order_by("pk")
    )
    return LockedRequestGraph(request=request, matches=matches, offers=offers)


def lock_deal_aggregate(deal_id: int) -> LockedDealAggregate:
    from apps.deals.models import Deal, DealLegAllocation
    from apps.trips.models import Journey, JourneyLeg

    snapshot = Deal.objects.values("delivery_request_id", "journey_id").get(pk=deal_id)
    request_graph = lock_request_graph(
        snapshot["delivery_request_id"], include_negotiation=True
    )
    journey = Journey.objects.select_for_update(no_key=True).get(
        pk=snapshot["journey_id"]
    )
    journey_legs = tuple(
        JourneyLeg.objects.select_for_update(no_key=True)
        .filter(journey_id=journey.pk)
        .order_by("position", "pk")
    )
    deal = Deal.objects.select_for_update(no_key=True).get(pk=deal_id)
    allocations = tuple(
        DealLegAllocation.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id)
        .order_by("journey_leg_id", "pk")
    )
    return LockedDealAggregate(
        request_graph=request_graph,
        journey=journey,
        journey_legs=journey_legs,
        deal=deal,
        allocations=allocations,
    )


def lock_deal_lifecycle(deal_id: int) -> LockedLifecycleAggregate:
    """The Deal aggregate plus recipient, handover codes, disputes and ratings.

    Every Phase 4 writer starts here. Taking the whole set — even the parts a
    given transition does not need — is what makes the ordering a property of
    one function rather than of every caller's discipline, and it is why the
    protection-expiry/dispute race has no losing interleaving: whichever
    transaction arrives second sees the first one's committed rows.
    """

    from apps.deals.models import DealArrivalReport, DealRecipient
    from apps.disputes.models import Dispute
    from apps.handover.models import DealHandoverCode
    from apps.ratings.models import Rating

    deal_aggregate = lock_deal_aggregate(deal_id)
    recipient = (
        DealRecipient.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id)
        .first()
    )
    arrival_reports = tuple(
        DealArrivalReport.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id)
        .order_by("pk")
    )
    handover_codes = tuple(
        DealHandoverCode.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id)
        .order_by("pk")
    )
    disputes = tuple(
        Dispute.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id)
        .order_by("pk")
    )
    ratings = tuple(
        Rating.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id)
        .order_by("pk")
    )
    return LockedLifecycleAggregate(
        deal_aggregate=deal_aggregate,
        recipient=recipient,
        handover_codes=handover_codes,
        disputes=disputes,
        ratings=ratings,
        arrival_reports=arrival_reports,
    )


def lock_payment_order_aggregate(order_id: int) -> LockedPaymentAggregate:
    from apps.finance.models import PaymentOrder

    snapshot = PaymentOrder.objects.values(
        "delivery_request_id",
        "deal_id",
    ).get(pk=order_id)
    deal_aggregate = None
    request_graph = None
    if snapshot["deal_id"] is not None:
        deal_aggregate = lock_deal_aggregate(snapshot["deal_id"])
        request_graph = deal_aggregate.request_graph
    elif snapshot["delivery_request_id"] is not None:
        request_graph = lock_request_graph(
            snapshot["delivery_request_id"], include_negotiation=False
        )
    order = PaymentOrder.objects.select_for_update(no_key=True).get(pk=order_id)
    return LockedPaymentAggregate(
        order=order,
        request_graph=request_graph,
        deal_aggregate=deal_aggregate,
    )


@contextmanager
def hold_payout_account_setup(traveler_id: int):
    """Hold a traveler's Stripe account setup across a whole onboarding call.

    A session-level advisory lock, taken before User and released when the
    call answers, so it spans the call's own short transactions and the Stripe
    calls between them: the account-creation intent is committed before its
    POST, as recovery needs, and no preference change can commit between that
    intent and the POST. A process that dies drops its connection and the
    lock with it. The lock nests, so a call inside an onboarding call that
    takes it again does not wait for itself.
    """

    from django.db import connection

    if connection.vendor != "postgresql":
        yield
        return
    key = [PAYOUT_ACCOUNT_SETUP_LOCK, traveler_id & 0x7FFFFFFF]
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s, %s)", key)
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", key)


def lock_payout_account_setup(traveler_id: int) -> None:
    """Wait for any onboarding call of this traveler, for this transaction.

    Every EUR preference write takes it before User, so a change either
    commits before an onboarding call reads the declaration or waits until
    the call has answered.
    """

    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [PAYOUT_ACCOUNT_SETUP_LOCK, traveler_id & 0x7FFFFFFF],
            )


def models_q_deal_or_deposit(deal_id: int, request_id: int):
    """Match a Deal's balance order and the posting deposit credited into it.

    A query helper, not a lock helper — it says which two obligations hold one
    Deal's money, which is what an evidence bundle or a finance report needs to
    ask for. It deliberately does not acquire anything: the lock helper that
    used to live beside it documented an ascending-id order that no caller took
    and that `apps.finance.settlement` contradicts, so it was removed rather
    than left as a trap for the first caller who trusted it.
    """

    from django.db.models import Q

    from apps.finance.models import PaymentOrder

    return Q(deal_id=deal_id) | Q(
        delivery_request_id=request_id,
        purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
    )


def lock_payout_method_set(traveler_id: int) -> tuple:
    """Lock a traveler's payout methods as one set, then each row, ascending id.

    Funding reads which methods are enabled while it holds the Deal aggregate,
    so it cannot take the User row that serializes profile writers. Row locks
    alone do not protect the set: a change that disables one row and inserts
    another makes funding wait for the row it updated, but the inserted row
    stays invisible to a funding query that started before the change
    committed, so funding would read a set with no enabled method that never
    existed. Funding and every writer that adds a method or changes which are
    enabled take this lock first; a writer that only updates one existing row
    (readiness, a new version) is already serialized with funding by that row's
    lock. Travelers whose ids share a slot only wait for each other.
    """

    from django.db import connection

    from apps.finance.models import TravelerPayoutMethod

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [PAYOUT_METHOD_SET_LOCK, traveler_id & 0x7FFFFFFF],
            )
    return tuple(
        TravelerPayoutMethod.objects.select_for_update(no_key=True)
        .filter(traveler_id=traveler_id)
        .order_by("pk")
    )
