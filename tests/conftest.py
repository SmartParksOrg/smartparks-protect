"""Shared test setup.

Settings are read from the environment. `.env.example` values work against the local docker
compose stack; CI sets the same variables for its service containers. Tests that need the real
infrastructure are marked `integration`.
"""

import os

DEFAULTS = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": "postgresql+asyncpg://protect:protect-dev-password@localhost:5432/smartparks_protect",
    "REDIS_URL": "redis://:protect-dev-redis@localhost:6379/0",
    "MINIO_ENDPOINT": "localhost:9000",
    "MINIO_ROOT_USER": "protect",
    "MINIO_ROOT_PASSWORD": "protect-dev-minio",
    "JWT_SECRET": "test-secret-that-is-long-enough",
    "LOG_FORMAT": "text",
}

for key, value in DEFAULTS.items():
    os.environ.setdefault(key, value)
