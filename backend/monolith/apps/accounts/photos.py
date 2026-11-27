"""Profile photos (spec 21). The one home of the rule.

A member may add one optional photo, replace it and remove it. It is visible
from the moment it is stored, to everyone who can see the person's first name,
guests included (owner decision of 2026-11-24): there is no staff pre-check.
Staff can remove any photo from the console with a reason, which is audited and
which the member is shown.

**What is stored.** Never the uploaded file. The bytes are checked like every
image upload (declared type, real type, size, pixel ceiling), then re-encoded
by `apps.core.storage.square_jpeg_without_metadata`: upright, a centred 512 px
square, a JPEG with no metadata. The object goes to the private media store
under a random key that never contains the user id.

**What is published.** `public_photo(user)`: ``{"url", "version"}`` or None.
The URL is signed when the payload is built (nothing caches it) and lives for
`PROFILE_PHOTO_URL_TTL_SECONDS`; the app caches the image by `version`. Only an
active photo of an active, unbanned account is published. The owner reads
`own_photo(user)`, which also says when Wassla removed the photo, and why.

**Races, decided by `version`.** Every write takes the member's row lock,
whatever the account's state, so the member's own uploads and removals, a
staff removal and account deletion run one after the other. Each upload gets a new random version. A staff removal names the
version the operator was looking at and applies only while that version is
still the active one: a replacement that lands first makes the removal refuse
with `profile_photo_changed`, so a fresh photo is never marked removed unseen,
and a removal that lands first leaves nothing visible, because the removed
object is deleted and a later upload is a new photo.

**Stored objects: one cleanup rule.** "Delete object K once no photo row
names it", run by a durable `ScheduledJob` (``profile_photo_object_delete``),
so no lost response, failed delete or dead worker can leave an image behind:

- an upload records its job (an hour later) before the object is written, which
  covers a failed write, a lost commit acknowledgement and a crash;
- replacing and staff removal record the job for the old object in the same
  transaction as the decision; deleting a row (the member's removal, account
  deletion, a cascade or a bulk delete) records it from `post_delete`;
- after commit, one immediate attempt is the fast path; the job retries until
  storage confirms, an object already gone counts as deleted, and an object a
  row names is never deleted.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.core.storage import (
    ImageRejected,
    ext_for_content_type,
    image_bytes_match_extension,
    make_key,
    square_jpeg_without_metadata,
    storage_for,
    store_for_bucket,
)

from .models import ProfilePhoto

logger = logging.getLogger(__name__)

#: The private media store, Django's own credential (G4).
PHOTO_STORE = "media"
#: Object keys are ``profile-photos/<random>.jpg``: nothing in them names a person.
KEY_PREFIX = "profile-photos"
#: The side of the stored square, in pixels.
PHOTO_SIZE = 512
#: The upload limit, the same as a parcel photo's.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: What a multipart body may add around the photo (boundaries, part headers).
MULTIPART_ALLOWANCE = 64 * 1024
#: An upload's own cleanup job runs this long after it starts: by then the
#: upload has long committed (the object is named, so it stays) or failed.
UPLOAD_CHECK_DELAY = timedelta(hours=1)
#: The cleanup job's retry budget. With the job loop's backoff (capped at six
#: hours) that is about ten days, then a failed job staff see and can retry.
CLEANUP_MAX_ATTEMPTS = 48
OBJECT_JOB_PREFIX = "profile_photo_object"

#: The audit action of a staff removal.
AUDIT_REMOVED = "profile_photo.removed"
#: The console capability that removes a photo.
MODERATE_PERMISSION = "moderate_profile_photos"

# Stable refusal codes. The app words them; `detail` is for logs and tests.
PHOTO_MISSING = "profile_photo_missing"
PHOTO_TOO_LARGE = "profile_photo_too_large"
PHOTO_TYPE_UNSUPPORTED = "profile_photo_media_type_unsupported"
PHOTO_STORAGE_UNAVAILABLE = "profile_photo_storage_unavailable"
PHOTO_NOT_ACTIVE = "profile_photo_not_active"
PHOTO_CHANGED = "profile_photo_changed"
REASON_REQUIRED = "reason_required"
ACCOUNT_INACTIVE = "account_inactive"


class PhotoRefused(Exception):
    """A refused photo write, with a stable code, an HTTP status and extras."""

    def __init__(self, code: str, detail: str, *, status: int = 400, **extra):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status
        self.extra = extra

    @property
    def payload(self) -> dict:
        return {"code": self.code, "detail": self.detail, **self.extra}


class PhotoUploadHandler(FileUploadHandler):
    """The upload handler of `PUT /api/me/photo`: memory only, never a temp file.

    Django's default handlers spill a file part to a temporary file once the
    body passes `FILE_UPLOAD_MAX_MEMORY_SIZE`, which a valid photo near the limit
    does, so the original, metadata and all, would touch the disk. This one
    keeps every byte in memory and refuses with `profile_photo_too_large` as
    soon as the body or the files in it pass the limit, before reading on.
    """

    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length > MAX_UPLOAD_BYTES + MULTIPART_ALLOWANCE:
            raise _too_large()

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file = BytesIO()

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_UPLOAD_BYTES:
            raise _too_large()
        self.file.write(raw_data)

    def file_complete(self, file_size):
        self.file.seek(0)
        return InMemoryUploadedFile(
            file=self.file,
            field_name=self.field_name,
            name=self.file_name,
            content_type=self.content_type,
            size=file_size,
            charset=self.charset,
            content_type_extra=self.content_type_extra,
        )


def _too_large() -> PhotoRefused:
    return PhotoRefused(
        PHOTO_TOO_LARGE, "File exceeds 10 MiB.", status=413, max_bytes=MAX_UPLOAD_BYTES
    )


def _new_version() -> str:
    return secrets.token_urlsafe(12)


def _url_ttl() -> int:
    return int(getattr(settings, "PROFILE_PHOTO_URL_TTL_SECONDS", 1800) or 1800)


def signed_url(photo: ProfilePhoto) -> str | None:
    """A fresh signed read of the photo's object, or None if it cannot be signed.

    Signing is local; a photo is never worth failing the page it decorates.
    Payloads go through `public_photo` or `own_photo`; the console calls this
    directly, because staff see a photo whatever the account's state.
    """

    try:
        return store_for_bucket(photo.bucket, default=PHOTO_STORE).presigned_get(
            photo.object_key, expires_in=_url_ttl()
        )
    except Exception:  # noqa: BLE001 - logged; the person shows initials
        logger.exception("profile photo presign failed", extra={"profile_photo_id": photo.pk})
        return None


def _photo_of(user) -> ProfilePhoto | None:
    """The user's photo row as loaded. List surfaces load it with their people
    (``select_related("<person>__profile_photo")``), so this reads nothing."""

    try:
        return user.profile_photo
    except ProfilePhoto.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def public_photo(user) -> dict | None:
    """``{"url", "version"}`` for a person's active photo, or None.

    The block every payload that shows a person by name carries, for guests
    and members alike. A removed photo, and any photo of a banned or
    deactivated account, is None.
    """

    if user is None or not user.is_active or user.is_banned:
        return None
    photo = _photo_of(user)
    if photo is None or photo.state != ProfilePhoto.State.ACTIVE:
        return None
    url = signed_url(photo)
    if url is None:
        return None
    return {"url": url, "version": photo.version}


def own_photo(user) -> dict | None:
    """The member's own view of their photo (`GET /api/me`), or None.

    Always the same five keys: ``state`` (`active` or `removed`), ``url``,
    ``version``, ``removed_at`` and ``reason``. An active photo has a URL and
    no removal; a photo Wassla removed has no URL, the time, and the reason
    staff wrote for the member.
    """

    photo = _photo_of(user)
    return None if photo is None else own_view(photo)


def own_view(photo: ProfilePhoto) -> dict:
    """`own_photo` for a row already in hand (the answer to an upload)."""

    if photo.state == ProfilePhoto.State.REMOVED:
        return {
            "state": ProfilePhoto.State.REMOVED.value,
            "url": None,
            "version": photo.version,
            "removed_at": photo.removed_at.isoformat() if photo.removed_at else None,
            "reason": photo.removed_reason,
        }
    return {
        "state": ProfilePhoto.State.ACTIVE.value,
        "url": signed_url(photo),
        "version": photo.version,
        "removed_at": None,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# The member's writes
# ---------------------------------------------------------------------------


def _hold_member(user_id: int):
    """Take the member's row lock, whatever the account's state, and return the
    row (None once it is gone).

    Every photo write takes it, so writes on one member's photo queue. Whether
    the member may still upload is decided after it is held (`_may_upload`)."""

    return (
        get_user_model()
        .objects.select_for_update(no_key=True)
        .filter(pk=user_id)
        .first()
    )


def _may_upload(member) -> bool:
    return member is not None and member.is_active and not member.is_banned


def prepare_upload(upload) -> bytes:
    """Check one uploaded file and return the bytes to store, or refuse.

    The declared type is a claim, so the real type is read from the bytes and
    must agree. The returned bytes are the server's re-encoding, never the
    upload.
    """

    if upload is None:
        raise PhotoRefused(PHOTO_MISSING, "Send the image under the 'photo' field.")
    if upload.size > MAX_UPLOAD_BYTES:
        raise _too_large()
    ext = ext_for_content_type(upload.content_type or "")
    if ext is None:
        raise PhotoRefused(
            PHOTO_TYPE_UNSUPPORTED, "Only JPEG, PNG and WebP images are allowed.", status=415
        )
    body = upload.read()
    if not image_bytes_match_extension(body, ext):
        raise PhotoRefused(
            PHOTO_TYPE_UNSUPPORTED,
            "File content is not a valid image of the declared type.",
            status=415,
        )
    try:
        return square_jpeg_without_metadata(body, size=PHOTO_SIZE)
    except ImageRejected as exc:
        raise PhotoRefused(
            PHOTO_TYPE_UNSUPPORTED, "File content is not a valid image.", status=415
        ) from exc


def replace_photo(user, upload) -> ProfilePhoto:
    """Store a new photo for ``user``, replacing any photo or removal.

    The new object's cleanup job is recorded first, then the object is written
    outside any lock under a fresh key, then the row points at it under the
    member's lock. Whatever happens after the job is recorded, the object is
    deleted unless a row names it. The previous object is released in the same
    transaction as the replacement.
    """

    body = prepare_upload(upload)
    store = storage_for(PHOTO_STORE)
    try:
        bucket = store.require_bucket()
    except Exception:
        logger.exception("profile photo storage is not configured")
        raise _storage_unavailable() from None
    key = make_key(KEY_PREFIX, "jpg")
    _schedule_object_check(
        bucket, key, purpose="upload", run_at=timezone.now() + UPLOAD_CHECK_DELAY
    )
    try:
        store.put(key, body, "image/jpeg")
    except Exception:
        # The provider's message names buckets and keys: log it, never send it.
        # The write may still have landed; the upload's job deletes it.
        logger.exception("profile photo upload failed")
        raise _storage_unavailable() from None

    try:
        with transaction.atomic():
            if not _may_upload(_hold_member(user.pk)):
                raise PhotoRefused(ACCOUNT_INACTIVE, "This account is not active.", status=403)
            photo = ProfilePhoto.objects.filter(user_id=user.pk).first()
            if photo is None:
                photo = ProfilePhoto(user_id=user.pk)
            else:
                release_object(photo.bucket, photo.object_key)
            photo.state = ProfilePhoto.State.ACTIVE
            photo.bucket = bucket
            photo.object_key = key
            photo.bytes = len(body)
            photo.version = _new_version()
            photo.uploaded_at = timezone.now()
            photo.removed_at = None
            photo.removed_by = None
            photo.removed_reason = ""
            photo.save()
    except PhotoRefused:
        # Refused before anything committed, so no row names the object: try
        # now. Any other failure may follow a commit whose acknowledgement was
        # lost, so it is left to the job, which keeps an object a row names.
        _delete_now(bucket, key)
        raise
    return photo


def remove_own_photo(user, *, version: str | None = None) -> None:
    """The member removes their photo, or dismisses a removal notice.

    The row goes, and `post_delete` releases its object. Removing when there
    is no photo changes nothing. Never refused for the account's state.

    ``version`` is the photo the member was looking at (the app always sends
    it). If the member put another photo up since, on a second device say,
    nothing changes and `profile_photo_changed` answers, so a notice or a photo
    the member is no longer looking at never takes the new one with it.
    """

    with transaction.atomic():
        _hold_member(user.pk)
        photo = ProfilePhoto.objects.filter(user_id=user.pk).first()
        if photo is None:
            return
        if version is not None and photo.version != version:
            raise PhotoRefused(
                PHOTO_CHANGED,
                "The photo changed since it was shown. Look at it again.",
                status=409,
            )
        photo.delete()


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


def remove_by_staff(*, user, actor, version: str, reason: str) -> ProfilePhoto:
    """Remove ``user``'s active photo, audited, if it is still ``version``.

    ``version`` is the photo the operator was shown. If the member replaced
    or removed it meanwhile, nothing changes and `profile_photo_changed` (or
    `profile_photo_not_active`) answers, so the operator decides again on what
    is really there. The member is shown ``reason``.
    """

    from apps.admin_panel.services import record_admin_action

    reason = (reason or "").strip()
    if not reason:
        raise PhotoRefused(REASON_REQUIRED, "A reason is required.")
    with transaction.atomic():
        _hold_member(user.pk)
        photo = ProfilePhoto.objects.filter(user_id=user.pk).first()
        if photo is None or photo.state != ProfilePhoto.State.ACTIVE:
            raise PhotoRefused(
                PHOTO_NOT_ACTIVE, "This person has no photo to remove.", status=409
            )
        if photo.version != version:
            raise PhotoRefused(
                PHOTO_CHANGED,
                "The photo changed since the page was opened. Look at it again.",
                status=409,
            )
        before = {"state": photo.state, "version": photo.version}
        release_object(photo.bucket, photo.object_key)
        photo.state = ProfilePhoto.State.REMOVED
        photo.bucket = ""
        photo.object_key = ""
        photo.removed_at = timezone.now()
        photo.removed_by = actor
        photo.removed_reason = reason[:500]
        photo.save()
        record_admin_action(
            actor=actor,
            action=AUDIT_REMOVED,
            target=user,
            before=before,
            after={"state": photo.state, "version": photo.version},
            reason=reason,
        )
    return photo


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------


def erase(user) -> None:
    """Delete the photo row; `post_delete` releases its object.

    Called by `apps.accounts.deletion._erase`, inside its transaction and
    under its lock on the member's row.
    """

    ProfilePhoto.objects.filter(user_id=user.pk).delete()


# ---------------------------------------------------------------------------
# Stored objects: "delete object K once no row names it"
# ---------------------------------------------------------------------------


def _storage_unavailable() -> PhotoRefused:
    return PhotoRefused(
        PHOTO_STORAGE_UNAVAILABLE, "Photo storage is temporarily unavailable.", status=503
    )


def _already_gone(exc: Exception) -> bool:
    response = getattr(exc, "response", None) or {}
    return str(response.get("Error", {}).get("Code", "")) in {"NoSuchKey", "404"}


def delete_if_unreferenced(bucket: str, key: str) -> str:
    """Delete object ``key`` unless a photo row names it. Raises if storage fails.

    Keys are random and never reused, so a key no row names now will never be
    named again (an upload's own key is checked an hour after it starts).
    """

    if ProfilePhoto.objects.filter(object_key=key).exists():
        return "referenced"
    try:
        store_for_bucket(bucket, default=PHOTO_STORE).delete(key)
    except Exception as exc:
        if not _already_gone(exc):
            raise
    return "deleted"


def _delete_now(bucket: str, key: str) -> None:
    try:
        delete_if_unreferenced(bucket, key)
    except Exception:  # noqa: BLE001 - the durable job retries it
        logger.warning("profile photo object delete failed; its job retries", exc_info=True)


def _schedule_object_check(bucket: str, key: str, *, purpose: str, run_at) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    schedule_job(
        kind=ScheduledJob.Kind.PROFILE_PHOTO_OBJECT_DELETE,
        key=f"{OBJECT_JOB_PREFIX}:{purpose}:{key}",
        run_at=run_at,
        payload={"bucket": bucket, "key": key},
        max_attempts=CLEANUP_MAX_ATTEMPTS,
    )


def release_object(bucket: str, key: str) -> None:
    """A row stopped naming ``key``: delete the object once nothing does.

    The job is recorded in the caller's transaction, so it exists exactly when
    the decision does; after commit, one immediate attempt is the fast path.
    """

    if not key:
        return
    _schedule_object_check(bucket, key, purpose="release", run_at=timezone.now())
    transaction.on_commit(lambda: _delete_now(bucket, key))


@receiver(post_delete, sender=ProfilePhoto, dispatch_uid="accounts.photos.release_deleted")
def _release_deleted_photo(sender, instance: ProfilePhoto, **kwargs) -> None:
    """Every deleted row releases its object: the member's removal, account
    deletion, a cascade from the user, or a bulk delete."""

    release_object(instance.bucket, instance.object_key)


def handle_object_delete_job(payload: dict) -> str:
    """The ``profile_photo_object_delete`` job. Retried until storage confirms."""

    from apps.finance.jobs import PermanentJobError, RetryableJobError

    key = payload.get("key")
    if not isinstance(key, str) or not key.startswith(f"{KEY_PREFIX}/"):
        raise PermanentJobError("Not a profile photo key.", code="profile_photo_key_invalid")
    try:
        return delete_if_unreferenced(str(payload.get("bucket") or ""), key)
    except Exception:
        logger.warning("profile photo object delete failed", exc_info=True)
        raise RetryableJobError(
            "Photo storage did not confirm the delete.",
            code="profile_photo_storage_unavailable",
        ) from None
