"""Tests for apps.verification — issue, verify, escrow release on delivery."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.payments.models import PaymentIntent
from apps.trips.models import Trip
from apps.verification.models import HandoverCode
from apps.verification.services import (
    CodeInvalid,
    CodeNotActive,
    issue_code,
    verify_code,
)
from apps.wallet.models import Hold, Wallet
from apps.wallet.services import get_balance


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


def _accepted_match_with_intent(
    total_dzd: int = 5000,
    base_amount: int = 4000,
    commission: int = 1000,
) -> tuple[User, User, Match, Offer, PaymentIntent]:
    sender = _user("v_sender@example.com", "300")
    traveler = _user("v_traveler@example.com", "301")
    parcel = DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        origin_id="ALG",
        destination_id="CDG",
        weight_kg=2,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        base_amount_dzd=base_amount,
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
        base_amount_dzd=base_amount,
        commission_dzd=commission,
        total_dzd=total_dzd,
        economics_version=Offer.EconomicsVersion.LEGACY_DZD,
        currency=Offer.Currency.DZD,
        status=Offer.Status.ACCEPTED,
        responded_at=timezone.now(),
    )
    intent = PaymentIntent.objects.create(
        offer=offer,
        payer=sender,
        provider="mock",
        provider_intent_id=f"pi_mock_test_{match.id}",
        amount_minor=total_dzd,
        currency="DZD",
        status=PaymentIntent.Status.SUCCEEDED,
        succeeded_at=timezone.now(),
    )
    return sender, traveler, match, offer, intent


class IssueCodeServiceTests(APITestCase):
    def test_issue_pickup_returns_plaintext_once(self):
        sender, _, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        assert issued.code.isdigit() and len(issued.code) == 6
        row = HandoverCode.objects.get(id=issued.handover_id)
        assert row.status == HandoverCode.Status.ACTIVE
        assert row.code_hash.startswith("$argon2")
        assert row.code_hash != issued.code  # NOT stored as plaintext

    def test_issuing_again_rotates_previous(self):
        sender, _, match, _, _ = _accepted_match_with_intent()
        first = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        second = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        assert first.handover_id != second.handover_id
        row1 = HandoverCode.objects.get(id=first.handover_id)
        row2 = HandoverCode.objects.get(id=second.handover_id)
        assert row1.status == HandoverCode.Status.ROTATED
        assert row2.status == HandoverCode.Status.ACTIVE


class VerifyCodeServiceTests(APITestCase):
    def test_pickup_verify_moves_match_to_in_transit(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        verify_code(
            match=match,
            kind=HandoverCode.Kind.PICKUP,
            submitted_code=issued.code,
            used_by=traveler,
        )
        match.refresh_from_db()
        assert match.status == Match.Status.IN_TRANSIT

    def test_pickup_verify_auto_issues_delivery_code_to_sender(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        verify_code(
            match=match,
            kind=HandoverCode.Kind.PICKUP,
            submitted_code=issued.code,
            used_by=traveler,
        )
        delivery = HandoverCode.objects.filter(
            match=match,
            kind=HandoverCode.Kind.DELIVERY,
            status=HandoverCode.Status.ACTIVE,
        ).first()
        assert delivery is not None
        assert delivery.issued_to_id == sender.id

    def test_delivery_verify_releases_escrow_to_traveler(self):
        sender, traveler, match, offer, intent = _accepted_match_with_intent(
            total_dzd=5000, base_amount=4000, commission=1000
        )
        # Move through pickup first.
        match.status = Match.Status.IN_TRANSIT
        match.save(update_fields=["status"])
        # Signal already auto-opened a hold via PaymentIntent.SUCCEEDED.
        hold = Hold.objects.get(source="payment_intent", source_id=intent.id)
        assert hold.status == Hold.Status.OPEN

        issued = issue_code(
            match=match, kind=HandoverCode.Kind.DELIVERY, issued_to=sender
        )
        verify_code(
            match=match,
            kind=HandoverCode.Kind.DELIVERY,
            submitted_code=issued.code,
            used_by=traveler,
        )
        match.refresh_from_db()
        assert match.status == Match.Status.COMPLETED
        hold.refresh_from_db()
        assert hold.status == Hold.Status.RELEASED
        t_wallet = Wallet.objects.get(user=traveler, currency="DZD")
        bal = get_balance(t_wallet)
        # Traveler got base_amount (4000), platform kept commission (1000)
        assert bal.available_minor == 4000

    def test_wrong_code_increments_attempts(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        for _ in range(3):
            try:
                verify_code(
                    match=match,
                    kind=HandoverCode.Kind.PICKUP,
                    submitted_code="000000",  # extremely unlikely to match
                    used_by=traveler,
                )
            except CodeInvalid:
                pass
        row = HandoverCode.objects.filter(
            match=match, kind=HandoverCode.Kind.PICKUP
        ).order_by("-id").first()
        assert row.attempts == 3
        assert row.status == HandoverCode.Status.ACTIVE

    def test_five_wrong_attempts_locks_code(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        for _ in range(5):
            try:
                verify_code(
                    match=match,
                    kind=HandoverCode.Kind.PICKUP,
                    submitted_code="000000",
                    used_by=traveler,
                )
            except CodeInvalid:
                pass
        row = HandoverCode.objects.filter(
            match=match, kind=HandoverCode.Kind.PICKUP
        ).order_by("-id").first()
        assert row.status == HandoverCode.Status.LOCKED
        # Subsequent verify call raises CodeNotActive (no active code anymore)
        try:
            verify_code(
                match=match,
                kind=HandoverCode.Kind.PICKUP,
                submitted_code="000000",
                used_by=traveler,
            )
            assert False, "should have raised"
        except CodeNotActive:
            pass

    def test_used_code_cannot_be_reused(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        verify_code(
            match=match,
            kind=HandoverCode.Kind.PICKUP,
            submitted_code=issued.code,
            used_by=traveler,
        )
        # Match is now in_transit; another pickup verify must fail (no active code)
        try:
            verify_code(
                match=match,
                kind=HandoverCode.Kind.PICKUP,
                submitted_code=issued.code,
                used_by=traveler,
            )
            assert False, "should have raised"
        except CodeNotActive:
            pass


class HandoverApiTests(APITestCase):
    def test_only_sender_can_issue(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        r = _client(traveler).post(
            f"/api/matches/{match.id}/handover/issue",
            {"kind": "pickup"},
            format="json",
        )
        assert r.status_code == 403

    def test_sender_issues_pickup_returns_code(self):
        sender, _, match, _, _ = _accepted_match_with_intent()
        r = _client(sender).post(
            f"/api/matches/{match.id}/handover/issue",
            {"kind": "pickup"},
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.data["code"].isdigit() and len(r.data["code"]) == 6

    def test_only_traveler_can_verify(self):
        sender, _, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        r = _client(sender).post(
            f"/api/matches/{match.id}/handover/verify",
            {"kind": "pickup", "code": issued.code},
            format="json",
        )
        assert r.status_code == 403

    def test_traveler_verifies_pickup(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        r = _client(traveler).post(
            f"/api/matches/{match.id}/handover/verify",
            {"kind": "pickup", "code": issued.code},
            format="json",
        )
        assert r.status_code == 200, r.content
        match.refresh_from_db()
        assert match.status == Match.Status.IN_TRANSIT

    def test_handover_list_visible_to_party(self):
        sender, traveler, match, _, _ = _accepted_match_with_intent()
        issue_code(match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender)
        r = _client(traveler).get(f"/api/matches/{match.id}/handover")
        assert r.status_code == 200
        results = r.data["results"] if isinstance(r.data, dict) else r.data
        assert len(results) == 1

    def test_active_code_get_returns_same_row_without_rotating(self):
        sender, _, match, _, _ = _accepted_match_with_intent()
        issued = issue_code(
            match=match, kind=HandoverCode.Kind.PICKUP, issued_to=sender
        )
        url = f"/api/matches/{match.id}/handover/code?kind=pickup"
        r1 = _client(sender).get(url)
        r2 = _client(sender).get(url)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.data["id"] == r2.data["id"] == issued.handover_id
        # Only one ACTIVE row exists — nothing was rotated.
        active = HandoverCode.objects.filter(
            match=match,
            kind=HandoverCode.Kind.PICKUP,
            status=HandoverCode.Status.ACTIVE,
        )
        assert active.count() == 1

    def test_active_code_get_404_when_none(self):
        sender, _, match, _, _ = _accepted_match_with_intent()
        r = _client(sender).get(
            f"/api/matches/{match.id}/handover/code?kind=pickup"
        )
        assert r.status_code == 404
