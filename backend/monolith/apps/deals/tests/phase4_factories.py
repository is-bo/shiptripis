"""Shared scaffolding for the Phase 4 handover, protection and dispute tests.

`apps.finance.tests.factories.build_scenario` already produces the smallest
world in which real money can move: one sender, one KYC-approved traveler, one
active journey and one matchable V1 delivery request. Phase 4 needs that world
carried several steps further -- funded, with a recipient, picked up, past the
safety buffer, delivered -- and it needs every step to run through the real
services rather than through hand-written rows.

That last point is the whole design of this module. A test that fabricated a
`Deal` with `status="delivery_ready"` and a hand-made code row would pass while
the actual release path silently stopped arming the recipient's email. Every
helper here drives the production service, so a regression in the service breaks
the fixture, loudly, before it can break an assertion.

**Time.** Two techniques, used for different jobs. `freeze_at` patches
`django.utils.timezone.now` so a test can stand exactly on a boundary -- one
second before the 30-minute buffer closes, and exactly on it. `rewind_deal`
moves the Deal's own stored deadlines into the past, which is what a test about
a long window wants when the boundary itself is not the subject. Neither ever
shortens a window inside the service: the services compare against stored
instants under a row lock, and that is precisely what these tests exist to
check.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest import mock

from django.utils import timezone

from apps.deals.models import Deal
from apps.deals.recipient import set_recipient
from apps.finance.tests.factories import Scenario, build_scenario, pay_order_with_mock
from apps.handover.models import DealHandoverCode
from apps.handover.services import reveal_code, submit_code

DEFAULT_RECIPIENT = {
    "full_name": "Recipient Example",
    "email": "recipient@example.invalid",
    "phone": "+213555000111",
    "delivery_note": "Ring the top bell.",
}


@contextlib.contextmanager
def freeze_at(instant: datetime):
    """Run a block with `timezone.now()` pinned to `instant`.

    Every Phase 4 service reads the clock through `django.utils.timezone.now`,
    so patching it there covers the services, the lifecycle module and the job
    handlers at once. `auto_now_add` columns follow the same clock, which keeps
    a frozen-time fixture internally consistent.
    """

    with mock.patch("django.utils.timezone.now", return_value=instant):
        yield instant


def rewind_deal(deal: Deal, delta: timedelta) -> Deal:
    """Move a Deal's stored Phase 4 deadlines back by `delta`.

    Used when the subject of a test is what happens *after* a window, not the
    boundary itself. It edits the columns directly and on purpose: this is the
    one place in the codebase allowed to, because it is simulating the passage
    of time rather than performing a transition.
    """

    fields = [
        "pickup_confirmed_at",
        "delivery_code_available_at",
        "delivery_code_released_at",
        "delivery_confirmed_at",
        "protection_ends_at",
        "rating_window_ends_at",
        # Phase I1A. The funded arrival basis is one of this Deal's stored
        # deadlines, so simulating the passage of time has to move it with the
        # rest of them. Leaving it behind would not be "48 hours later" -- it
        # would be a Deal delivered 48 hours before it was scheduled to arrive,
        # which is a different scenario and one the arrival floor deliberately
        # holds back.
        "funded_scheduled_arrival_floor_at",
    ]
    updates = {}
    for name in fields:
        value = getattr(deal, name)
        if value is not None:
            updates[name] = value - delta
    if updates:
        Deal.objects.filter(pk=deal.pk).update(**updates)
    deal.refresh_from_db()
    return deal


@dataclass
class Phase4Scenario:
    """A `Scenario` plus whatever Phase 4 state the test asked to reach."""

    base: Scenario
    pickup_code: str = ""
    delivery_code: str = ""

    @property
    def deal(self) -> Deal:
        assert self.base.deal is not None, "The scenario has no Deal yet."
        self.base.deal.refresh_from_db()
        return self.base.deal

    @property
    def sender(self):
        return self.base.sender

    @property
    def traveler(self):
        return self.base.traveler

    @property
    def outsider(self):
        return self.base.outsider

    @property
    def admin(self):
        return self.base.admin

    @property
    def delivery_request(self):
        return self.base.delivery_request


def enable_mock_rail() -> None:
    """Turn the test-only payment rail on in the active settings revision.

    `PAYMENTS_ALLOW_MOCK_PROVIDER` is already true under the test settings, and
    production refuses to boot with it set; this is the second switch, the
    business-policy one, and Phase 3's tests flip it the same way.
    """

    from copy import deepcopy

    from apps.core.business_settings import get_active_business_settings
    from apps.core.models import BusinessSettingsVersion

    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(policy=policy)


def fund_scenario(client, *, prefix: str = "p4", reward_eur_cents: int = 2_000):
    """Accept an offer and pay its balance through the real mock rail."""

    enable_mock_rail()
    scenario = build_scenario(prefix=prefix)
    scenario.accept(reward_eur_cents=reward_eur_cents)
    pay_order_with_mock(client, scenario.balance_order())
    scenario.deal.refresh_from_db()
    assert scenario.deal.status == Deal.Status.FUNDED, scenario.deal.status
    return Phase4Scenario(base=scenario)


def record_recipient(scenario: Phase4Scenario, **overrides) -> Phase4Scenario:
    """Set the recipient, which is also the gate into `pickup_ready`."""

    payload = {**DEFAULT_RECIPIENT, **overrides}
    set_recipient(
        deal_id=scenario.deal.pk, actor_id=scenario.sender.pk, **payload
    )
    assert scenario.deal.status == Deal.Status.PICKUP_READY, scenario.deal.status
    return scenario


def reveal_pickup_code(scenario: Phase4Scenario) -> str:
    revealed = reveal_code(
        deal_id=scenario.deal.pk,
        kind=DealHandoverCode.Kind.PICKUP,
        actor_id=scenario.sender.pk,
    )
    scenario.pickup_code = revealed.code
    return revealed.code


def confirm_pickup(scenario: Phase4Scenario, *, at: datetime | None = None):
    """Hand the sender's code to the traveler and have them submit it."""

    code = scenario.pickup_code or reveal_pickup_code(scenario)
    if at is None:
        submit_code(
            deal_id=scenario.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=scenario.traveler.pk,
            submitted_code=code,
        )
    else:
        with freeze_at(at):
            submit_code(
                deal_id=scenario.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.traveler.pk,
                submitted_code=code,
            )
    assert scenario.deal.status == Deal.Status.IN_TRANSIT, scenario.deal.status
    return scenario


