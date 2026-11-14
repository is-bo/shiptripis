"""L11A: one tracking number per parcel (spec 16, plan L11A).

The number is created with the request, never changes, is shown by every
server surface that used to print the old deal reference, and is searchable by
staff. It is never on a public card, a candidate list or the guest payment page
(those assertions live in the existing privacy tests).
"""

from __future__ import annotations

import re
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation
from rest_framework.test import APIClient

from apps.admin_panel.permissions import assign_admin_roles
from apps.deals.models import Deal
from apps.deals.cancellation import cancel_funded_deal
from apps.deals.tests.phase4_factories import (
    delivered_scenario,
    enable_mock_rail,
    fund_scenario,
)
from apps.disputes.models import Dispute
from apps.finance.models import PaymentAttempt, PaymentRefund, Payout
from apps.finance.services import (
    _enqueue_payment_failed_email,
    _enqueue_refund_status_email,
    create_guest_link,
    ensure_posting_deposit_order,
)
from apps.finance.tests.factories import build_scenario
from apps.matching.v1_services import accept_offer, create_sender_offer
from apps.notifications import outbox
from apps.notifications.models import OutboundMessage
from apps.parcels import tracking
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.admin_panel.tests.two_step_helpers import staff_login

NUMBER = re.compile(r"^WSL-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{8}$")


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _staff(user):
    assign_admin_roles(user, ["super_admin"], elevate_super_admin=True)
    return user


#: The fields a second request for the same sender copies from the first.
_REQUEST_FIELDS = (
    "sender",
    "kind",
    "schema_version",
    "status",
    "pickup_location",
    "delivery_location",
    "ready_window_start",
    "ready_window_end",
    "deadline_at",
    "actual_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "declared_value_eur_cents",
    "traveler_reward_eur_cents",
    "title",
    "description",
    "category",
    "item_type",
    "description_is_accurate",
    "item_is_legal",
    "no_prohibited_goods",
    "declared_value_is_accurate",
    "customs_responsibilities_understood",
)


def _request_like(template: DeliveryRequest, **overrides) -> DeliveryRequest:
    values = {field: getattr(template, field) for field in _REQUEST_FIELDS}
    values.update(overrides)
    return DeliveryRequest(**values)


def _second_deal(scenario) -> Deal:
    """A second request and deal between the same two people."""

    request = _request_like(scenario.delivery_request, status=ParcelRequest.Status.OPEN)
    request.save()
    offer = create_sender_offer(
        sender=scenario.sender,
        delivery_request=request,
        journey=scenario.journey,
        start_leg_id=scenario.leg.pk,
        end_leg_id=scenario.leg.pk,
        traveler_reward_eur_cents=2_000,
    )
    return accept_offer(pending_offer=offer, actor=scenario.traveler).deal


# --- the module ---------------------------------------------------------------


class FormatTests(SimpleTestCase):
    def test_the_alphabet_has_no_lookalike_characters(self):
        assert tracking.ALPHABET == "23456789ABCDEFGHJKMNPQRSTVWXYZ"
        assert len(set(tracking.ALPHABET)) == 30
        assert not set("01ILOU") & set(tracking.ALPHABET)

    def test_a_generated_number_is_the_prefix_and_eight_characters(self):
        numbers = {tracking.generate() for _ in range(500)}
        assert len(numbers) == 500
        for number in numbers:
            assert NUMBER.match(number), number
            assert len(number) == tracking.MAX_LENGTH == 12
            assert tracking.is_valid(number)

    def test_typed_forms_normalise_to_the_stored_one(self):
        for typed in (
            "WSL-7K3M9QXD",
            "wsl-7k3m9qxd",
            "WSL7K3M9QXD",
            "wsl7k3m9qxd",
            "7K3M9QXD",
            "7k3m9qxd",
            "  WSL-7K3M9QXD  ",
            "\t7k3m9qxd\n",
            # As copied out of a right-to-left email, isolates included.
            "⁦WSL-7K3M9QXD⁩",
        ):
            assert tracking.normalize(typed) == "WSL-7K3M9QXD", repr(typed)

    def test_anything_else_is_not_a_number(self):
        for typed in (
            "",
            "   ",
            None,
            42,
            "WSL-7K3M9QX",  # seven characters
            "WSL-7K3M9QXDA",  # nine
            "7K3M9QX",
            "WSL-7K3M9QX0",  # zero
            "WSL-7K3M9QX1",  # one
            "WSL-7K3M9QXI",
            "WSL-7K3M9QXL",
            "WSL-7K3M9QXO",
            "WSL-7K3M9QXU",
            "WSL_7K3M9QXD",
            "WSL--7K3M9QXD",
            "WSL 7K3M9QXD",
            "XSL-7K3M9QXD",
            "7K3M 9QXD",
            "DEAL-42",
            "TR-14",
            "01234567-89ab-4cde-0123-456789abcdef",
        ):
            assert tracking.normalize(typed) is None, repr(typed)
        assert not tracking.is_valid("wsl-7k3m9qxd")
        assert not tracking.is_valid("7K3M9QXD")


