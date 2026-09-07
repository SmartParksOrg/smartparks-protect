"""Profile pictures of entities and devices (decision D110): read the upload within its bound,
make the square, keep it in the pictures bucket under a key per object, and serve it with the
bearer token and a cache that refreshes when the picture changes."""

import uuid
from datetime import datetime

from fastapi import HTTPException, Response, UploadFile, status

from shared.config import get_settings
from shared.pictures import PICTURE_CONTENT_TYPE, PictureError, process_picture
from shared.storage import get_object, put_object, remove_object
from shared.timeutil import utc_now


def picture_key(kind: str, object_id: uuid.UUID) -> str:
    return f"{kind}/{object_id}.webp"


async def store_picture(kind: str, object_id: uuid.UUID, file: UploadFile) -> tuple[str, datetime]:
    """The upload as a stored square; returns the object key and the time to keep on the row."""
    settings = get_settings()
    data = await file.read(settings.picture_max_bytes + 1)
    if len(data) > settings.picture_max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The picture exceeds {settings.picture_max_bytes} bytes",
        )
    try:
        square = process_picture(data)
    except PictureError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    key = picture_key(kind, object_id)
    await put_object(settings.minio_bucket_pictures, key, square, PICTURE_CONTENT_TYPE)
    return key, utc_now()


async def drop_picture(key: str | None) -> None:
    if key:
        await remove_object(get_settings().minio_bucket_pictures, key)


async def picture_response(key: str | None, updated_at: datetime | None) -> Response:
    """The stored square, cacheable per version: the frontend puts `picture_updated_at` in the
    URL, so a changed picture is a new URL and an unchanged one stays cached for a day."""
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture")
    data = await get_object(get_settings().minio_bucket_pictures, key)
    return Response(
        content=data,
        media_type=PICTURE_CONTENT_TYPE,
        headers={
            "Cache-Control": "private, max-age=86400",
            "ETag": f'"{updated_at.isoformat() if updated_at else key}"',
        },
    )
