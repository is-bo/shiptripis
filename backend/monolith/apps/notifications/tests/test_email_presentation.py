"""The HTML alternative of a transactional message.

A ShipTrip email arrives from an unfamiliar address and asks its reader to hand
a parcel to a stranger, or types a six-character code into their phone. Whether
it *looks* like ShipTrip is therefore not a cosmetic question — it is the only
signal a recipient has that the message is real, and the recipient of a delivery
code has no account, no session and nothing else to check it against.

These tests hold three lines:

* every message the outbox can produce has a readable, branded HTML part;
* the HTML part and the plain-text part come from one document, so they cannot
  say different things about the same delivery;
* adding the HTML part changed nothing about delivery-code secrecy — the code
  still exists only inside the trusted renderer, still bypasses Redis, and
  still never reaches a stream payload, an audit row or an error column.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings

from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)
from apps.notifications import outbox
from apps.notifications.email_layout import EmailDocument, to_html, to_text
from apps.notifications.models import OutboundMessage

# Every kind the outbox knows how to build without opening a seal.
NON_SECRET_KINDS = (
    OutboundMessage.Kind.KYC_STATUS,
    OutboundMessage.Kind.FLIGHT_PROOF_STATUS,
    OutboundMessage.Kind.PAYMENT_REQUIRED,
    OutboundMessage.Kind.PAYMENT_PROCESSING,
    OutboundMessage.Kind.PAYMENT_FAILED,
    OutboundMessage.Kind.PAYMENT_SUCCEEDED,
    OutboundMessage.Kind.GUEST_PAYMENT,
    OutboundMessage.Kind.REFUND_STATUS,
    OutboundMessage.Kind.EVIDENCE_REQUEST,
    OutboundMessage.Kind.SECURITY_EVENT,
    OutboundMessage.Kind.PICKUP_CONFIRMED,
    OutboundMessage.Kind.DELIVERY_CODE_RELEASED,
    OutboundMessage.Kind.DELIVERY_CONFIRMED,
    OutboundMessage.Kind.PROTECTION_ENDED,
    OutboundMessage.Kind.PROTECTION_ENDING,
    OutboundMessage.Kind.DISPUTE_OPENED,
    OutboundMessage.Kind.DISPUTE_RESOLVED,
    OutboundMessage.Kind.PAYOUT_STATUS,
    OutboundMessage.Kind.DEAL_CANCELLED,
    OutboundMessage.Kind.RATING_AVAILABLE,
)

SAMPLE_CONTEXT = {
    "status": "pending",
    "payment_reference": "pay-test",
    "dispute_reference": "DSP-test",
    "deal_reference": "DL-test",
    "summary": "A security event needs your attention.",
    "resolution_label": "refund the sender",
    "payout_status": "eligible",
    "reason": "cancelled by the sender",
    "protection_ends_at": "2026-09-01T10:00:00Z",
    "buffer_minutes": 30,
}


def _message(kind: str, **context) -> OutboundMessage:
    return OutboundMessage(kind=kind, context={**SAMPLE_CONTEXT, **context})


class EveryMessageHasAReadableHtmlPartTests(TestCase):
    def test_every_non_secret_kind_renders_all_three_parts(self):
        for kind in NON_SECRET_KINDS:
            with self.subTest(kind=kind):
                subject, text, html = outbox.render_parts(_message(kind))
                assert subject
                assert text.strip()
                assert html.lstrip().lower().startswith("<!doctype html>")
                assert "</html>" in html

    def test_the_html_is_branded_and_names_the_corridor(self):
        _, _, html = outbox.render_parts(
            _message(OutboundMessage.Kind.PAYMENT_SUCCEEDED)
        )
        assert "ShipTrip" in html
        # The masthead is set in type rather than fetched, because a blocked
        # remote image is the normal case in an email client.
        assert "<img" not in html
        assert "Algeria" in html

    def test_the_subject_is_the_document_title(self):
        subject, _, html = outbox.render_parts(
            _message(OutboundMessage.Kind.DISPUTE_OPENED)
        )
        assert f"<title>{subject}</title>" in html

    def test_narrow_clients_get_a_single_column_that_can_collapse(self):
        _, _, html = outbox.render_parts(_message(OutboundMessage.Kind.PAYOUT_STATUS))
        assert 'name="viewport"' in html
        assert "max-width:600px" in html
        assert "max-width:620px" in html  # the collapse breakpoint

    def test_layout_is_tables_and_inline_styles_rather_than_modern_css(self):
        """Flex and grid are unsupported in enough clients to be a bug, not a risk."""

        _, _, html = outbox.render_parts(
            _message(OutboundMessage.Kind.PICKUP_CONFIRMED)
        )
        assert "<table" in html
        assert "display:flex" not in html
        assert "display:grid" not in html
        assert "@media only screen" in html

    def test_no_message_reaches_out_to_a_third_party_host(self):
        for kind in NON_SECRET_KINDS:
            with self.subTest(kind=kind):
                _, _, html = outbox.render_parts(_message(kind))
                assert "http://" not in html
                assert "https://" not in html


class TextAndHtmlAgreeTests(TestCase):
    def test_both_parts_carry_the_same_heading_and_references(self):
        message = _message(OutboundMessage.Kind.DISPUTE_RESOLVED)
        _, text, html = outbox.render_parts(message)
        for fragment in ("Your dispute has been resolved", "DSP-test", "DL-test"):
            assert fragment in text
            assert fragment in html

    def test_a_document_renders_its_highlight_in_both_parts(self):
        document = EmailDocument(
            subject="s",
            heading="h",
            highlight=("Your code", "A7K2Q9"),
        )
        assert "Your code: A7K2Q9" in to_text(document)
        html = to_html(document)
        assert "Your code" in html
        assert "A7K2Q9" in html


class HtmlEscapingTests(TestCase):
    def test_context_values_cannot_inject_markup(self):
        """Context is data. A status string is never markup, in any renderer."""

        _, _, html = outbox.render_parts(
            _message(
                OutboundMessage.Kind.SECURITY_EVENT,
                summary='<script>alert("x")</script> & "quoted"',
            )
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html

    def test_a_reference_with_markup_is_escaped_in_the_reference_rows(self):
        _, _, html = outbox.render_parts(
            _message(
                OutboundMessage.Kind.PAYMENT_REQUIRED, payment_reference="<b>x</b>"
            )
        )
        assert "<b>x</b>" not in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html


@override_settings(EMAIL_SUPPORT_ADDR="support@shiptrip.invalid")
class SupportAndSafetyCopyTests(TestCase):
    def test_the_footer_tells_the_reader_shiptrip_never_asks_for_a_code(self):
        """And it tells both parts, not only the one with the styling.

        The anti-phishing line and the transactional-message notice used to be
        HTML-only, which put the least information in front of the reader whose
        client shows plain text.
        """

        _, text, html = outbox.render_parts(
            _message(OutboundMessage.Kind.PICKUP_CONFIRMED)
        )
        for part in (text, html):
            assert "never ask you for a pickup or delivery code" in part
            assert "transactional message, not marketing" in part

    def test_the_configured_support_mailbox_is_offered(self):
        _, text, html = outbox.render_parts(
            _message(OutboundMessage.Kind.REFUND_STATUS)
        )
        assert "support@shiptrip.invalid" in html
        assert "support@shiptrip.invalid" in text

    def test_the_release_notice_says_the_code_is_not_in_the_email(self):
        """The sender's 'your code is available' mail must not look like the code."""

        _, text, html = outbox.render_parts(
            _message(OutboundMessage.Kind.DELIVERY_CODE_RELEASED)
        )
        assert "not in this email" in text
        assert "not in this email" in html