class InsertTests(TestCase):
    def setUp(self):
        self.scenario = build_scenario(prefix="l11a-insert")
        self.existing = self.scenario.delivery_request.tracking_number

    def test_a_new_request_has_a_number_from_its_first_save(self):
        request = self.scenario.delivery_request
        assert NUMBER.match(request.tracking_number)
        stored = ParcelRequest.objects.get(pk=request.pk).tracking_number
        assert stored == request.tracking_number == tracking.for_request(request)

    def test_a_collision_draws_another_number_and_succeeds(self):
        fresh = "WSL-22222222"
        request = _request_like(
            self.scenario.delivery_request, tracking_number=self.existing
        )
        with mock.patch.object(tracking, "generate", return_value=fresh) as drawn:
            request.save()
        assert drawn.call_count == 1
        request.refresh_from_db()
        assert request.tracking_number == fresh
        assert DeliveryRequest.objects.filter(tracking_number=fresh).count() == 1

    def test_five_collisions_give_up_and_leave_nothing_behind(self):
        before = ParcelRequest.objects.count()
        request = _request_like(
            self.scenario.delivery_request, tracking_number=self.existing
        )
        with mock.patch.object(
            tracking, "generate", return_value=self.existing
        ) as drawn:
            with self.assertRaises(tracking.TrackingNumberUnavailable):
                request.save()
        assert drawn.call_count == tracking.MAX_ATTEMPTS - 1
        # Each attempt ran in its own savepoint: the transaction is still
        # usable and holds no half-written row.
        assert ParcelRequest.objects.count() == before

    def test_an_unrelated_integrity_error_is_not_retried(self):
        request = _request_like(self.scenario.delivery_request)

        def insert():
            raise IntegrityError("some other constraint")

        with mock.patch.object(tracking, "generate") as drawn:
            with self.assertRaises(IntegrityError):
                tracking.insert_with_new_number(request, insert)
        assert drawn.call_count == 0

    def test_a_supplied_value_that_is_not_a_number_is_refused(self):
        request = _request_like(
            self.scenario.delivery_request, tracking_number="DEAL-42"
        )
        with self.assertRaises(ValidationError):
            request.save()

    def test_a_saved_number_never_changes(self):
        request = DeliveryRequest.objects.get(pk=self.scenario.delivery_request.pk)
        request.tracking_number = tracking.generate()
        with self.assertRaises(ValidationError):
            request.save()
        with self.assertRaises(ValidationError):
            request.save(update_fields=["tracking_number"])
        # The same instance, changed after its own first save.
        fresh = _request_like(self.scenario.delivery_request)
        fresh.save()
        fresh.tracking_number = tracking.generate()
        with self.assertRaises(ValidationError):
            fresh.save()
        assert (
            ParcelRequest.objects.get(pk=request.pk).tracking_number == self.existing
        )

    def test_an_ordinary_save_keeps_the_number(self):
        request = DeliveryRequest.objects.get(pk=self.scenario.delivery_request.pk)
        request.title = "Renamed"
        request.save()
        deferred = DeliveryRequest.objects.only("pk", "title", "sender").get(
            pk=request.pk
        )
        deferred.title = "Renamed again"
        deferred.save(update_fields=["title"])
        assert (
            ParcelRequest.objects.get(pk=request.pk).tracking_number == self.existing
        )


class ReopenedRequestTests(TestCase):
    def test_a_reopened_request_keeps_its_number_on_the_next_deal(self):
        scenario = build_scenario(prefix="l11a-reopen")
        number = scenario.delivery_request.tracking_number
        first = scenario.accept()
        cancelled = _client(scenario.sender).post(
            reverse("deals-cancel", args=[first.pk]), format="json"
        )
        assert cancelled.status_code == 200, cancelled.data
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.status == ParcelRequest.Status.OPEN
        assert scenario.delivery_request.tracking_number == number

        scenario.offer = None
        second = scenario.accept()
        assert second.pk != first.pk
        assert tracking.for_deal(first) == tracking.for_deal(second) == number
        for deal in (first, second):
            payload = _client(scenario.traveler).get(
                reverse("deals-detail", args=[deal.pk])
            )
            assert payload.status_code == 200, payload.data
            assert payload.data["tracking_number"] == number


