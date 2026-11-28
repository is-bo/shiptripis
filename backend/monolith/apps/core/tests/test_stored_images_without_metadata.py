"""Every stored parcel photo, ticket proof and dispute photo is written again from its pixels.

A photo keeps what the phone wrote into it: the GPS position of the place it
was taken (often the sender's home), the camera, a comment, XMP. Exact
locations stay hidden until a deal is funded, so the stored file must carry
none of it. Each upload path is driven through its own HTTP endpoint, and the
bytes handed to the object store are read back.
"""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import ExifTags, Image

from apps.core.storage import MAX_STORED_IMAGE_SIDE
from apps.core.tests.l10_world import DRIVE, FLIGHT, AcceptanceWorld, api
from apps.discovery.tests.support import STATIC_STORES
from apps.disputes.models import Dispute, DisputeEvidence
from apps.disputes.services import open_dispute
from apps.parcels.models import ParcelMedia
from apps.trips.models import Journey, JourneyLegProof

RED = (220, 20, 20)
BLUE = (20, 20, 220)
GPS_LATITUDE = (36.0, 45.0, 12.0)
SECRETS = (b"SecretCam PV", b"pv secret comment", b"pv-secret-xmp")


def halves(width: int, height: int) -> Image.Image:
    """Left half red, right half blue, as stored."""

    image = Image.new("RGB", (width, height), BLUE)
    image.paste(RED, (0, 0, width // 2, height))
    return image


def photo_with_gps(*, orientation: int | None = None, size=(800, 600)) -> bytes:
    """A JPEG as a phone camera writes one: GPS, camera, XMP and a comment."""

    exif = Image.Exif()
    exif[ExifTags.Base.Model] = "SecretCam PV"
    if orientation is not None:
        exif[ExifTags.Base.Orientation] = orientation
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = GPS_LATITUDE
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (3.0, 3.0, 30.0)
    out = BytesIO()
    halves(*size).save(
        out,
        format="JPEG",
        exif=exif.tobytes(),
        comment=b"pv secret comment",
        xmp=b"<x:xmpmeta>pv-secret-xmp</x:xmpmeta>",
    )
    return out.getvalue()


def transparent_png() -> bytes:
    out = BytesIO()
    Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(out, format="PNG")
    return out.getvalue()


def animated_png() -> bytes:
    out = BytesIO()
    frames = [Image.new("RGB", (40, 40), RED), Image.new("RGB", (40, 40), BLUE)]
    frames[0].save(out, format="PNG", save_all=True, append_images=frames[1:])
    return out.getvalue()


def bomb_png() -> bytes:
    """Small on disk, 48 million pixels once decoded."""

    out = BytesIO()
    Image.new("1", (8000, 6000)).save(out, format="PNG")
    return out.getvalue()


def corrupt_jpeg() -> bytes:
    return photo_with_gps()[:400]


def metadata_left(stored: bytes) -> list[str]:
    """What survived of the phone's metadata, by name."""

    found = [secret.decode() for secret in SECRETS if secret in stored]
    with Image.open(BytesIO(stored)) as image:
        if image.getexif():
            found.append("exif")
        found += sorted(set(image.info) & {"exif", "xmp", "icc_profile", "comment", "photoshop"})
    return found


@override_settings(STORAGES=STATIC_STORES)
class StoredImagesWithoutMetadataTests(AcceptanceWorld, TestCase):
    """The same table of cases for each of the four endpoints that store an image."""

    def setUp(self):
        cache.clear()
        self.build_acceptance_world()
        self.depart = self.now + timedelta(hours=4)
        self._parcel = self._dispute = None

    # -- the upload paths: each returns (status, code, stored bytes, recorded type)

    def _post(self, client, url, data, put_target):
        with patch(put_target) as put:
            response = client.post(url, data, format="multipart")
        stored = put.call_args.kwargs["body"] if put.called else None
        if stored is not None:
            assert put.call_args.kwargs["content_type"] == "image/jpeg"
            assert put.call_args.kwargs["key"].endswith(".jpg")
        return response, stored

    def stage_parcel_photo(self, body, content_type):
        response, stored = self._post(
            api(self.sender),
            reverse("parcels-item-photo-stage"),
            {"photo": SimpleUploadedFile("item", body, content_type=content_type)},
            "apps.parcels.views.put_object",
        )
        recorded = None
        if response.status_code == 201:
            row = ParcelMedia.objects.get(pk=response.data["id"])
            recorded = (row.content_type, row.bytes)
        return response, stored, recorded

    def parcel(self):
        if self._parcel is None:
            self._parcel = self.post_parcel(
                self.algiers,
                self.setif,
                ready_from=self.depart - timedelta(hours=2),
                ready_until=self.depart + timedelta(minutes=30),
                deliver_by=self.depart + timedelta(hours=12),
            )
        return self._parcel

    def attach_parcel_photo(self, body, content_type):
        response, stored = self._post(
            api(self.sender),
            reverse("parcels-media-upload", args=(self.parcel().pk,)),
            {"photo": SimpleUploadedFile("extra", body, content_type=content_type)},
            "apps.parcels.views.put_object",
        )
        recorded = None
        if response.status_code == 201:
            row = ParcelMedia.objects.get(pk=response.data["id"])
            recorded = (row.content_type, row.bytes)
        return response, stored, recorded

    def upload_ticket_proof(self, body, content_type):
        journey = self.make_journey(
            self.traveler,
            [(FLIGHT, self.cdg, self.alg)],
            status=Journey.Status.DRAFT,
            approve_tickets=False,
        )
        leg = journey.legs.get()
        response, stored = self._post(
            api(self.traveler),
            reverse("journey-leg-proof-create", args=(journey.pk, leg.pk)),
            {"photo": SimpleUploadedFile("ticket", body, content_type=content_type), "kind": "ticket"},
            "apps.trips.views.put_object",
        )
        recorded = None
        if response.status_code == 201:
            row = JourneyLegProof.objects.get(pk=response.data["id"])
            recorded = (row.content_type, row.bytes)
        return response, stored, recorded

    def dispute(self):
        if self._dispute is None:
            journey = self.post_trip(
                [self.leg_payload(DRIVE, self.algiers, self.setif, self.depart, hours=3)]
            )
            self.publish(journey)
            leg = journey.legs.get()
            parcel = self.parcel()
            self.pay_deposit(parcel)
            deal = self.accept(self.propose(parcel, journey, leg, leg, 3_000))
            self.pay_balance(deal)
            self.set_recipient(deal)
            self.pick_up(deal)
            self._dispute = open_dispute(
                deal_id=deal.pk,
                actor_id=self.sender.pk,
                category=Dispute.Category.NOT_DELIVERED,
                reason_text="The traveler has stopped answering.",
            )
        return self._dispute

    def add_dispute_photo(self, body, content_type):
        response, stored = self._post(
            api(self.sender),
            reverse("disputes-evidence", args=(self.dispute().pk,)),
            {"kind": "photo", "file": SimpleUploadedFile("proof", body, content_type=content_type)},
            "apps.disputes.services.put_object",
        )
        recorded = None
        if response.status_code == 201:
            row = DisputeEvidence.objects.get(pk=response.data["id"])
            recorded = (row.content_type, row.size_bytes)
        return response, stored, recorded

    PATHS = {
        "parcel item photo": ("stage_parcel_photo", "parcel_photo_media_type_unsupported"),
        "parcel attachment": ("attach_parcel_photo", "parcel_photo_media_type_unsupported"),
        "ticket proof": ("upload_ticket_proof", "proof_media_type_unsupported"),
        "dispute photo": ("add_dispute_photo", "dispute_evidence_content_mismatch"),
    }

    def each_path(self):
        for name, (method, refusal) in self.PATHS.items():
            with self.subTest(path=name):
                yield name, getattr(self, method), refusal

    # -- the cases -------------------------------------------------------------

    def test_a_photo_with_a_gps_position_is_stored_without_it(self):
        source = photo_with_gps()
        with Image.open(BytesIO(source)) as original:
            # The input really carries what must not survive.
            assert original.getexif().get_ifd(ExifTags.IFD.GPSInfo)[ExifTags.GPS.GPSLatitude] == GPS_LATITUDE
        assert {"SecretCam PV", "pv secret comment", "pv-secret-xmp"} <= set(metadata_left(source))
        for name, upload, _ in self.each_path():
            response, stored, recorded = upload(source, "image/jpeg")
            assert response.status_code == 201, (name, response.data)
            assert metadata_left(stored) == [], name
            with Image.open(BytesIO(stored)) as image:
                assert image.format == "JPEG"
                assert image.size == (800, 600), "the shape is kept"
            assert recorded == ("image/jpeg", len(stored)), name

    def test_all_eight_orientations_come_out_upright(self):
        # Each orientation is stored so that, turned as its tag says, red is
        # on the left: the stored output must show red on the left.
        transposes = {
            1: None,
            2: Image.Transpose.FLIP_LEFT_RIGHT,
            3: Image.Transpose.ROTATE_180,
            4: Image.Transpose.FLIP_TOP_BOTTOM,
            5: Image.Transpose.TRANSPOSE,
            6: Image.Transpose.ROTATE_90,
            7: Image.Transpose.TRANSVERSE,
            8: Image.Transpose.ROTATE_270,
        }
        for name, upload, _ in self.each_path():
            for orientation, stored_as in transposes.items():
                upright = halves(400, 200)
                raw = upright if stored_as is None else upright.transpose(stored_as)
                exif = Image.Exif()
                exif[ExifTags.Base.Orientation] = orientation
                out = BytesIO()
                raw.save(out, format="JPEG", exif=exif.tobytes())
                response, stored, _ = upload(out.getvalue(), "image/jpeg")
                assert response.status_code == 201, (name, orientation, response.data)
                with Image.open(BytesIO(stored)) as image:
                    assert image.size == (400, 200), (name, orientation, image.size)
                    left, right = image.getpixel((40, 100)), image.getpixel((360, 100))
                assert left[0] > 180 and left[2] < 80, (name, orientation, left)
                assert right[2] > 180 and right[0] < 80, (name, orientation, right)

    def test_a_transparent_png_is_flattened_onto_white(self):
        for name, upload, _ in self.each_path():
            response, stored, recorded = upload(transparent_png(), "image/png")
            assert response.status_code == 201, (name, response.data)
            with Image.open(BytesIO(stored)) as image:
                assert image.format == "JPEG" and image.mode == "RGB"
                assert min(image.getpixel((150, 100))) > 240
            assert recorded == ("image/jpeg", len(stored))

    def test_the_longer_side_is_brought_down_to_the_limit(self):
        for name, upload, _ in self.each_path():
            response, stored, _ = upload(photo_with_gps(size=(4000, 1000)), "image/jpeg")
            assert response.status_code == 201, (name, response.data)
            with Image.open(BytesIO(stored)) as image:
                assert image.size == (MAX_STORED_IMAGE_SIDE, MAX_STORED_IMAGE_SIDE // 4)

    def test_a_corrupt_an_animated_and_a_bomb_file_are_refused(self):
        for name, upload, refusal in self.each_path():
            for label, body in (
                ("corrupt", corrupt_jpeg()),
                ("animated", animated_png()),
                ("bomb", bomb_png()),
            ):
                content_type = "image/jpeg" if label == "corrupt" else "image/png"
                response, stored, recorded = upload(body, content_type)
                # Each path keeps the status and code it already answers with.
                assert 400 <= response.status_code < 500, (name, label, response.data)
                assert response.data["code"] == refusal, (name, label, response.data)
                assert stored is None and recorded is None, (name, label)

