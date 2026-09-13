"""Profile pictures of entities and devices (decision D110): one small picture per object, made
on the server from whatever a phone or a camera produced, so every page loads a few kilobytes
and orientation and size are always right. Only the processed picture is kept: a square for a
device (its icon), a 4:3 landscape for an entity (a card on its page, decision D194)."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

PICTURE_SIZE = 512
#: An entity's picture (decision D194): a landscape card on its page, 4:3, wide enough for a
#: desktop card and small enough for a phone.
PICTURE_LANDSCAPE = (1200, 900)
PICTURE_CONTENT_TYPE = "image/webp"
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PictureError(ValueError):
    """The upload is not a picture we accept; the message says why."""


def process_picture(data: bytes, shape: tuple[int, int] = (PICTURE_SIZE, PICTURE_SIZE)) -> bytes:
    """A JPEG, PNG or WebP of any size to a centre-cropped WebP of `shape` (a square of
    PICTURE_SIZE by default, PICTURE_LANDSCAPE for an entity)."""
    try:
        image: Image.Image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PictureError("The file is not a JPEG, PNG or WebP picture") from exc
    if image.format not in ACCEPTED_FORMATS:
        raise PictureError(f"{image.format or 'This'} is not a JPEG, PNG or WebP picture")
    image = ImageOps.exif_transpose(image) or image  # phones store the rotation as metadata
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    square = ImageOps.fit(image, shape, method=Image.Resampling.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()