# --- payloads -------------------------------------------------------------------


class PayloadTests(TestCase):
    def setUp(self):
        self.scenario = build_scenario(prefix="l11a-payload")
        self.number = self.scenario.delivery_request.tracking_number

    def test_the_sender_sees_it_on_their_request_and_nobody_else_does(self):
        sender = _client(self.scenario.sender)
        detail = sender.get(
            reverse("parcels-detail", args=[self.scenario.delivery_request.pk])
        )
        listing = sender.get(reverse("parcels-list"))
        assert detail.data["tracking_number"] == self.number
        assert listing.data[0]["tracking_number"] == self.number
        for stranger in (self.scenario.traveler, self.scenario.outsider):
            response = _client(stranger).get(
                reverse("parcels-detail", args=[self.scenario.delivery_request.pk])
            )
            assert response.status_code == 200, response.data
            assert "tracking_number" not in response.data
            assert self.number not in str(response.data)

    def test_both_people_of_a_proposal_see_it(self):
        offer = self.scenario.propose()
        for user in (self.scenario.sender, self.scenario.traveler):
            client = _client(user)
            listing = client.get(reverse("matches-list"))
            detail = client.get(reverse("matches-detail", args=[offer.match_id]))
            assert listing.status_code == 200 and detail.status_code == 200
            rows = listing.data["results"] if isinstance(listing.data, dict) else listing.data
            assert rows[0]["tracking_number"] == self.number
            assert rows[0]["latest_offer"]["tracking_number"] == self.number
            assert detail.data["tracking_number"] == self.number

    def test_the_proposal_response_carries_it(self):
        enable_mock_rail()
        quote = _client(self.scenario.sender).post(
            reverse("matches-quote-v1"),
            {
                "parcel_id": self.scenario.delivery_request.pk,
                "journey_id": self.scenario.journey.pk,
            },
            format="json",
        )
        assert quote.status_code == 200, quote.data
        proposal = _client(self.scenario.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.scenario.delivery_request.pk,
                "journey_id": self.scenario.journey.pk,
                "start_leg_id": quote.data["journey"]["start_leg_id"],
                "end_leg_id": quote.data["journey"]["end_leg_id"],
                "traveler_reward_eur_cents": 2_000,
            },
            format="json",
        )
        assert proposal.status_code == 201, proposal.data
        assert proposal.data["tracking_number"] == self.number
        accepted = _client(self.scenario.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        assert accepted.status_code == 201, accepted.data
        assert accepted.data["tracking_number"] == self.number

    def test_deal_payment_order_payout_and_dispute_payloads_carry_it(self):
        deal = self.scenario.accept()
        order = self.scenario.balance_order()
        Payout.objects.create(
            deal=deal,
            traveler=self.scenario.traveler,
            amount_eur_cents=2_000,
            method=Payout.Method.MANUAL,
        )
        dispute = Dispute.objects.create(
            deal=deal,
            opened_by=self.scenario.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            status=Dispute.Status.UNDER_REVIEW,
            category=Dispute.Category.DAMAGED,
            reason_text="Crushed corner.",
        )
        sender = _client(self.scenario.sender)
        traveler = _client(self.scenario.traveler)

        for client in (sender, traveler):
            listing = client.get(reverse("deals-list"))
            rows = listing.data["results"] if isinstance(listing.data, dict) else listing.data
            assert rows[0]["tracking_number"] == self.number
            assert (
                client.get(reverse("deals-detail", args=[deal.pk])).data[
                    "tracking_number"
                ]
                == self.number
            )
            payment = client.get(reverse("finance-deal-payment", args=[deal.pk]))
            assert payment.data["tracking_number"] == self.number
            disputes = client.get(reverse("disputes-list", args=[deal.pk]))
            assert disputes.data[0]["tracking_number"] == self.number
            assert (
                client.get(reverse("disputes-detail", args=[dispute.pk])).data[
                    "tracking_number"
                ]
                == self.number
            )

        orders = sender.get(reverse("finance-orders"))
        rows = orders.data["results"] if isinstance(orders.data, dict) else orders.data
        assert {row["tracking_number"] for row in rows} == {self.number}
        detail = sender.get(
            reverse("finance-order-detail", args=[order.public_reference])
        )
        assert detail.data["tracking_number"] == self.number

        payouts = traveler.get(reverse("finance-payouts"))
        row = payouts.data["results"][0]
        assert row["tracking_number"] == self.number
        assert row["mobile"]["tracking_number"] == self.number
        payout_detail = traveler.get(
            reverse("finance-payout-detail", args=[row["reference"]])
        )
        assert payout_detail.data["tracking_number"] == self.number

    def test_the_deposit_order_names_the_request(self):
        scenario = build_scenario(prefix="l11a-deposit", open_request=False)
        order = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request
        )
        assert order.tracking_number == scenario.delivery_request.tracking_number
        response = _client(scenario.sender).get(
            reverse("finance-posting-deposit", args=[scenario.delivery_request.pk])
        )
        assert response.status_code == 200, response.data
        assert (
            response.data["order"]["tracking_number"]
            == scenario.delivery_request.tracking_number
        )


