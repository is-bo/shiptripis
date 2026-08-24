"""Tests for the KYCSubmissionServicer.

We exercise the servicer directly (no real gRPC channel) since the
servicer's invariants — enum mapping, idempotency, validation — are
what we care about. The transport-layer concerns (mTLS, max message
size, bearer interceptor) are configured in runkycgrpc.py and aren't
worth integration-testing inside the Django suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import grpc
from django.test import TestCase

from apps.accounts.models import User
from apps.kyc.grpc_gen import kyc_pb2
from apps.kyc.grpc_server import KYCSubmissionServicer
from apps.kyc.models import KycSubmission


def _ctx() -> MagicMock:
    """Servicer context stub. abort() raises so test fail-paths are loud."""
    ctx = MagicMock()

    def _abort(code, msg):
        raise grpc.RpcError(f"{code}: {msg}")

    ctx.abort.side_effect = _abort
    return ctx


def _user(suffix: str) -> User:
    return User.objects.create_user(
        username=f"kyc_user_{suffix}",
        email=f"kyc_{suffix}@example.com",
        password="Sup3rStrongPass!",
        full_name=f"KYC User {suffix}",
        phone=f"+21355500{suffix}",
        wilaya="16",
    )


def _req(**overrides) -> kyc_pb2.RecordSubmissionRequest:
    defaults = dict(
        user_id=1,
        document_type=kyc_pb2.DOCUMENT_TYPE_ID_CARD,
        idempotency_key="a" * 32,
        front_image_key="kyc-docs/1/abc-front.jpg",
        back_image_key="kyc-docs/1/abc-back.jpg",
        selfie_image_key="kyc-docs/1/abc-selfie.jpg",
    )
    defaults.update(overrides)
    return kyc_pb2.RecordSubmissionRequest(**defaults)


class RecordSubmissionTests(TestCase):
    def setUp(self):
        self.servicer = KYCSubmissionServicer()
        self.user = _user("1")

    def test_creates_row_on_first_call(self):
        resp = self.servicer.RecordSubmission(
            _req(user_id=self.user.id), _ctx()
        )
        self.assertTrue(resp.created)
        self.assertEqual(resp.status, kyc_pb2.STATUS_PENDING)
        self.assertEqual(KycSubmission.objects.count(), 1)
        row = KycSubmission.objects.get()
        self.assertEqual(row.user_id, self.user.id)
        self.assertEqual(row.document_type, KycSubmission.DocumentType.ID_CARD)
        self.assertEqual(row.idempotency_key, "a" * 32)

    def test_idempotent_replay_returns_existing(self):
        first = self.servicer.RecordSubmission(
            _req(user_id=self.user.id), _ctx()
        )
        second = self.servicer.RecordSubmission(
            _req(user_id=self.user.id), _ctx()
        )
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.submission_id, second.submission_id)
        self.assertEqual(KycSubmission.objects.count(), 1)

    def test_different_keys_create_separate_rows(self):
        self.servicer.RecordSubmission(
            _req(user_id=self.user.id, idempotency_key="a" * 32), _ctx()
        )
        self.servicer.RecordSubmission(
            _req(user_id=self.user.id, idempotency_key="b" * 32), _ctx()
        )
        self.assertEqual(KycSubmission.objects.count(), 2)

    def test_rejects_unspecified_document_type(self):
        with self.assertRaises(grpc.RpcError):
            self.servicer.RecordSubmission(
                _req(user_id=self.user.id, document_type=kyc_pb2.DOCUMENT_TYPE_UNSPECIFIED),
                _ctx(),
            )

    def test_rejects_bad_idempotency_key(self):
        for bad in ["", "short", "A" * 32, "g" * 32, " " * 32]:
            with self.subTest(key=bad):
                with self.assertRaises(grpc.RpcError):
                    self.servicer.RecordSubmission(
                        _req(user_id=self.user.id, idempotency_key=bad), _ctx()
                    )

    def test_rejects_missing_user(self):
        with self.assertRaises(grpc.RpcError):
            self.servicer.RecordSubmission(_req(user_id=999_999), _ctx())

    def test_rejects_missing_front_key(self):
        with self.assertRaises(grpc.RpcError):
            self.servicer.RecordSubmission(
                _req(user_id=self.user.id, front_image_key=""), _ctx()
            )

    def test_passport_without_back_is_allowed(self):
        resp = self.servicer.RecordSubmission(
            _req(
                user_id=self.user.id,
                document_type=kyc_pb2.DOCUMENT_TYPE_PASSPORT,
                back_image_key="",
            ),
            _ctx(),
        )
        self.assertTrue(resp.created)
        self.assertEqual(KycSubmission.objects.get().back_image_key, "")

    def test_status_enum_mapping_on_replay(self):
        # First create, then mutate row to APPROVED and replay — the
        # replay should reflect the current status, not PENDING.
        first = self.servicer.RecordSubmission(
            _req(user_id=self.user.id), _ctx()
        )
        KycSubmission.objects.filter(pk=first.submission_id).update(
            status=KycSubmission.Status.APPROVED
        )
        second = self.servicer.RecordSubmission(
            _req(user_id=self.user.id), _ctx()
        )
        self.assertFalse(second.created)
        self.assertEqual(second.status, kyc_pb2.STATUS_APPROVED)
