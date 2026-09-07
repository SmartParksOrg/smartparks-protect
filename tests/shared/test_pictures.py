"""Profile pictures (decision D110): any JPEG, PNG or WebP becomes a small WebP square, phones'
rotation metadata is applied, and anything else is refused with a reason."""

import io

import pytest
from PIL import Image

from shared.pictures import PICTURE_SIZE, PictureError, process_picture


def _png(width: int, height: int, color: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def test_landscape_becomes_a_square_webp():
    result = process_picture(_png(1200, 800))
    image = Image.open(io.BytesIO(result))
    assert image.format == "WEBP"
    assert image.size == (PICTURE_SIZE, PICTURE_SIZE)
    assert len(result) < 50_000


def test_small_picture_is_scaled_up_not_padded():
    image = Image.open(io.BytesIO(process_picture(_png(100, 300))))
    assert image.size == (PICTURE_SIZE, PICTURE_SIZE)


def test_jpeg_with_rotation_metadata_is_turned():
    out = io.BytesIO()
    source = Image.new("RGB", (400, 200), "blue")
    # a 200 px wide strip on the left is red: after a 90° rotation it must be at the top
    source.paste("red", (0, 0, 200, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90° clockwise
    source.save(out, format="JPEG", exif=exif.tobytes())
    image = Image.open(io.BytesIO(process_picture(out.getvalue()))).convert("RGB")
    top = image.getpixel((PICTURE_SIZE // 2, 10))
    bottom = image.getpixel((PICTURE_SIZE // 2, PICTURE_SIZE - 10))
    assert top[0] > 200 and top[2] < 80, top  # red on top
    assert bottom[2] > 200 and bottom[0] < 80, bottom  # blue below


def test_not_a_picture_is_refused():
    with pytest.raises(PictureError, match="not a JPEG, PNG or WebP"):
        process_picture(b"just some text, not an image")


def test_other_formats_are_refused():
    out = io.BytesIO()
    Image.new("RGB", (50, 50)).save(out, format="BMP")
    with pytest.raises(PictureError, match="BMP"):
        process_picture(out.getvalue())