class ListQueryCountTests(TestCase):
    """Adding the number to a list costs no query per row."""

    def _count(self, client, url) -> int:
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url)
        assert response.status_code == 200, response.data
        return len(queries.captured_queries)

    def _lists(self, scenario):
        sender = _client(scenario.sender)
        traveler = _client(scenario.traveler)
        return {
            "parcels": (sender, reverse("parcels-list")),
            "matches": (sender, reverse("matches-list")),
            "deals": (traveler, reverse("deals-list")),
            "orders": (sender, reverse("finance-orders")),
            "payouts": (traveler, reverse("finance-payouts")),
        }

    def test_each_touched_list_costs_the_same_for_one_row_or_two(self):
        scenario = build_scenario(prefix="l11a-count")
        deals = [scenario.accept()]
        Payout.objects.create(
            deal=deals[0],
            traveler=scenario.traveler,
            amount_eur_cents=2_000,
            method=Payout.Method.MANUAL,
        )
        one = {
            name: self._count(client, url)
            for name, (client, url) in self._lists(scenario).items()
        }
        deals.append(_second_deal(scenario))
        Payout.objects.create(
            deal=deals[1],
            traveler=scenario.traveler,
            amount_eur_cents=2_000,
            method=Payout.Method.MANUAL,
        )
        two = {
            name: self._count(client, url)
            for name, (client, url) in self._lists(scenario).items()
        }
        assert one == two, (one, two)


# --- emails ---------------------------------------------------------------------


DEAL_EMAIL_KINDS = (
    OutboundMessage.Kind.PICKUP_CONFIRMED,
    OutboundMessage.Kind.DELIVERY_CODE_RELEASED,
    OutboundMessage.Kind.DELIVERY_CONFIRMED,
    OutboundMessage.Kind.PROTECTION_ENDING,
    OutboundMessage.Kind.PROTECTION_ENDED,
    OutboundMessage.Kind.DISPUTE_OPENED,
    OutboundMessage.Kind.EVIDENCE_REQUEST,
    OutboundMessage.Kind.DISPUTE_RESOLVED,
    OutboundMessage.Kind.PAYOUT_STATUS,
    OutboundMessage.Kind.DEAL_CANCELLED,
    OutboundMessage.Kind.RATING_AVAILABLE,
    OutboundMessage.Kind.PAYMENT_REQUIRED,
    OutboundMessage.Kind.PAYMENT_PROCESSING,
    OutboundMessage.Kind.PAYMENT_FAILED,
    OutboundMessage.Kind.PAYMENT_SUCCEEDED,
    OutboundMessage.Kind.REFUND_STATUS,
)

LABELS = {"en": "Tracking number", "fr": "Numéro de suivi", "ar": "رقم التتبع"}


