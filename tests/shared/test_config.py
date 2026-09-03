import pytest
from pydantic import ValidationError

from shared.config import Settings


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example, http://b.example,")
    monkeypatch.setenv("MINIO_SECURE", "true")
    settings = Settings(_env_file=None)
    assert settings.cors_origin_list == ["http://a.example", "http://b.example"]
    assert settings.minio_url == "https://localhost:9000"


def test_missing_required_value_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_short_jwt_secret_raises(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
