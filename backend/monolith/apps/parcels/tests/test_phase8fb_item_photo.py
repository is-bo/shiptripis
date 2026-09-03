"""Phase 8F-B: the required item photo, and optional dimensions.

Two product rules are locked here, both from real device QA.

**Dimensions are optional.** The write contract used to require all three
measurements, while the form presented them as optional and the helper text
said so. A sender who left them empty was allowed forward through four steps
and then bounced back to the parcel step by three `length_cm`/`width_cm`/
`height_cm` errors the form had no input bound to — a silent rejection. They
are now genuinely optional; a *partial* set is still refused, once, under
`dimensions`, because pricing and capacity read a volume rather than a side.

**One photo of the actual item is required.** Not a profile picture: evidence
of the thing a traveller is agreeing to carry across a border. Enforced by
the server, so a stale or hostile client cannot post without it, and enforced
by *ordering* rather than by a later check — the photo is stored first and the
create call consumes it, so no failed upload can leave a live request with no
image behind it.

The storage assertions matter as much as the behavioural ones. Phase 8F-A
found every deployed flight-proof upload answering 500 because Django was
presigning a bucket owned by the Go KYC service's credential. An item photo
goes to `S3_BUCKET_PARCEL` — Django's own — and never to `S3_BUCKET_KYC`.
"""

from __future__ import annotations

import io
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.locations.models import Country, Place
from apps.parcels.models import DeliveryRequest, ParcelMedia, ParcelRequest
from apps.parcels.views import MAX_UPLOAD_BYTES

STAGE_URL = "/api/parcels/media"


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (48, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 120, 60)).save(buffer, format=fmt)
    return buffer.getvalue()


def _upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


def _make_user(email: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name="Sen Der",
        phone="+213555000333",
        wilaya="16",
    )


