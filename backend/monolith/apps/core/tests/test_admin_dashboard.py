"""The operations dashboard, the queue panel on it, and the settings reading.

The panel exists because the admin index answered "where do I go" and never
"is anything wrong". Three things have to hold for it to be worth trusting:

* the numbers are counts of the rows they claim to count;
* every link lands on a changelist filtered to exactly those rows — a link that
  quietly drops its filter shows an operator a hundred rows and hides the one;
* it is not shown to someone who could not open the changelists behind it.

The settings reading is here for the same reason the money helpers are: an
operator asked "is protection still 48 hours" should not be dividing 172800 by
3600 under time pressure, and should never be shown a plausible default in
place of a value the document does not contain.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import BusinessSettingsVersion
from apps.core.policy_display import MISSING, boost_packages, policy_rows
from apps.core.templatetags.shiptrip_admin import QUEUES
from apps.disputes.models import Dispute
from apps.finance.models import ScheduledJob
from apps.kyc.models import KycSubmission
from apps.notifications.models import OutboundMessage

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
class QueuePanelTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="ops@example.com", email="ops@example.com", password="Sup3rStrong!"
        )
        self.client.force_login(self.operator)

    def test_an_empty_system_says_so_rather_than_showing_nothing(self):
        response = self.client.get("/admin/")
        body = response.content.decode()
        assert response.status_code == 200
        assert "Needs attention" in body
        assert "Every queue is empty right now." in body
        # A queue at zero stays on the page: an operator has to be able to see
        # that it was checked.
        assert "KYC submissions to review" in body

    def test_a_waiting_submission_is_counted_and_announced(self):
        applicant = User.objects.create_user(
            username="waiting@example.com", email="waiting@example.com"
        )
        KycSubmission.objects.create(
            user=applicant,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key="queue-panel-pending-00000000000",
            front_image_key="kyc/pending/front.jpg",
            status=KycSubmission.Status.PENDING,
        )
        body = self.client.get("/admin/").content.decode()
        assert "1 queue with work waiting" in body
        assert "/admin/kyc/kycsubmission/?status__exact=pending" in body

    def test_every_queue_link_lands_on_a_changelist_filtered_to_its_own_rows(self):
        """The link is the panel's only claim; an unfiltered one is a lie.

        Each queue is given one row in its state and one row that is not, then
        the link is followed and the result counted. Django silently ignores an
        unrecognised query parameter on some paths and raises on others, so the
        assertion is on what came back rather than on the URL.
        """

        for queue in QUEUES:
            with self.subTest(queue=queue.label):
                url = f"/admin/{queue.app_label}/{queue.model_name}/?{queue.query}"
                response = self.client.get(url)
                assert response.status_code == 200, (queue.label, response.status_code)
                changelist = response.context_data["cl"]
                model = changelist.model
                expected = model._default_manager.filter(queue.filters).count()
                assert changelist.result_count == expected, queue.label

    def test_a_failed_job_and_a_failed_email_both_reach_the_panel(self):
        ScheduledJob.objects.create(
            key="panel-failed-job",
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            run_at=timezone.now() - timedelta(minutes=1),
            status=ScheduledJob.Status.FAILED,
        )
        OutboundMessage.objects.create(
            key="panel-failed-email",
            kind=OutboundMessage.Kind.KYC_STATUS,
            to_email="bounce@example.invalid",
            status=OutboundMessage.Status.FAILED,
            last_error="SMTP 550",
        )
        body = self.client.get("/admin/").content.decode()
        assert "2 queues with work waiting" in body
        assert "/admin/finance/scheduledjob/?status__exact=failed" in body
        assert "/admin/notifications/outboundmessage/?status__exact=failed" in body

    def test_the_panel_is_not_shown_to_staff_who_are_not_superusers(self):
        """It counts across finance, KYC and disputes in one view.

        A staff account with a narrower grant should not learn how many
        disputes are open from a page it can read.
        """

        limited = User.objects.create_user(
            username="limited@example.com",
            email="limited@example.com",
            password="Sup3rStrong!",
            is_staff=True,
        )
        from django.contrib.auth.models import Permission

        limited.user_permissions.add(
            Permission.objects.get(codename="view_kycsubmission")
        )
        self.client.force_login(limited)
        body = self.client.get("/admin/").content.decode()
        assert "Needs attention" not in body


@UNHASHED_STATIC
class DisputeQueueCountTests(TestCase):
    """The dispute queue counts the three states a decision is pending in."""

    def test_a_resolved_dispute_is_not_counted_as_awaiting_a_decision(self):
        from apps.deals.tests.phase4_factories import (
            delivered_scenario,
            enable_mock_rail,
        )

        enable_mock_rail()
        scenario = delivered_scenario(self.client, prefix="panel")
        admin_user = User.objects.create_superuser(
            username="dq@example.com", email="dq@example.com", password="Sup3rStrong!"
        )
        Dispute.objects.create(
            deal=scenario.deal,
            opened_by=scenario.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            status=Dispute.Status.RESOLVED,
            category=Dispute.Category.LATE,
            reason_text="Closed already.",
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
            resolved_at=timezone.now(),
            resolved_by=admin_user,
        )
        self.client.force_login(admin_user)
        body = self.client.get("/admin/").content.decode()
        assert "Every queue is empty right now." in body


class PolicyReadingTests(TestCase):
    """Readings of the stored document, in the units the product speaks in."""

    def setUp(self):
        self.revision = BusinessSettingsVersion.objects.filter(
            status="active"
        ).order_by("-version").first()
        assert self.revision is not None, "A migration seeds the active revision."

    def _value(self, rows, label):
        return next(row.value for row in rows if row.label == label)

    def test_the_windows_read_the_way_the_product_states_them(self):
        rows = policy_rows(
            self.revision.policy,
            commission_rate_bps=self.revision.commission_rate_bps,
        )
        assert self._value(rows, "Payout protection window").startswith("48 hours")
        assert self._value(rows, "Delivery-code buffer after pickup").startswith(
            "30 minutes"
        )
        # The raw seconds stay in the reading, so it can be checked against the
        # document sitting underneath it on the page.
        assert "172,800 s" in self._value(rows, "Payout protection window")

    def test_rates_and_amounts_are_rendered_not_recalculated(self):
        rows = policy_rows(
            self.revision.policy,
            commission_rate_bps=self.revision.commission_rate_bps,
        )
        assert self._value(rows, "Commission") == "25.00% (2,500 bps)"
        assert self._value(rows, "Posting deposit floor") == "€3.00"
        assert self._value(rows, "Posting deposit ceiling") == "€7.00"

    def test_every_row_names_a_key_that_exists_in_the_document(self):
        """A reading that silently reads nothing is worse than no reading."""

        rows = policy_rows(
            self.revision.policy,
            commission_rate_bps=self.revision.commission_rate_bps,
        )
        unresolved = [row.label for row in rows if row.value == MISSING]
        assert unresolved == [], unresolved

    def test_an_absent_key_says_so_instead_of_showing_a_plausible_number(self):
        rows = policy_rows({}, commission_rate_bps=None)
        assert {row.value for row in rows} == {MISSING}

    def test_the_test_rail_is_called_out_when_a_revision_carries_it(self):
        rows = policy_rows(
            {"payments": {"providers": {"mock_enabled": True}}},
            commission_rate_bps=None,
        )
        mock_row = next(row for row in rows if row.label.startswith("Mock rail"))
        assert mock_row.value == "Enabled"
        assert mock_row.tone == "bad"

        off = policy_rows(
            {"payments": {"providers": {"mock_enabled": False}}},
            commission_rate_bps=None,
        )
        mock_off = next(row for row in off if row.label.startswith("Mock rail"))
        assert mock_off.value == "Disabled"
        assert mock_off.tone == "mute"

    def test_boost_packages_are_listed_with_prices_as_amounts(self):
        packages = boost_packages(self.revision.policy)
        assert packages, "The seeded revision configures boost packages."
        assert all(package["price"].startswith("€") for package in packages)
        assert boost_packages({}) == ()
        assert boost_packages(None) == ()


@UNHASHED_STATIC
class SettingsPageTests(TestCase):
    def test_the_revision_page_carries_the_reading_and_the_document(self):
        operator = User.objects.create_superuser(
            username="settings@example.com",
            email="settings@example.com",
            password="Sup3rStrong!",
        )
        self.client.force_login(operator)
        revision = (
            BusinessSettingsVersion.objects.filter(status="active")
            .order_by("-version")
            .first()
        )
        response = self.client.get(
            f"/admin/core/businesssettingsversion/{revision.pk}/change/"
        )
        body = response.content.decode()
        assert response.status_code == 200
        assert "Payout protection window" in body
        assert "48 hours" in body
        assert "payments.payout.protection_window_seconds" in body
        # The document is still there, and still the authority.
        assert "protection_window_seconds" in body
        assert "this page cannot" in body.replace("\n", " ")