@override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
class DeliveryCodeSecrecySurvivesTheHtmlPartTests(TestCase):
    """Phase 4/6A secrecy, re-checked against the part that did not exist before."""

    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="obxhtml")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        release_delivery_code(self.scenario)
        self.code = self.scenario.delivery_code
        self.message = OutboundMessage.objects.get(
            deal_id=self.scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
        )

    def test_the_code_is_still_absent_from_the_stored_row(self):
        self.message.refresh_from_db()
        assert self.code not in str(self.message.context)
        assert self.code not in self.message.secret_ref
        assert self.message.secret_ref.startswith("handover_code:")

    def test_the_html_part_carries_the_code_only_at_the_trusted_renderer(self):
        _, text, html = outbox.render_parts(self.message)
        assert self.code in text
        assert self.code in html
        # And the warning travels with it in both parts.
        assert "never" in text.lower()
        assert "never" in html.lower()

    def test_the_secret_message_still_bypasses_redis_entirely(self):
        sent = {}

        def _capture(**kwargs):
            sent.update(kwargs)

        fake_client = mock.MagicMock()
        with (
            mock.patch.object(outbox.redis_bus, "get_client", return_value=fake_client),
            mock.patch.object(outbox, "_send_email_via_provider", side_effect=_capture),
        ):
            assert outbox.dispatch_message(message_id=self.message.pk) == "dispatched"

        fake_client.xadd.assert_not_called()
        assert self.code in sent["body"]
        assert self.code in sent["html"]

    def test_the_html_part_is_attached_as_an_alternative_not_as_the_body(self):
        """The plain-text part stays primary; HTML is the alternative."""

        with mock.patch("apps.notifications.outbox.EmailMultiAlternatives") as ctor:
            ctor.return_value.send.return_value = 1
            outbox._send_email_via_provider(
                to="r@example.invalid", subject="s", body="b", html="<p>b</p>"
            )
        assert ctor.call_args.kwargs["body"] == "b"
        ctor.return_value.attach_alternative.assert_called_once_with(
            "<p>b</p>", "text/html"
        )

    def test_a_message_with_no_html_stays_single_part(self):
        with mock.patch("apps.notifications.outbox.EmailMultiAlternatives") as ctor:
            ctor.return_value.send.return_value = 1
            outbox._send_email_via_provider(
                to="r@example.invalid", subject="s", body="b"
            )
        ctor.return_value.attach_alternative.assert_not_called()


