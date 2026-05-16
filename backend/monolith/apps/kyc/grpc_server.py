"""gRPC server for the KYCSubmissionService contract.

The Go kyc-service uploads document images to MinIO/S3, then calls
RecordSubmission here so Django can durably INSERT the kyc_submission row.

Idempotency: `idempotency_key` is unique. On retry of the same logical
submission (flaky mobile networks), the existing row is returned and
`created=False` so the Go side can surface a 200 instead of 201.

Channel security: mTLS in production (CLAUDE.md §G5). Static bearer is
permitted only in docker-compose dev (`GRPC_AUTH_MODE=bearer`).

Run with: `python manage.py runkycgrpc`  (see management/commands/).
"""

from __future__ import annotations

import logging
import re

import grpc
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.kyc.grpc_gen import kyc_pb2, kyc_pb2_grpc
from apps.kyc.models import KycSubmission

log = logging.getLogger(__name__)

User = get_user_model()

_IDEMPOTENCY_KEY_RE = re.compile(r"^[0-9a-f]{32}$")


# Two enum mappings — proto uses SCREAMING_SNAKE constants, Django uses
# snake_case strings. Mismatches here are silent data bugs in admin so
# keep these as the single source of truth.
_DOC_TYPE_PROTO_TO_DJANGO = {
    kyc_pb2.DOCUMENT_TYPE_ID_CARD: KycSubmission.DocumentType.ID_CARD,
    kyc_pb2.DOCUMENT_TYPE_PASSPORT: KycSubmission.DocumentType.PASSPORT,
    kyc_pb2.DOCUMENT_TYPE_DRIVING_LICENSE: KycSubmission.DocumentType.DRIVING_LICENSE,
}

_STATUS_DJANGO_TO_PROTO = {
    KycSubmission.Status.PENDING: kyc_pb2.STATUS_PENDING,
    KycSubmission.Status.APPROVED: kyc_pb2.STATUS_APPROVED,
    KycSubmission.Status.REJECTED: kyc_pb2.STATUS_REJECTED,
    KycSubmission.Status.EXPIRED: kyc_pb2.STATUS_EXPIRED,
}


class KYCSubmissionServicer(kyc_pb2_grpc.KYCSubmissionServiceServicer):
    """Implements the RecordSubmission RPC.

    Single responsibility: take metadata, write a row, return its id.
    No image-byte handling — the Go side owns the S3 path.
    """

    def RecordSubmission(self, request, context):
        # ── validate inputs at the boundary ────────────────────────────
        if request.user_id <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")

        doc_type = _DOC_TYPE_PROTO_TO_DJANGO.get(request.document_type)
        if doc_type is None:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"document_type {request.document_type} is unspecified or unknown",
            )

        key = request.idempotency_key
        if not _IDEMPOTENCY_KEY_RE.match(key or ""):
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "idempotency_key must be 32 lowercase hex chars (UUIDv4 hex)",
            )

        if not request.front_image_key:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "front_image_key is required"
            )

        # Passport submissions legitimately have no back image. Other
        # document types are validated upstream by the Go multipart
        # handler, so don't double-validate here — that just creates
        # places where the rules drift apart.

        # ── idempotent insert ──────────────────────────────────────────
        # The fast path: look up by key. If found, return existing row.
        existing = KycSubmission.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return self._response(existing, created=False)

        # Verify the user exists. We use FK PROTECT so a bad user_id
        # would raise IntegrityError, but checking up front gives a
        # cleaner NOT_FOUND than a generic INTERNAL.
        if not User.objects.filter(pk=request.user_id).exists():
            context.abort(
                grpc.StatusCode.NOT_FOUND, f"user {request.user_id} does not exist"
            )

        try:
            with transaction.atomic():
                row = KycSubmission.objects.create(
                    user_id=request.user_id,
                    document_type=doc_type,
                    idempotency_key=key,
                    front_image_key=request.front_image_key,
                    back_image_key=request.back_image_key or "",
                    selfie_image_key=request.selfie_image_key or "",
                    # status defaults to PENDING via the model
                )
        except IntegrityError:
            # Race: another concurrent request inserted the same key
            # between our lookup and our insert. Re-read and return
            # idempotently.
            row = KycSubmission.objects.get(idempotency_key=key)
            return self._response(row, created=False)

        log.info(
            "kyc.record_submission created",
            extra={"submission_id": row.id, "user_id": row.user_id},
        )
        return self._response(row, created=True)

    @staticmethod
    def _response(row: KycSubmission, *, created: bool):
        return kyc_pb2.RecordSubmissionResponse(
            submission_id=row.id,
            created=created,
            status=_STATUS_DJANGO_TO_PROTO.get(row.status, kyc_pb2.STATUS_UNSPECIFIED),
        )
