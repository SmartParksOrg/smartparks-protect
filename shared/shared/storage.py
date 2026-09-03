"""MinIO client for raw payloads above the inline limit, uploads and exports (decision D32).

The MinIO SDK is synchronous; calls run in a thread so they do not block the event loop.
"""

import asyncio
import hashlib
import io
from functools import lru_cache

from minio import Minio

from shared.config import get_settings


@lru_cache
def get_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def put_object(
    bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
) -> None:
    client = get_client()

    def _put() -> None:
        client.put_object(
            bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
        )

    await asyncio.to_thread(_put)


async def get_object(bucket: str, key: str) -> bytes:
    client = get_client()

    def _get() -> bytes:
        response = client.get_object(bucket, key)
        try:
            return bytes(response.read())
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(_get)
