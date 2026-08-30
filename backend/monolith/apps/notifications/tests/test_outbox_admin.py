"""The outbox as an operations surface, and the line it must not cross.

`OutboundMessage` had no admin at all, so "did the verification email go out,
and why is that address bouncing" was a question answerable only from logs.
Registering it puts every transactional send in front of an operator — which is
exactly why the delivery-code guarantee has to be re-checked against this
surface rather than assumed from the outbox tests.

The rule, unchanged since Phase 4: the plaintext delivery code exists only
inside the final trusted renderer, at send time. The row carries a sealed
`secret_ref`. Nothing on this page renders a secret, nothing here can resolve
one, and the reference itself is not displayed.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)
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
class OutboxAdminTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="obx@example.com", email="obx@example.com", password="Sup3rStrong!"
        )
        self.client.force_login(self.operator)
        self.scenario = fund_scenario(self.client, prefix="obxadm")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        release_delivery_code(self.scenario)
        self.code = self.scenario.delivery_code
        assert self.code, "The fixture must have released a real code."
        self.message = OutboundMessage.objects.get(
            deal_id=self.scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
        )
        self.client.force_login(self.operator)

    def test_the_changelist_never_renders_a_delivery_code(self):
        response = self.client.get("/admin/notifications/outboundmessage/")
        body = response.content.decode()
        assert response.status_code == 200
        assert self.code not in body
        assert self.message.secret_ref not in body

    def test_the_detail_page_never_renders_a_delivery_code_or_its_reference(self):
        url = f"/admin/notifications/outboundmessage/{self.message.pk}/change/"
        body = self.client.get(url).content.decode()
        assert self.code not in body
        assert self.message.secret_ref not in body
        # What it does say is that one exists, which is what an operator
        # reading a failed send needs to know.
        assert "sealed" in body.lower()

    def test_a_failing_send_shows_what_the_transport_said(self):
        OutboundMessage.objects.create(
            key="admin-failed-send",
            kind=OutboundMessage.Kind.KYC_STATUS,
            to_email="bounce@example.invalid",
            status=OutboundMessage.Status.FAILED,
            attempts=10,
            last_error="SMTP 550 5.1.1 recipient rejected (relay refused).",
        )
        body = self.client.get("/admin/notifications/outboundmessage/").content.decode()
        assert "SMTP 550 5.1.1 recipient rejected" in body
        assert "10 / 10" in body

    def test_the_row_is_evidence_and_cannot_be_added_changed_or_deleted(self):
        model_admin = admin.site._registry[OutboundMessage]
        request = self.client.get("/admin/notifications/outboundmessage/").wsgi_request
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request, self.message) is False
        assert model_admin.has_delete_permission(request, self.message) is False

    def test_the_secret_reference_is_not_a_field_the_page_can_render(self):
        model_admin = admin.site._registry[OutboundMessage]
        request = self.client.get("/admin/notifications/outboundmessage/").wsgi_request
        assert "secret_ref" not in model_admin.get_fields(request, self.message)
        assert "secret_ref" not in model_admin.search_fields
        assert "secret_ref" not in model_admin.list_display