class EmailRenderingTests(TestCase):
    def test_every_parcel_email_names_the_number_in_each_language(self):
        for language, label in LABELS.items():
            for kind in DEAL_EMAIL_KINDS:
                with self.subTest(kind=kind, language=language):
                    message = OutboundMessage(
                        kind=kind,
                        language=language,
                        context={"tracking_number": "WSL-7K3M9QXD"},
                    )
                    _, text, html = outbox.render_parts(message)
                    for part in (text, html):
                        assert "WSL-7K3M9QXD" in part
                        assert label in part
            with self.subTest(kind="recipient_delivery_code", language=language):
                # Rendered without its secret: the code itself is resolved
                # only at dispatch.
                with translation.override(language):
                    document = outbox._recipient_delivery_code(
                        {"tracking_number": "WSL-7K3M9QXD"}, "123456"
                    )
                assert dict(document.facts)[label] == "WSL-7K3M9QXD"

    def test_the_guest_receipt_never_names_the_number(self):
        message = OutboundMessage(
            kind=OutboundMessage.Kind.GUEST_PAYMENT,
            context={
                "status": "succeeded",
                "tracking_number": "WSL-7K3M9QXD",
                "payment_reference": "PAY-1",
                "amount_eur_cents": 1_200,
            },
        )
        _, text, html = outbox.render_parts(message)
        assert "WSL-" not in text + html


