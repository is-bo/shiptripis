"""Private, authenticated payout evidence; never a public or presigned URL."""

import hashlib
import json
import uuid
from io import BytesIO
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables
from PIL import Image, UnidentifiedImageError

from apps.core.storage import storage_for
from apps.admin_panel.services import record_admin_action
from .models import PayoutEvidence
from .payout_profiles import require_capabilities, _traveler
from .sensitive_data import encrypt, decrypt

MAX_BYTES = 8 * 1024 * 1024
#: The Traveler's own evidence that the CCP/RIP they typed is their account.
#: The wording is approved and is carried verbatim in all three languages; it is
#: never machine-translated, abbreviated or paraphrased, and it names no other
#: banking identifier.
CHEQUE_LABELS = {
    "fr": "Photo du chèque barré complet",
    "ar": "صورة كاملة لشيك مُسطَّر",
    "en": "Photo of the full crossed cheque",
}
#: A different document, from a different person, proving a different thing:
#: that a ShipTrip Finance operator performed the outgoing DZD transfer. The
#: two are never presented under one heading, because attaching one where the
#: other belongs is an evidence failure that survives into the audit trail.
RECEIPT_LABELS = {
    "fr": "Reçu du virement",
    "ar": "إيصال التحويل",
    "en": "Transfer receipt",
}
FORMATS = {
    "JPEG": ("image/jpeg", {".jpg", ".jpeg"}),
    "PNG": ("image/png", {".png"}),
    "WEBP": ("image/webp", {".webp"}),
}


@sensitive_variables()
def upload_evidence(*, actor, upload, purpose="account_document"):
    if purpose == "account_document":
        _traveler(actor)
    elif purpose == "transfer_receipt":
        require_capabilities(
            actor, "view_payout_sensitive", "view_payout_evidence", "retry_payouts"
        )
    else:
        raise ValidationError("Invalid evidence purpose.")
    body = upload.read(MAX_BYTES + 1)
    if not body or len(body) > MAX_BYTES:
        raise ValidationError("Evidence image exceeds the size limit.")
    try:
        with Image.open(BytesIO(body)) as img:
            expected_mime, extensions = FORMATS[img.format]
            if img.width * img.height > 20_000_000 or getattr(img, "n_frames", 1) != 1:
                raise ValueError
            img.verify()
        extension = PurePosixPath(upload.name.replace("\\", "/")).suffix.lower()
        if upload.content_type != expected_mime or extension not in extensions:
            raise ValueError
    except (
        ValueError,
        KeyError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ):
        raise ValidationError("A valid JPEG, PNG or WebP image is required.") from None
    import base64

    evidence = PayoutEvidence(
        owner=actor,
        purpose=purpose,
        object_key=f"payout/{'account-documents' if purpose == 'account_document' else 'transfer-receipts'}/{uuid.uuid4().hex}",
        digest=hashlib.sha256(body).hexdigest(),
        mime_type=expected_mime,
        size_bytes=len(body),
        upload_state="complete",
    )
    envelope = encrypt(
        base64.b64encode(body).decode("ascii"),
        model="PayoutEvidence",
        record=evidence.public_reference,
        field="image",
    )
    evidence.encryption_key_id = json.loads(envelope)["kid"]
    storage_for("payout").put(
        evidence.object_key, envelope.encode(), "application/octet-stream"
    )
    evidence.save()
    record_admin_action(
        actor=actor,
        action="payout_evidence.uploaded",
        target=evidence,
        after={"purpose": purpose},
    )
    return evidence


@sensitive_variables()
def read_evidence(*, actor, reference):
    require_capabilities(actor, "view_payout_sensitive", "view_payout_evidence")
    evidence = PayoutEvidence.objects.get(
        public_reference=reference, upload_state="complete"
    )
    import base64

    encrypted = storage_for("payout").get(evidence.object_key).decode()
    body = base64.b64decode(
        decrypt(
            encrypted,
            model="PayoutEvidence",
            record=evidence.public_reference,
            field="image",
        ),
        validate=True,
    )
    if (
        len(body) != evidence.size_bytes
        or hashlib.sha256(body).hexdigest() != evidence.digest
    ):
        raise ValidationError("Evidence integrity check failed.")
    record_admin_action(actor=actor, action="payout_evidence.viewed", target=evidence)
    return body, evidence.mime_type
