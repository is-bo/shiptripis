"""P3A: `square_jpeg_without_metadata`, the server's re-encoding of an image.

Nothing a phone wrote into a file may survive: the output is built from pixels
alone. It is upright, a centred square of the asked size, and a JPEG.
"""

from __future__ import annotations

from io import BytesIO

from django.test import SimpleTestCase
from PIL import ExifTags, Image

from apps.core.storage import (
    MAX_IMAGE_PIXELS,
    ImageRejected,
    image_bytes_match_extension,
    square_jpeg_without_metadata,
)

RED = (220, 20, 20)
BLUE = (20, 20, 220)


def halves(width: int, height: int) -> Image.Image:
    """Left half red, right half blue, as stored."""

    image = Image.new("RGB", (width, height), BLUE)
    image.paste(RED, (0, 0, width // 2, height))
    return image


def jpeg_with_gps(*, orientation: int | None = None) -> bytes:
    """A JPEG carrying a camera model, GPS coordinates and, optionally, an
    orientation, the way a phone camera writes one."""

    exif = Image.Exif()
    exif[ExifTags.Base.Model] = "SecretCam P3A"
    exif[ExifTags.Base.DateTimeOriginal] = "2026:11:24 09:15:00"
    if orientation is not None:
        exif[ExifTags.Base.Orientation] = orientation
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (36.0, 45.0, 12.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (3.0, 3.0, 30.0)
    out = BytesIO()
    halves(800, 600).save(out, format="JPEG", exif=exif.tobytes(), comment=b"p3a secret comment")
    return out.getvalue()


def app_markers(jpeg: bytes) -> list[int]:
    """The APPn markers (0xE0 to 0xEF) and comments (0xFE) before the image data."""

    found = []
    position = 2  # after SOI
    while position + 4 <= len(jpeg):
        marker = jpeg[position + 1]
        if marker == 0xDA:  # start of scan: metadata comes before it
            break
        length = int.from_bytes(jpeg[position + 2 : position + 4], "big")
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            found.append(marker)
        position += 2 + length
    return found


class ReencodeTests(SimpleTestCase):
    def test_gps_and_every_other_metadata_are_gone(self):
        source = jpeg_with_gps()
        with Image.open(BytesIO(source)) as original:
            # The input really carries what must not survive.
            assert original.getexif().get_ifd(ExifTags.IFD.GPSInfo)
            assert original.getexif()[ExifTags.Base.Model] == "SecretCam P3A"

        output = square_jpeg_without_metadata(source, size=512)

        with Image.open(BytesIO(output)) as result:
            assert result.format == "JPEG"
            assert result.size == (512, 512)
            assert len(result.getexif()) == 0
            assert not set(result.info) & {"exif", "icc_profile", "xmp", "comment", "photoshop"}
        assert b"Exif\x00\x00" not in output
        assert b"SecretCam" not in output and b"p3a secret comment" not in output
        # Only the JFIF header: no APP1 (EXIF, XMP), APP2 (ICC), APP13 or comment.
        assert app_markers(output) == [0xE0]

    def test_the_output_is_upright_and_the_centred_square(self):
        # Orientation 6: the stored picture is shown turned 90 degrees
        # clockwise, so the stored left half (red) is the top when upright.
        output = square_jpeg_without_metadata(jpeg_with_gps(orientation=6), size=512)
        with Image.open(BytesIO(output)) as result:
            top = result.getpixel((256, 40))
            bottom = result.getpixel((256, 470))
        assert top[0] > 180 and top[2] < 80, top
        assert bottom[2] > 180 and bottom[0] < 80, bottom

    def test_a_wide_picture_keeps_its_middle(self):
        image = Image.new("RGB", (1500, 500), (0, 0, 0))
        image.paste((0, 200, 0), (500, 0, 1000, 500))  # the middle third is green
        out = BytesIO()
        image.save(out, format="PNG")
        with Image.open(BytesIO(square_jpeg_without_metadata(out.getvalue(), size=512))) as result:
            assert result.size == (512, 512)
            for x in (10, 256, 500):
                pixel = result.getpixel((x, 256))
                assert pixel[1] > 150 and pixel[0] < 60, (x, pixel)

    def test_transparency_is_flattened_onto_white(self):
        image = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        out = BytesIO()
        image.save(out, format="WEBP", lossless=True)
        with Image.open(BytesIO(square_jpeg_without_metadata(out.getvalue(), size=512))) as result:
            assert result.mode == "RGB"
            assert min(result.getpixel((256, 256))) > 240

    def test_a_decompression_bomb_is_refused_before_it_is_expanded(self):
        width, height = 8000, 6000
        assert width * height > MAX_IMAGE_PIXELS
        out = BytesIO()
        Image.new("1", (width, height)).save(out, format="PNG")
        bomb = out.getvalue()
        assert len(bomb) < 200_000  # small on disk, enormous in memory
        assert image_bytes_match_extension(bomb, "png") is False
        with self.assertRaises(ImageRejected):
            square_jpeg_without_metadata(bomb, size=512)

    def test_anything_that_is_not_a_supported_image_is_refused(self):
        gif = BytesIO()
        Image.new("RGB", (10, 10)).save(gif, format="GIF")
        truncated = jpeg_with_gps()[:400]
        for body in (b"", b"not an image", truncated, gif.getvalue()):
            with self.subTest(body=body[:12]), self.assertRaises(ImageRejected):
                square_jpeg_without_metadata(body, size=512)