def _auth(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class _PhotoTestBase(APITestCase):
    """A sender, two canonical places, and a stubbed object store.

    `put_object` is patched rather than pointed at a real bucket: what these
    tests are about is which bucket the application *chose* and what it did
    with the outcome, not whether boto3 works.
    """

    def setUp(self):
        self.sender = _make_user(f"8fb-sender-{uuid4().hex[:8]}@example.com")
        self.client = _auth(self.sender)
        france = Country.objects.create(
            code="FR",
            name="France",
            source="phase8fb-test",
            source_id="country-fr",
            source_version="phase8fb",
        )
        algeria = Country.objects.create(
            code="DZ",
            name="Algeria",
            source="phase8fb-test",
            source_id="country-dz",
            source_version="phase8fb",
        )
        self.pickup_place = Place.objects.create(
            country=france,
            place_type=Place.PlaceType.LOCALITY,
            source="phase8fb-test",
            source_id="locality-paris",
            source_version="phase8fb",
            name="Paris",
        )
        self.delivery_place = Place.objects.create(
            country=algeria,
            place_type=Place.PlaceType.LOCALITY,
            source="phase8fb-test",
            source_id="locality-algiers",
            source_version="phase8fb",
            name="Algiers",
        )

    # -- helpers ----------------------------------------------------------

    def stage_photo(self, user: User | None = None) -> ParcelMedia:
        owner = user or self.sender
        return ParcelMedia.objects.create(
            parcel=None,
            uploaded_by=owner,
            purpose=ParcelMedia.Purpose.ITEM_PHOTO,
            bucket="shiptrip-parcel-test",
            object_key=f"parcels/staged/{owner.pk}/{uuid4().hex}.jpg",
            content_type="image/jpeg",
            bytes=2048,
        )

    def payload(self, **overrides) -> dict:
        now = timezone.now()
        body = {
            "pickup_place_id": self.pickup_place.pk,
            "delivery_place_id": self.delivery_place.pk,
            "ready_window_start": (now + timedelta(days=1)).isoformat(),
            "ready_window_end": (now + timedelta(days=1, hours=2)).isoformat(),
            "deadline_at": (now + timedelta(days=3)).isoformat(),
            "actual_weight_kg": "2.50",
            "declared_value_eur_cents": 12_500,
            "sender_proposed_reward_eur_cents": 3_000,
            "title": "Documents for Algiers",
            "description": "A sealed folder of personal documents.",
            "category": "documents",
            "handling_notes": "",
            "fragile": False,
            "description_is_accurate": True,
            "item_is_legal": True,
            "no_prohibited_goods": True,
            "declared_value_is_accurate": True,
            "customs_responsibilities_understood": True,
            "item_photo_media_id": self.stage_photo().pk,
        }
        body.update(overrides)
        return {k: v for k, v in body.items() if v is not _ABSENT}

    def create(self, **overrides):
        return self.client.post(
            reverse("parcels-delivery-v1-create"),
            self.payload(**overrides),
            format="json",
        )


class _Absent:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<absent>"


_ABSENT = _Absent()


# ---------------------------------------------------------------------------
# Staging the photo
# ---------------------------------------------------------------------------


class ItemPhotoStagingTests(_PhotoTestBase):
    def test_requires_authentication(self):
        response = APIClient().post(
            STAGE_URL,
            {"photo": _upload("item.jpg", _image_bytes(), "image/jpeg")},
            format="multipart",
        )
        assert response.status_code == 401

    def test_a_staged_photo_belongs_to_its_uploader_and_to_no_request(self):
        with patch("apps.parcels.views.put_object") as put:
            response = self.client.post(
                STAGE_URL,
                {"photo": _upload("item.jpg", _image_bytes(), "image/jpeg")},
                format="multipart",
            )

        assert response.status_code == 201, response.data
        media = ParcelMedia.objects.get(pk=response.data["id"])
        assert media.parcel_id is None
        assert media.uploaded_by_id == self.sender.pk
        assert media.purpose == ParcelMedia.Purpose.ITEM_PHOTO
        assert media.is_staged is True
        # The bucket Django's own credential owns — never the KYC bucket.
        assert media.bucket == "shiptrip-parcel"
        assert put.call_args.kwargs["bucket"] == "shiptrip-parcel"
        assert media.object_key.startswith(f"parcels/staged/{self.sender.pk}/")

    def test_the_response_never_carries_a_storage_key(self):
        with patch("apps.parcels.views.put_object"):
            response = self.client.post(
                STAGE_URL,
                {"photo": _upload("item.png", _image_bytes("PNG"), "image/png")},
                format="multipart",
            )

        assert response.status_code == 201
        assert set(response.data) == {
            "id",
            "purpose",
            "content_type",
            "bytes",
            "created_at",
        }
        body = str(response.data)
        assert "bucket" not in body
        assert "object_key" not in body

    @override_settings(S3_BUCKET_KYC="shiptrip-kyc-i7wgelkvyjp9")
    def test_the_kyc_bucket_is_not_reachable_from_this_endpoint(self):
        """The 8F-A credential mistake, guarded rather than remembered.

        Django's key has no grant on the KYC bucket, so writing an item photo
        there would fail in production exactly the way flight proof did. The
        assertion is on the bucket the code chose, because that is the part a
        future edit could get wrong silently.
        """

        with patch("apps.parcels.views.put_object") as put:
            self.client.post(
                STAGE_URL,
                {"photo": _upload("item.jpg", _image_bytes(), "image/jpeg")},
                format="multipart",
            )

        assert put.call_args.kwargs["bucket"] != "shiptrip-kyc-i7wgelkvyjp9"

    def test_a_missing_file_is_named_not_guessed(self):
        response = self.client.post(STAGE_URL, {}, format="multipart")
        assert response.status_code == 400
        assert response.data["code"] == "parcel_photo_missing"

    def test_a_pdf_is_refused_even_when_it_claims_to_be_a_jpeg(self):
        response = self.client.post(
            STAGE_URL,
            {"photo": _upload("item.jpg", b"%PDF-1.7\n%not an image", "image/jpeg")},
            format="multipart",
        )
        assert response.status_code == 415
        assert response.data["code"] == "parcel_photo_media_type_unsupported"
        assert ParcelMedia.objects.count() == 0

    def test_an_unsupported_declared_type_is_refused(self):
        response = self.client.post(
            STAGE_URL,
            {"photo": _upload("item.gif", _image_bytes("GIF"), "image/gif")},
            format="multipart",
        )
        assert response.status_code == 415
        assert response.data["code"] == "parcel_photo_media_type_unsupported"

    def test_webp_is_accepted(self):
        with patch("apps.parcels.views.put_object"):
            response = self.client.post(
                STAGE_URL,
                {"photo": _upload("item.webp", _image_bytes("WEBP"), "image/webp")},
                format="multipart",
            )
        assert response.status_code == 201, response.data

    def test_an_oversized_image_is_refused_before_it_reaches_storage(self):
        """The ceiling is lowered rather than the payload inflated.

        Posting an actual 10 MiB body through the test client to prove a
        comparison would make the suite slower and no more truthful. What
        matters is that the size gate runs *before* `put_object`, so a
        rejected upload never costs a write.
        """

        big_enough = _image_bytes(size=(64, 64))
        assert len(big_enough) > 64

        with (
            patch("apps.parcels.views.MAX_UPLOAD_BYTES", 64),
            patch("apps.parcels.views.put_object") as put,
        ):
            response = self.client.post(
                STAGE_URL,
                {"photo": _upload("big.jpg", big_enough, "image/jpeg")},
                format="multipart",
            )

        assert response.status_code == 413
        assert response.data["code"] == "parcel_photo_too_large"
        assert response.data["max_bytes"] == 64
        put.assert_not_called()
        assert ParcelMedia.objects.count() == 0

    def test_the_deployed_ceiling_is_the_documented_one(self):
        assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024

    def test_a_storage_failure_is_a_503_with_no_row_and_no_provider_detail(self):
        with patch(
            "apps.parcels.views.put_object", side_effect=RuntimeError("AccessDenied")
        ):
            response = self.client.post(
                STAGE_URL,
                {"photo": _upload("item.jpg", _image_bytes(), "image/jpeg")},
                format="multipart",
            )

        assert response.status_code == 503
        assert response.data["code"] == "parcel_photo_storage_unavailable"
        # The provider names buckets and credentials in its messages. None of
        # that reaches the phone.
        assert "AccessDenied" not in str(response.data)
        assert ParcelMedia.objects.count() == 0

    def test_a_retry_with_one_key_produces_one_row(self):
        """A dropped connection must not cost the sender a duplicate."""

        with patch("apps.parcels.views.put_object"):
            first = self.client.post(
                STAGE_URL,
                {
                    "photo": _upload("item.jpg", _image_bytes(), "image/jpeg"),
                    "idempotency_key": "device-abc-123",
                },
                format="multipart",
            )
            second = self.client.post(
                STAGE_URL,
                {
                    "photo": _upload("item.jpg", _image_bytes(), "image/jpeg"),
                    "idempotency_key": "device-abc-123",
                },
                format="multipart",
            )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.data["id"] == second.data["id"]
        assert ParcelMedia.objects.count() == 1

    def test_two_senders_may_use_the_same_key(self):
        other = _make_user(f"8fb-other-{uuid4().hex[:8]}@example.com")
        with patch("apps.parcels.views.put_object"):
            self.client.post(
                STAGE_URL,
                {
                    "photo": _upload("item.jpg", _image_bytes(), "image/jpeg"),
                    "idempotency_key": "same-key",
                },
                format="multipart",
            )
            _auth(other).post(
                STAGE_URL,
                {
                    "photo": _upload("item.jpg", _image_bytes(), "image/jpeg"),
                    "idempotency_key": "same-key",
                },
                format="multipart",
            )
        assert ParcelMedia.objects.count() == 2


# ---------------------------------------------------------------------------
# Creating with, and without, the photo
# ---------------------------------------------------------------------------


@patch("apps.parcels.views.redis_bus.publish_after_commit")
class RequiredItemPhotoTests(_PhotoTestBase):
    def test_a_request_without_a_photo_is_refused(self, _publish):
        response = self.create(item_photo_media_id=_ABSENT)

        assert response.status_code == 400
        assert "item_photo_media_id" in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_a_request_with_a_photo_is_accepted_and_owns_it(self, _publish):
        photo = self.stage_photo()
        response = self.create(item_photo_media_id=photo.pk)

        assert response.status_code == 201, response.data
        parcel = DeliveryRequest.objects.get()
        photo.refresh_from_db()
        assert photo.parcel_id == parcel.parcelrequest_ptr_id
        assert photo.is_staged is False
        assert response.data["item_photo_media_id"] == photo.pk
        assert [m["purpose"] for m in response.data["media"]] == ["item_photo"]

    def test_another_senders_photo_cannot_be_claimed(self, _publish):
        stranger = _make_user(f"8fb-stranger-{uuid4().hex[:8]}@example.com")
        stolen = self.stage_photo(stranger)

        response = self.create(item_photo_media_id=stolen.pk)

        assert response.status_code == 400
        assert "item_photo_media_id" in response.data
        assert DeliveryRequest.objects.count() == 0
        stolen.refresh_from_db()
        assert stolen.parcel_id is None

    def test_one_photo_cannot_be_reused_for_a_second_request(self, _publish):
        photo = self.stage_photo()
        first = self.create(item_photo_media_id=photo.pk)
        assert first.status_code == 201, first.data

        second = self.create(item_photo_media_id=photo.pk)

        assert second.status_code == 400
        assert "item_photo_media_id" in second.data
        assert DeliveryRequest.objects.count() == 1

    def test_an_unknown_photo_id_is_a_field_error_not_a_crash(self, _publish):
        response = self.create(item_photo_media_id=999_999)
        assert response.status_code == 400
        assert "item_photo_media_id" in response.data

    def test_an_attachment_cannot_masquerade_as_the_item_photo(self, _publish):
        """Purpose is part of the contract, not a label.

        Only a row staged *as* an item photo satisfies the requirement, so a
        client cannot post an unrelated attachment id and call it evidence.
        """

        attachment = ParcelMedia.objects.create(
            parcel=None,
            uploaded_by=self.sender,
            purpose=ParcelMedia.Purpose.ATTACHMENT,
            bucket="shiptrip-parcel-test",
            object_key=f"parcels/staged/{self.sender.pk}/{uuid4().hex}.jpg",
            content_type="image/jpeg",
            bytes=64,
        )

        response = self.create(item_photo_media_id=attachment.pk)

        assert response.status_code == 400
        assert "item_photo_media_id" in response.data

    def test_no_orphan_request_survives_a_failed_creation(self, _publish):
        """The ordering is the guarantee, not a cleanup routine.

        A rejected create leaves nothing: the photo is still staged and
        reusable, and no request row exists to be discovered, deposited on or
        matched against.
        """

        photo = self.stage_photo()
        response = self.create(item_photo_media_id=photo.pk, title="")

        assert response.status_code == 400
        assert ParcelRequest.objects.count() == 0
        photo.refresh_from_db()
        assert photo.parcel_id is None


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


@patch("apps.parcels.views.redis_bus.publish_after_commit")
class OptionalDimensionsTests(_PhotoTestBase):
    def test_all_three_empty_is_accepted(self, _publish):
        response = self.create()

        assert response.status_code == 201, response.data
        parcel = DeliveryRequest.objects.get()
        assert parcel.length_cm is None
        assert parcel.width_cm is None
        assert parcel.height_cm is None

    def test_explicit_nulls_are_accepted(self, _publish):
        response = self.create(length_cm=None, width_cm=None, height_cm=None)
        assert response.status_code == 201, response.data

    def test_all_three_supplied_is_accepted(self, _publish):
        response = self.create(
            length_cm="30.00", width_cm="20.00", height_cm="10.00"
        )

        assert response.status_code == 201, response.data
        parcel = DeliveryRequest.objects.get()
        assert str(parcel.length_cm) == "30.00"
        assert str(parcel.height_cm) == "10.00"

    def test_a_partial_set_is_refused_once_under_one_key(self, _publish):
        response = self.create(length_cm="30.00")

        assert response.status_code == 400
        assert "dimensions" in response.data
        assert "length_cm" not in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_weight_is_still_required(self, _publish):
        response = self.create(actual_weight_kg=_ABSENT)

        assert response.status_code == 400
        assert "actual_weight_kg" in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_weight_bounds_are_unchanged(self, _publish):
        assert self.create(actual_weight_kg="0.00").status_code == 400
        assert self.create(actual_weight_kg="100.01").status_code == 400
        assert self.create(actual_weight_kg="100.00").status_code == 201

    def test_the_model_refuses_a_partial_set_too(self, _publish):
        """The API is not the only writer, so the rule lives on the row.

        A management action or a data fix that set one side would otherwise
        produce a request the marketplace cannot price.
        """

        from django.core.exceptions import ValidationError

        response = self.create()
        parcel = DeliveryRequest.objects.get()
        assert response.status_code == 201

        parcel.width_cm = "20.00"
        try:
            parcel.save()
        except ValidationError as error:
            assert "dimensions" in error.message_dict
        else:  # pragma: no cover - the assertion is the point
            raise AssertionError("a partial dimension set was accepted")


# ---------------------------------------------------------------------------
# Reading the photo back
# ---------------------------------------------------------------------------


@patch("apps.parcels.views.redis_bus.publish_after_commit")
class ItemPhotoAccessTests(_PhotoTestBase):
    def _created(self, **overrides):
        response = self.create(**overrides)
        assert response.status_code == 201, response.data
        parcel = ParcelRequest.objects.get()
        media = ParcelMedia.objects.get(parcel=parcel)
        return parcel, media

    def _url(self, parcel, media):
        return reverse("parcels-media-url", args=[parcel.pk, media.pk])

    def test_the_sender_gets_a_short_lived_signed_url(self, _publish):
        parcel, media = self._created()

        with patch("apps.parcels.views.s3_client") as client:
            client.return_value.generate_presigned_url.return_value = (
                "https://storage.invalid/signed?X-Amz-Expires=300"
            )
            response = self.client.get(self._url(parcel, media))

        assert response.status_code == 200
        assert response.data["expires_in"] == 300
        assert response["Cache-Control"] == "no-store"
        params = client.return_value.generate_presigned_url.call_args.kwargs
        assert params["ExpiresIn"] == 300
        assert params["Params"]["Bucket"] == media.bucket

    def test_a_published_request_is_visible_to_another_authenticated_user(
        self, _publish
    ):
        parcel, media = self._created()
        ParcelRequest.objects.filter(pk=parcel.pk).update(
            status=ParcelRequest.Status.OPEN
        )
        traveler = _make_user(f"8fb-trav-{uuid4().hex[:8]}@example.com")

        with patch("apps.parcels.views.s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://x/y"
            response = _auth(traveler).get(self._url(parcel, media))

        assert response.status_code == 200

    def test_an_unpublished_request_keeps_its_photo_to_its_sender(self, _publish):
        parcel, media = self._created()
        ParcelRequest.objects.filter(pk=parcel.pk).update(
            status=ParcelRequest.Status.AWAITING_DEPOSIT
        )
        stranger = _make_user(f"8fb-nosy-{uuid4().hex[:8]}@example.com")

        response = _auth(stranger).get(self._url(parcel, media))

        assert response.status_code == 403
        assert response.data["code"] == "not_authorized"

    def test_a_targeted_request_is_private_to_its_two_parties(self, _publish):
        target = _make_user(f"8fb-target-{uuid4().hex[:8]}@example.com")
        parcel, media = self._created(target_traveler_id=target.pk)
        ParcelRequest.objects.filter(pk=parcel.pk).update(
            status=ParcelRequest.Status.OPEN
        )
        stranger = _make_user(f"8fb-else-{uuid4().hex[:8]}@example.com")

        with patch("apps.parcels.views.s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://x/y"
            allowed = _auth(target).get(self._url(parcel, media))
        refused = _auth(stranger).get(self._url(parcel, media))

        assert allowed.status_code == 200
        assert refused.status_code == 403

    def test_staff_may_read_for_support(self, _publish):
        parcel, media = self._created()
        staff = _make_user(f"8fb-staff-{uuid4().hex[:8]}@example.com")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])

        with patch("apps.parcels.views.s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://x/y"
            response = _auth(staff).get(self._url(parcel, media))

        assert response.status_code == 200

    def test_anonymous_callers_are_refused(self, _publish):
        parcel, media = self._created()
        assert APIClient().get(self._url(parcel, media)).status_code == 401

    def test_a_media_id_from_another_request_is_not_reachable(self, _publish):
        parcel, media = self._created()
        assert (
            self.client.get(
                reverse("parcels-media-url", args=[parcel.pk, media.pk + 5000])
            ).status_code
            == 404
        )

    def test_the_detail_payload_never_carries_bucket_or_key(self, _publish):
        parcel, media = self._created()

        response = self.client.get(reverse("parcels-detail", args=[parcel.pk]))

        assert response.status_code == 200
        body = str(response.data)
        assert media.object_key not in body
        assert media.bucket not in body
        assert response.data["item_photo_media_id"] == media.pk

    def test_a_presign_failure_is_a_503_without_provider_detail(self, _publish):
        parcel, media = self._created()

        with patch("apps.parcels.views.s3_client") as client:
            client.return_value.generate_presigned_url.side_effect = RuntimeError(
                "AccessDenied on shiptrip-kyc"
            )
            response = self.client.get(self._url(parcel, media))

        assert response.status_code == 503
        assert response.data["code"] == "parcel_photo_storage_unavailable"
        assert "AccessDenied" not in str(response.data)


# ---------------------------------------------------------------------------
# Reclaiming what was never posted
# ---------------------------------------------------------------------------


class StagedMediaPurgeTests(_PhotoTestBase):
    def test_only_old_unclaimed_rows_are_reclaimed(self):
        from django.core.management import call_command

        fresh = self.stage_photo()
        stale = self.stage_photo()
        ParcelMedia.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        with patch("apps.parcels.management.commands.purge_staged_parcel_media"
                   ".s3_client") as client:
            call_command("purge_staged_parcel_media", "--older-than-hours", "24")

        assert ParcelMedia.objects.filter(pk=fresh.pk).exists()
        assert not ParcelMedia.objects.filter(pk=stale.pk).exists()
        client.return_value.delete_object.assert_called_once()

    def test_a_claimed_photo_is_never_reclaimed(self):
        from django.core.management import call_command

        with patch("apps.parcels.views.redis_bus.publish_after_commit"):
            response = self.create()
        assert response.status_code == 201, response.data
        media = ParcelMedia.objects.get()
        ParcelMedia.objects.filter(pk=media.pk).update(
            created_at=timezone.now() - timedelta(days=365)
        )

        with patch("apps.parcels.management.commands.purge_staged_parcel_media"
                   ".s3_client"):
            call_command("purge_staged_parcel_media", "--older-than-hours", "1")

        assert ParcelMedia.objects.filter(pk=media.pk).exists()