class EmailContextTests(TestCase):
    def test_a_cancelled_deal_tells_both_people_its_number(self):
        scenario = fund_scenario(self.client, prefix="l11a-mail-cancel")
        deal = scenario.deal
        cancel_funded_deal(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        messages = OutboundMessage.objects.filter(
            kind=OutboundMessage.Kind.DEAL_CANCELLED, deal=deal
        )
        assert messages.count() == 2
        for message in messages:
            assert message.context["tracking_number"] == tracking.for_deal(deal)

    def test_the_owner_hears_the_number_and_the_guest_never_does(self):
        scenario = build_scenario(prefix="l11a-mail-guest")
        scenario.accept()
        order = scenario.balance_order()
        issued = create_guest_link(order_id=order.pk, actor_id=scenario.sender.pk)
        attempt = PaymentAttempt.objects.create(
            order=order,
            provider="stripe",
            amount_eur_cents=order.amount_eur_cents,
            payment_currency="EUR",
            provider_amount_minor=order.amount_eur_cents,
            status=PaymentAttempt.Status.FAILED,
            provider_session_id="cs_test_l11a_guest",
            idempotency_key="l11a-guest-failed",
            guest_link=issued.link,
            guest_email="relative@example.invalid",
        )
        _enqueue_payment_failed_email(attempt=attempt, order=order)
        owner = OutboundMessage.objects.get(
            key=f"payment_failed:attempt:{attempt.pk}:owner"
        )
        guest = OutboundMessage.objects.get(
            key=f"guest_payment:attempt:{attempt.pk}:failed"
        )
        assert owner.context["tracking_number"] == scenario.delivery_request.tracking_number
        assert "tracking_number" not in guest.context
        _, text, html = outbox.render_parts(guest)
        assert "WSL-" not in text + html

    def test_a_deposit_refund_names_the_request_to_its_owner_only(self):
        scenario = build_scenario(prefix="l11a-mail-deposit", open_request=False)
        order = ensure_posting_deposit_order(delivery_request=scenario.delivery_request)
        issued = create_guest_link(order_id=order.pk, actor_id=scenario.sender.pk)
        attempt = PaymentAttempt.objects.create(
            order=order,
            provider="stripe",
            amount_eur_cents=order.amount_eur_cents,
            payment_currency="EUR",
            provider_amount_minor=order.amount_eur_cents,
            status=PaymentAttempt.Status.FAILED,
            provider_session_id="cs_test_l11a_deposit",
            idempotency_key="l11a-deposit-refund",
            guest_link=issued.link,
            guest_email="relative@example.invalid",
        )
        refund = PaymentRefund(
            order=order, attempt=attempt, amount_eur_cents=100, provider="stripe"
        )
        _enqueue_refund_status_email(refund=refund, status="pending")
        messages = OutboundMessage.objects.filter(
            kind=OutboundMessage.Kind.REFUND_STATUS
        )
        owner = messages.get(key__endswith=":owner")
        guest = messages.get(key__endswith=":guest")
        assert owner.context["tracking_number"] == scenario.delivery_request.tracking_number
        assert "tracking_number" not in guest.context


class DeliveryEmailTests(TestCase):
    def test_the_recipient_and_the_parties_are_told_the_number(self):
        scenario = delivered_scenario(self.client, prefix="l11a-mail-delivered")
        number = tracking.for_deal(scenario.deal)
        kinds = {
            OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            OutboundMessage.Kind.DELIVERY_CODE_RELEASED,
            OutboundMessage.Kind.PICKUP_CONFIRMED,
            OutboundMessage.Kind.DELIVERY_CONFIRMED,
            OutboundMessage.Kind.RATING_AVAILABLE,
        }
        messages = OutboundMessage.objects.filter(deal=scenario.deal, kind__in=kinds)
        assert {message.kind for message in messages} == kinds
        for message in messages:
            assert message.context["tracking_number"] == number, message.kind
        recipient = messages.get(kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE)
        with translation.override("en"):
            document = outbox._recipient_delivery_code(recipient.context, "000000")
        assert dict(document.facts)["Tracking number"] == number


# --- staff search ----------------------------------------------------------------


UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


@UNHASHED_STATIC
class StaffSearchTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="l11a-search")
        self.deal = self.scenario.deal
        self.number = tracking.for_deal(self.deal)
        self.typed = self.number[4:].lower()  # no prefix, no hyphen, lower case
        self.other = build_scenario(prefix="l11a-search-other")
        self.other.accept()
        self.other_number = self.other.delivery_request.tracking_number
        attempt = PaymentAttempt.objects.filter(
            order__deal=self.deal, status=PaymentAttempt.Status.SUCCEEDED
        ).first()
        self.refund = PaymentRefund.objects.create(
            order=attempt.order,
            attempt=attempt,
            amount_eur_cents=100,
            provider=attempt.provider,
            provider_mode=attempt.provider_mode,
            idempotency_key="l11a-search-refund",
            reason=PaymentRefund.Reason.ADMIN,
            status=PaymentRefund.Status.PENDING,
        )
        Dispute.objects.create(
            deal=self.deal,
            opened_by=self.scenario.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            status=Dispute.Status.UNDER_REVIEW,
            category=Dispute.Category.DAMAGED,
            reason_text="Crushed corner.",
        )
        self.operator = _staff(self.scenario.admin)

    def test_every_console_list_finds_a_parcel_by_its_typed_number(self):
        staff_login(self.client, self.operator)
        for name in ("requests", "deals", "disputes", "payments", "refunds", "payouts"):
            with self.subTest(name):
                url = reverse(f"admin_console:{name}")
                found = self.client.get(url, {"q": self.typed}).content.decode()
                assert self.number in found, name
                assert self.other_number not in found, name
                missing = self.client.get(url, {"q": "WSL-22222222"}).content.decode()
                assert self.number not in missing, name
                # A partial number is not a number and matches nothing by it.
                partial = self.client.get(url, {"q": self.number[:-1]}).content.decode()
                assert self.number not in partial, name

    def test_detail_pages_name_the_parcel_in_their_heading(self):
        staff_login(self.client, self.operator)
        dispute = Dispute.objects.get(deal=self.deal)
        payment = PaymentAttempt.objects.filter(order__deal=self.deal).first()
        for url in (
            reverse("admin_console:deal-detail", args=[self.deal.pk]),
            reverse("admin_console:dispute-detail", args=[dispute.pk]),
            reverse("admin_console:payment-detail", args=[payment.pk]),
            reverse("admin_console:refund-detail", args=[self.refund.pk]),
            reverse("admin_console:payout-detail", args=[self.deal.payout.pk]),
        ):
            with self.subTest(url):
                page = self.client.get(url)
                assert page.status_code == 200, url
                html = page.content.decode()
                start = html.index('<header class="st-page-head">')
                header = html[start : html.index("</header>", start)]
                assert self.number in header, url

    def test_every_admin_api_list_accepts_the_same_search(self):
        client = APIClient()
        staff_login(client, self.operator)
        for name in (
            "admin-request-list",
            "admin-match-list",
            "admin-deal-list",
            "admin-dispute-list",
            "admin-payment-order-list",
            "admin-payment-attempt-list",
            "admin-refund-list",
            "admin-payout-list",
        ):
            with self.subTest(name):
                found = client.get(reverse(name), {"q": self.typed})
                assert found.status_code == 200, found.data
                assert found.data["count"] >= 1, name
                assert {row["tracking_number"] for row in found.data["results"]} == {
                    self.number
                }
                missing = client.get(reverse(name), {"q": "WSL-22222222"})
                assert missing.data["count"] == 0, name


class TrackingNumberAtRestTests(TestCase):
    def test_every_request_row_has_a_distinct_valid_number(self):
        build_scenario(prefix="l11a-rest-a")
        build_scenario(prefix="l11a-rest-b")
        numbers = list(ParcelRequest.objects.values_list("tracking_number", flat=True))
        assert numbers and len(set(numbers)) == len(numbers)
        assert all(tracking.is_valid(number) for number in numbers)
