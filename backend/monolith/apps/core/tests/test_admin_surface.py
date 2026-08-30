"""The Django admin as an operations surface: what it shows, and what it refuses.

Two separate concerns live here.

**Authorization.** Phase 6A made administrative capability explicit: an
operations action checks a named permission and writes an audit row. The Django
admin is a second door into the same models, and it does not know about any of
that — it grants on Django's generic per-model add/change/delete permissions and
records nothing in `AdminAuditLog`. Business settings were reachable through
that door: the changelist offered an "activate revision" action, and the add
form accepted an arbitrary policy document, both without the Phase 6A
capability, without the serializer's validation and without a reason. These
tests hold that door shut, and hold the audited route open.

**Legibility.** Every amount in this system is an integer number of cents. On a
refund or payout queue that is a hundred-fold misread waiting to happen, so the
operations columns render it as an amount. These tests are about the arithmetic
of that rendering, which must be exact and must never invent a value.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from apps.core.admin_display import (
    TONE_ATTENTION,
    TONE_BAD,
    TONE_MUTE,
    TONE_OK,
    TONE_WAIT,
    format_eur,
    tone_for,
)
from apps.core.models import BusinessSettingsVersion

User = get_user_model()

# Production serves admin static through a hashed manifest, which does not exist
# in a test run. Rendering an admin page is the point of two tests below, so
# they use the plain storage rather than skipping the render.
UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


class MoneyRenderingTests(TestCase):
    def test_cents_render_as_an_exact_euro_amount(self):
        assert format_eur(0) == "€0.00"
        assert format_eur(5) == "€0.05"
        assert format_eur(50) == "€0.50"
        assert format_eur(750) == "€7.50"
        assert format_eur(3750) == "€37.50"
        assert format_eur(100000) == "€1,000.00"
        assert format_eur(123456789) == "€1,234,567.89"

    def test_a_negative_entry_keeps_its_sign(self):
        """The ledger has both directions and a dropped minus is a wrong answer."""

        assert format_eur(-3750) == "-€37.50"
        assert format_eur(-1) == "-€0.01"

    def test_a_missing_amount_is_shown_as_missing_rather_than_as_zero(self):
        assert format_eur(None) == "—"

    def test_rendering_never_uses_floating_point(self):
        """A cent that rounds away in the display is a cent an operator argues about."""

        for cents in (1, 9, 10, 99, 101, 199, 1999, 20001, 999999999):
            whole, remainder = divmod(cents, 100)
            assert format_eur(cents) == f"€{whole:,}.{remainder:02d}"


class StatusToneTests(TestCase):
    def test_queue_signals_map_to_the_tone_that_says_what_to_do(self):
        assert tone_for("succeeded") == TONE_OK
        assert tone_for("PENDING") == TONE_WAIT
        assert tone_for("requires_action") == TONE_ATTENTION
        assert tone_for("failed") == TONE_BAD

    def test_an_unknown_status_is_inert_rather_than_alarming(self):
        """Inventing an alarm for a status nobody mapped trains operators to ignore them."""

        assert tone_for("some_new_status") == TONE_MUTE
        assert tone_for(None) == TONE_MUTE
        assert tone_for("") == TONE_MUTE


@UNHASHED_STATIC
class BusinessSettingsAdminIsInspectionOnlyTests(TestCase):
    """The unaudited settings-activation path is closed."""

    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = User.objects.create_superuser(
            email="root@shiptrip.invalid", username="root-ops", password="x" * 24
        )
        self.model_admin = admin.site._registry[BusinessSettingsVersion]

    def _request(self):
        request = self.factory.get("/admin/core/businesssettingsversion/")
        request.user = self.superuser
        return request

    def test_even_a_superuser_cannot_add_change_or_delete_a_revision(self):
        request = self._request()
        assert self.model_admin.has_add_permission(request) is False
        assert self.model_admin.has_change_permission(request) is False
        assert self.model_admin.has_delete_permission(request) is False

    def test_no_admin_action_can_activate_a_revision(self):
        """Activation is a Phase 6A capability, not a Django model permission."""

        actions = self.model_admin.get_actions(self._request())
        assert "activate_revision" not in actions
        assert not any("activat" in name for name in actions)

    def test_every_field_on_the_page_is_read_only(self):
        request = self._request()
        readonly = set(self.model_admin.get_readonly_fields(request))
        assert set(self.model_admin.get_fields(request)) <= readonly

    def test_the_commission_column_reads_as_a_percentage(self):
        version = BusinessSettingsVersion(commission_rate_bps=750)
        rendered = self.model_admin.commission_display(version)
        assert "7.50%" in rendered

    def test_the_changelist_says_activation_only_affects_new_snapshots(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/core/businesssettingsversion/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Read-only" in body
        assert "already snapshotted on an existing Deal" in body
        assert "checks the Phase" in body


@UNHASHED_STATIC
class AdminShellTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            email="shell@shiptrip.invalid", username="shell-ops", password="x" * 24
        )

    def test_the_operations_shell_is_branded_and_loads_its_stylesheet(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "ShipTrip Operations" in body
        assert "shiptrip/admin.css" in body

    def test_a_money_column_renders_a_chip_free_aligned_amount(self):
        from apps.finance.admin import PaymentRefundAdmin
        from apps.finance.models import PaymentRefund

        model_admin = admin.site._registry[PaymentRefund]
        rendered = model_admin.amount_display(PaymentRefund(amount_eur_cents=3750))
        assert "€37.50" in rendered
        assert "st-money-lead" in rendered
        assert isinstance(PaymentRefundAdmin.amount_display, object)