@override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
class OrdinaryMessagesCarryTheHtmlOnTheStreamTests(TestCase):
    def test_the_stream_payload_gains_an_html_field_and_no_secret(self):
        scenario = fund_scenario(self.client, prefix="obxstream")
        record_recipient(scenario)
        confirm_pickup(scenario)
        # Release the delivery code first so there is a real secret in the
        # database to look for. The pickup-confirmed message is an ordinary
        # stream message and must not carry it.
        release_delivery_code(scenario)
        assert scenario.delivery_code

        message = OutboundMessage.objects.filter(
            deal_id=scenario.deal.pk,
            kind=OutboundMessage.Kind.PICKUP_CONFIRMED,
        ).first()
        if message is None:  # pragma: no cover - depends on armed product events
            self.skipTest("No pickup-confirmed obligation is armed in this scenario.")

        captured = {}

        class _Recorder:
            def xadd(self, stream, fields, **kwargs):
                captured["stream"] = stream
                captured["fields"] = fields
                return b"1-0"

        with mock.patch.object(
            outbox.redis_bus, "get_client", return_value=_Recorder()
        ):
            outbox.dispatch_message(message_id=message.pk)

        payload = captured["fields"]["payload"]
        assert '"html":' in payload
        assert scenario.delivery_code not in payload


class ADurableOutboxRendersRowsWrittenByAnOlderDeployTests(TestCase):
    """A queued row outlives the code that queued it.

    The outbox is an obligation table: a message enqueued before a deploy is
    rendered by whatever is running when the worker picks it up. Any value the
    template drops into the middle of a sentence therefore has to survive its
    own absence — otherwise a recipient reads "resolved this dispute as: ."
    """

    def test_a_resolved_dispute_with_no_label_still_reads_as_a_sentence(self):
        _, text, html = outbox.render_parts(
            OutboundMessage(
                key="legacy-dispute-resolved",
                kind=OutboundMessage.Kind.DISPUTE_RESOLVED,
                to_email="legacy@example.invalid",
                context={"deal_reference": "ST-1"},
            )
        )
        for part in (text, html):
            assert "as: ." not in part
            assert "has resolved this dispute." in part

    def test_a_payout_update_with_no_status_still_reads_as_a_sentence(self):
        _, text, html = outbox.render_parts(
            OutboundMessage(
                key="legacy-payout-status",
                kind=OutboundMessage.Kind.PAYOUT_STATUS,
                to_email="legacy@example.invalid",
                context={"deal_reference": "ST-1"},
            )
        )
        for part in (text, html):
            assert "is now ." not in part
            assert "payout was updated" in part

    def test_the_label_is_still_used_when_the_service_supplies_it(self):
        _, text, _ = outbox.render_parts(
            OutboundMessage(
                key="current-dispute-resolved",
                kind=OutboundMessage.Kind.DISPUTE_RESOLVED,
                to_email="current@example.invalid",
                context={"deal_reference": "ST-1", "resolution_label": "Partial split"},
            )
        )
        assert "as: Partial split." in text
