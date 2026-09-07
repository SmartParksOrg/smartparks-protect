"""Profile pictures of entities and devices (decision D110): one small square per object, made
on the server from whatever a phone or a camera produced, so every page loads a few kilobytes
and orientation and size are always right. Only the square is kept."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

PICTURE_SIZE = 512
PICTURE_CONTENT_TYPE = "image/webp"
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PictureError(ValueError):
    """The upload is not a picture we accept; the message says why."""


def process_picture(data: bytes) -> bytes:
    """A JPEG, PNG or WebP of any size to a centre-cropped WebP square of PICTURE_SIZE."""
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
    square = ImageOps.fit(image, (PICTURE_SIZE, PICTURE_SIZE), method=Image.Resampling.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()
