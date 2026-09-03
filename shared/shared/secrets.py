"""Encryption of credentials at rest with Fernet, keyed from CREDENTIALS_KEY."""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet

from shared.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().credentials_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(value: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(value).encode())


def decrypt_json(token: bytes) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(_fernet().decrypt(token))
    return result
