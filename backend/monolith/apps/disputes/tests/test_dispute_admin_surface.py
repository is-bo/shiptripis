"""What an operator can see before deciding a dispute.

Resolving a dispute means deciding what happens to money that is already
somewhere. Finding out where used to mean opening the order, refund and payout
changelists and filtering each by the deal — three navigations away from the
page holding the evidence and the timeline. The dispute page now states the
position it is about to be decided against.

Two properties matter. It must be a **reading**: the amounts are the stored
integers, formatted, and nothing on the page sums, nets or reconciles them —
that is the resolution service's job, under the deal lock, and it stays there.
And it must remain **read-only**: this page states the position, the audited
endpoint changes it.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    delivered_scenario,
    enable_mock_rail,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)
from apps.disputes.models import Dispute
from apps.finance.models import PaymentOrder, Payout

User = get_user_model()

UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


@UNHASHED_STATIC
class DisputeMoneyPositionTests(TestCase):
    def setUp(self):
        enable_mock_rail()
        self.scenario = delivered_scenario(self.client, prefix="dspadm")
        self.deal = self.scenario.deal
        self.operator = User.objects.create_superuser(
            username="dsp-ops@example.com",
            email="dsp-ops@example.com",
            password="Sup3rStrong!",
        )
        # Delivery already raises the payout obligation, so this adjusts the
        # row the services created rather than inventing a second one.
        self.payout, _ = Payout.objects.update_or_create(
            deal=self.deal,
            defaults=dict(
                traveler=self.scenario.traveler,
                amount_eur_cents=3_000,
                method=Payout.Method.MANUAL,
                status=Payout.Status.NOT_ELIGIBLE,
                reference="ADMIN-TEST-1",
            ),
        )
        self.dispute = Dispute.objects.create(
            deal=self.deal,
            opened_by=self.scenario.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            status=Dispute.Status.UNDER_REVIEW,
            category=Dispute.Category.DAMAGED,
            reason_text="One corner is crushed.",
            payout_frozen=True,
        )
        self.client.force_login(self.operator)

    def _body(self):
        response = self.client.get(f"/admin/disputes/dispute/{self.dispute.pk}/change/")
        assert response.status_code == 200
        return response.content.decode()

    def test_the_page_states_the_payment_and_payout_position(self):
        body = self._body()
        order = PaymentOrder.objects.get(
            deal=self.deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        assert "Where the money is" in body
        assert f"Payment order #{order.pk}" in body
        assert f"Payout #{self.payout.pk}" in body
        assert "€30.00" in body

    def test_a_frozen_payout_is_said_in_words_before_the_table(self):
        assert "frozen" in self._body()

    def test_an_already_settled_payout_is_the_louder_warning(self):
        self.dispute.payout_frozen = False
        self.dispute.payout_already_settled = True
        self.dispute.save()
        body = self._body()
        assert "already settled" in body.replace("\n", " ")
        assert "reconciled by hand" in body.replace("\n", " ")

    def test_the_page_points_at_the_audited_endpoint_and_cannot_resolve(self):
        body = self._body()
        assert "/api/admin/disputes/" in body
        assert "this page cannot" in body.replace("\n", " ")
        # No save row: the dispute admin is registered read-only.
        assert 'name="_save"' not in body

    def test_no_amount_on_the_page_is_a_number_the_page_worked_out(self):
        """Every rendered amount traces to a stored integer, exactly.

        The guard is deliberately literal: each euro figure in the position
        table has to be `format_eur` of a column, so a future edit that starts
        netting a refund against a payout fails here rather than in an
        operator's head.
        """

        import re

        from apps.core.admin_display import format_eur

        body = self._body()
        start = body.index("Where the money is")
        end = body.index("Every value is read from the stored row")
        stored = {
            format_eur(order.amount_eur_cents)
            for order in self.deal.payment_orders.all()
        } | {
            format_eur(self.payout.amount_eur_cents),
            format_eur(0),
        }
        for order in self.deal.payment_orders.all():
            stored.add(format_eur(order.paid_eur_cents))
            stored.add(format_eur(order.refunded_eur_cents))
        shown = set(re.findall(r"€[\d,]+\.\d{2}", body[start:end]))
        assert shown, "The position table shows at least one amount."
        assert shown <= stored, shown - stored


@UNHASHED_STATIC
class DisputeEvidenceDigestTests(TestCase):
    def test_a_content_hash_is_shown_as_a_prefix_not_as_64_characters(self):
        scenario = fund_scenario(self.client, prefix="dspev")
        record_recipient(scenario)
        confirm_pickup(scenario)
        release_delivery_code(scenario)
        operator = User.objects.create_superuser(
            username="ev-ops@example.com",
            email="ev-ops@example.com",
            password="Sup3rStrong!",
        )
        dispute = Dispute.objects.create(
            deal=scenario.deal,
            opened_by=scenario.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            status=Dispute.Status.OPEN,
            category=Dispute.Category.DAMAGED,
            reason_text="Crushed.",
        )
        from apps.disputes.models import DisputeEvidence

        digest = "b" * 64
        DisputeEvidence.objects.create(
            dispute=dispute,
            submitted_by=scenario.sender,
            kind=DisputeEvidence.Kind.PHOTO,
            storage_bucket="disputes",
            storage_key="x/y.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            content_sha256=digest,
        )
        self.client.force_login(operator)
        body = self.client.get(
            f"/admin/disputes/dispute/{dispute.pk}/change/"
        ).content.decode()
        assert digest[:12] in body
        # The whole hash stays reachable, on the title, but not set in the row.
        assert f'title="sha256:{digest}"' in body
        assert f">{digest}<" not in body
        # And the private storage location is still absent from every surface.
        assert "x/y.jpg" not in body
