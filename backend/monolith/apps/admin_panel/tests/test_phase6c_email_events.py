"""Authoritative trust-review transitions arm one localized email obligation."""

from django.test import TestCase

from apps.finance.tests.factories import build_scenario, make_user
from apps.kyc.models import KycSubmission
from apps.notifications.models import OutboundMessage
from apps.trips.models import JourneyLeg, JourneyLegProof

from ..permissions import AdminRole, assign_admin_roles
from ..services import review_flight_proof, review_kyc_submission


class KycStatusEmailTests(TestCase):
    def setUp(self):
        self.reviewer = make_user("p6c-kyc-reviewer@example.test", is_staff=True)
        assign_admin_roles(self.reviewer, (AdminRole.TRUST,))

    def _submission(self, suffix: str, *, language: str) -> KycSubmission:
        user = make_user(f"p6c-kyc-{suffix}@example.test")
        user.preferred_language = language
        user.save(update_fields=("preferred_language",))
        return KycSubmission.objects.create(
            user=user,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key=f"p6c-kyc-{suffix:0<23}"[:32],
            front_image_key=f"kyc/p6c/{suffix}/front.jpg",
        )

    def test_approved_transition_queues_once(self):
        submission = self._submission("approved", language="fr")

        review_kyc_submission(
            actor=self.reviewer,
            submission_id=submission.pk,
            decision=KycSubmission.Status.APPROVED,
        )
        review_kyc_submission(
            actor=self.reviewer,
            submission_id=submission.pk,
            decision=KycSubmission.Status.APPROVED,
        )

        message = OutboundMessage.objects.get(
            key=f"kyc_status:{submission.pk}:approved"
        )
        self.assertEqual(message.context, {"status": "approved", "reason": ""})
        self.assertEqual(message.language, "fr")
        self.assertEqual(
            OutboundMessage.objects.filter(
                kind=OutboundMessage.Kind.KYC_STATUS,
                recipient_user=submission.user,
            ).count(),
            1,
        )

    def test_rejected_transition_queues_action_required_once(self):
        submission = self._submission("rejected", language="ar")

        review_kyc_submission(
            actor=self.reviewer,
            submission_id=submission.pk,
            decision=KycSubmission.Status.REJECTED,
            reason="The image is unreadable.",
        )
        review_kyc_submission(
            actor=self.reviewer,
            submission_id=submission.pk,
            decision=KycSubmission.Status.REJECTED,
            reason="A replay must not change the email.",
        )

        message = OutboundMessage.objects.get(
            key=f"kyc_status:{submission.pk}:rejected"
        )
        self.assertEqual(message.context["status"], "action_required")
        self.assertEqual(message.context["reason"], "The image is unreadable.")
        self.assertEqual(message.language, "ar")


class FlightProofStatusEmailTests(TestCase):
    def setUp(self):
        self.reviewer = make_user("p6c-proof-reviewer@example.test", is_staff=True)
        assign_admin_roles(self.reviewer, (AdminRole.TRUST,))

    def _proof(self, suffix: str, *, language: str) -> JourneyLegProof:
        scenario = build_scenario(prefix=f"p6c-proof-{suffix}")
        scenario.traveler.preferred_language = language
        scenario.traveler.save(update_fields=("preferred_language",))
        JourneyLeg.objects.filter(pk=scenario.leg.pk).update(
            mode=JourneyLeg.Mode.FLIGHT,
            flight_number="AH1007",
        )
        return JourneyLegProof.objects.create(
            leg=scenario.leg,
            bucket="private-proof",
            object_key=f"journeys/p6c/{suffix}.jpg",
        )

    def test_approved_transition_queues_once(self):
        proof = self._proof("approved", language="fr")

        review_flight_proof(
            actor=self.reviewer,
            proof_id=proof.pk,
            decision=JourneyLegProof.Status.APPROVED,
        )
        review_flight_proof(
            actor=self.reviewer,
            proof_id=proof.pk,
            decision=JourneyLegProof.Status.APPROVED,
        )

        message = OutboundMessage.objects.get(
            key=f"flight_proof_status:{proof.pk}:approved"
        )
        self.assertEqual(message.context["status"], "approved")
        self.assertEqual(message.language, "fr")
        self.assertEqual(
            OutboundMessage.objects.filter(
                kind=OutboundMessage.Kind.FLIGHT_PROOF_STATUS,
                recipient_user=proof.leg.journey.traveler,
            ).count(),
            1,
        )

    def test_rejected_transition_queues_action_required_once(self):
        proof = self._proof("rejected", language="ar")

        review_flight_proof(
            actor=self.reviewer,
            proof_id=proof.pk,
            decision=JourneyLegProof.Status.REJECTED,
            reason="Upload the complete ticket.",
        )
        review_flight_proof(
            actor=self.reviewer,
            proof_id=proof.pk,
            decision=JourneyLegProof.Status.REJECTED,
            reason="A replay must not change the email.",
        )

        message = OutboundMessage.objects.get(
            key=f"flight_proof_status:{proof.pk}:rejected"
        )
        self.assertEqual(message.context["status"], "action_required")
        self.assertEqual(message.context["reason"], "Upload the complete ticket.")
        self.assertEqual(message.language, "ar")