def release_delivery_code(scenario: Phase4Scenario) -> str:
    """Run the durable release at the exact instant the buffer closes."""

    from apps.handover.services import release_delivery_code as _release

    deal = scenario.deal
    assert deal.delivery_code_available_at is not None
    with freeze_at(deal.delivery_code_available_at):
        _release(deal_id=deal.pk)
        # Inside the same frozen instant: revealing at the real wall clock
        # would be thirty minutes *before* the window closes and would be
        # refused, which is the service behaving correctly.
        revealed = reveal_code(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.DELIVERY,
            actor_id=scenario.sender.pk,
        )
    scenario.delivery_code = revealed.code
    return revealed.code


def confirm_delivery(scenario: Phase4Scenario):
    """Recipient reads the code to the traveler; the traveler submits it."""

    code = scenario.delivery_code or release_delivery_code(scenario)
    submit_code(
        deal_id=scenario.deal.pk,
        kind=DealHandoverCode.Kind.DELIVERY,
        actor_id=scenario.traveler.pk,
        submitted_code=code,
    )
    assert scenario.deal.status == Deal.Status.PROTECTION_WINDOW, scenario.deal.status
    return scenario


def delivered_scenario(client, *, prefix: str = "p4") -> Phase4Scenario:
    """The full happy path: funded, recipient, pickup, buffer, delivery."""

    scenario = fund_scenario(client, prefix=prefix)
    record_recipient(scenario)
    confirm_pickup(scenario)
    release_delivery_code(scenario)
    confirm_delivery(scenario)
    return scenario


def past_protection(scenario: Phase4Scenario) -> Phase4Scenario:
    """Move the Deal so its protection window has just closed."""

    deal = scenario.deal
    assert deal.protection_ends_at is not None
    # `rewind_deal` subtracts, so the delta must be positive to move the
    # deadline into the past. Written the other way round it pushed every
    # deadline 48 hours further out and any test using it would have passed
    # while proving nothing.
    elapsed = deal.protection_ends_at - timezone.now() + timedelta(seconds=1)
    rewind_deal(deal, elapsed)
    assert scenario.deal.protection_ends_at < timezone.now()
    return scenario
