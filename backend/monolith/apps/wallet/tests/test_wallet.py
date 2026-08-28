"""Tests for apps.wallet — ledger writes, holds, signals from payments."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.payments.models import PaymentIntent, Refund
from apps.trips.models import Trip
from apps.wallet.models import Hold, Wallet, WalletEntry
from apps.wallet.services import (
    get_balance,
    open_hold,
    release_hold_to_payee,
    reverse_hold_for_refund,
)


def _user(email: str, suffix: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=f"User {suffix}",
        phone=f"+213555000{suffix}",
        wilaya="16",
    )


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _accepted_offer(total_dzd: int = 5000) -> tuple[User, User, Offer]:
    sender = _user("w_sender@example.com", "200")
    traveler = _user("w_traveler@example.com", "201")
    parcel = DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        origin_id="ALG",
        destination_id="CDG",
        weight_kg=2,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        base_amount_dzd=total_dzd - 1000,
    )
    trip = Trip.objects.create(
        traveler=traveler,
        origin_id="ALG",
        destination_id="CDG",
        departure_at=timezone.now() + timedelta(days=2),
        capacity_kg=20,
        status=Trip.Status.ACTIVE,
    )
    match = Match.objects.create(
        parcel=parcel,
        trip=trip,
        sender=sender,
        traveler=traveler,
        status=Match.Status.ACCEPTED,
    )
    offer = Offer.objects.create(
        match=match,
        proposed_by=Offer.ProposedBy.TRAVELER,
        proposer=traveler,
        base_amount_dzd=total_dzd - 1000,
        commission_dzd=1000,
        total_dzd=total_dzd,
        economics_version=Offer.EconomicsVersion.LEGACY_DZD,
        currency=Offer.Currency.DZD,
        status=Offer.Status.ACCEPTED,
        responded_at=timezone.now(),
    )
    return sender, traveler, offer


class LedgerServiceTests(APITestCase):
    def setUp(self):
        self.sender, self.traveler, self.offer = _accepted_offer(10000)

    def test_open_hold_creates_deposit_and_hold_entries(self):
        hold = open_hold(
            user=self.sender,
            currency="DZD",
            amount_minor=10000,
            source="payment_intent",
            source_id=999,
        )
        wallet = hold.wallet
        balance = get_balance(wallet)
        assert balance.total_minor == 0
        assert balance.available_minor == 0
        assert balance.on_hold_minor == 10000
        kinds = sorted(wallet.entries.values_list("kind", flat=True))
        assert kinds == ["deposit", "hold"]

    def test_open_hold_idempotent_for_same_source(self):
        h1 = open_hold(
            user=self.sender, currency="DZD", amount_minor=10000,
            source="payment_intent", source_id=1,
        )
        h2 = open_hold(
            user=self.sender, currency="DZD", amount_minor=10000,
            source="payment_intent", source_id=1,
        )
        assert h1.id == h2.id
        assert WalletEntry.objects.filter(wallet=h1.wallet).count() == 2

    def test_release_pays_traveler_and_closes_hold(self):
        hold = open_hold(
            user=self.sender, currency="DZD", amount_minor=10000,
            source="payment_intent", source_id=2,
        )
        release_hold_to_payee(
            hold=hold,
            payee=self.traveler,
            payee_amount_minor=9000,  # 10k total - 1k commission
            platform_fee_minor=1000,
            release_source="handover",
            release_source_id=1,
        )
        hold.refresh_from_db()
        assert hold.status == "released"
        # Sender wallet net 0 (deposit + hold + release + payout = 0)
        s_bal = get_balance(Wallet.objects.get(user=self.sender, currency="DZD"))
        assert s_bal.total_minor == 0
        assert s_bal.on_hold_minor == 0
        # Traveler wallet has +9000
        t_bal = get_balance(Wallet.objects.get(user=self.traveler, currency="DZD"))
        assert t_bal.total_minor == 9000
        assert t_bal.available_minor == 9000

    def test_release_is_idempotent(self):
        hold = open_hold(
            user=self.sender, currency="DZD", amount_minor=10000,
            source="payment_intent", source_id=3,
        )
        release_hold_to_payee(
            hold=hold, payee=self.traveler, payee_amount_minor=9000,
            platform_fee_minor=1000,
            release_source="handover", release_source_id=2,
        )
        # A webhook replay with the stale in-memory OPEN hold is a no-op.
        wallet = Wallet.objects.get(user=self.sender, currency="DZD")
        n = wallet.entries.count()
        result = release_hold_to_payee(
            hold=hold, payee=self.traveler, payee_amount_minor=9000,
            platform_fee_minor=1000,
            release_source="handover", release_source_id=2,
        )
        assert result.status == Hold.Status.RELEASED
        assert wallet.entries.count() == n

    def test_reverse_hold_for_refund(self):
        hold = open_hold(
            user=self.sender, currency="DZD", amount_minor=10000,
            source="payment_intent", source_id=4,
        )
        reverse_hold_for_refund(
            hold=hold, refund_source="refund", refund_source_id=99,
        )
        hold.refresh_from_db()
        assert hold.status == "reversed"
        bal = get_balance(Wallet.objects.get(user=self.sender, currency="DZD"))
        assert bal.total_minor == 0
        assert bal.on_hold_minor == 0


class PaymentSignalTests(APITestCase):
    """Verify the post_save signal auto-opens / auto-reverses holds."""

    def test_payment_succeeded_opens_hold_on_sender_wallet(self):
        sender, traveler, offer = _accepted_offer(5000)
        intent = PaymentIntent.objects.create(
            offer=offer, payer=sender, provider="mock",
            provider_intent_id="pi_mock_test1",
            amount_minor=5000, currency="DZD",
            status=PaymentIntent.Status.SUCCEEDED,
            succeeded_at=timezone.now(),
        )
        hold = Hold.objects.filter(
            source="payment_intent", source_id=intent.id
        ).first()
        assert hold is not None
        assert hold.amount_minor == 5000
        assert hold.status == "open"

    def test_refund_succeeded_reverses_hold(self):
        sender, traveler, offer = _accepted_offer(5000)
        intent = PaymentIntent.objects.create(
            offer=offer, payer=sender, provider="mock",
            provider_intent_id="pi_mock_test2",
            amount_minor=5000, currency="DZD",
            status=PaymentIntent.Status.SUCCEEDED,
            succeeded_at=timezone.now(),
        )
        Refund.objects.create(
            intent=intent, amount_minor=5000, currency="DZD",
            provider="mock", provider_refund_id="re_mock_test1",
            status=Refund.Status.SUCCEEDED,
            succeeded_at=timezone.now(),
        )
        hold = Hold.objects.get(source="payment_intent", source_id=intent.id)
        assert hold.status == "reversed"


class WalletApiTests(APITestCase):
    def setUp(self):
        self.sender, self.traveler, self.offer = _accepted_offer(5000)
        self.intent = PaymentIntent.objects.create(
            offer=self.offer, payer=self.sender, provider="mock",
            provider_intent_id="pi_mock_api_1",
            amount_minor=5000, currency="DZD",
            status=PaymentIntent.Status.SUCCEEDED,
            succeeded_at=timezone.now(),
        )

    def test_sender_sees_held_balance(self):
        c = _client(self.sender)
        r = c.get(reverse("wallets-detail", args=["DZD"]))
        assert r.status_code == 200, r.data
        assert r.data["currency"] == "DZD"
        assert r.data["available_minor"] == 0
        assert r.data["on_hold_minor"] == 5000
        assert r.data["total_minor"] == 0

    def test_entries_list_shows_deposit_and_hold(self):
        c = _client(self.sender)
        r = c.get(reverse("wallets-entries", args=["DZD"]))
        assert r.status_code == 200
        kinds = sorted([e["kind"] for e in r.data])
        assert kinds == ["deposit", "hold"]

    def test_holds_list_shows_open_hold(self):
        c = _client(self.sender)
        r = c.get(reverse("wallets-holds", args=["DZD"]))
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["status"] == "open"
        assert r.data[0]["amount_minor"] == 5000

    def test_withdrawal_rejected_when_no_available_balance(self):
        c = _client(self.sender)
        r = c.post(
            reverse("withdrawals-create"),
            {"currency": "DZD", "amount_minor": 1000, "destination": "bank"},
            format="json",
        )
        assert r.status_code == 409

    def test_withdrawal_created_when_balance_available(self):
        # Give traveler 9000 by simulating a release.
        from apps.wallet.services import open_hold, release_hold_to_payee
        h = open_hold(
            user=self.sender, currency="DZD", amount_minor=10000,
            source="payment_intent", source_id=12345,
        )
        release_hold_to_payee(
            hold=h, payee=self.traveler, payee_amount_minor=9000,
            platform_fee_minor=1000,
            release_source="handover", release_source_id=12345,
        )
        c = _client(self.traveler)
        r = c.post(
            reverse("withdrawals-create"),
            {"currency": "DZD", "amount_minor": 5000, "destination": "bank"},
            format="json",
        )
        assert r.status_code == 201, r.data
