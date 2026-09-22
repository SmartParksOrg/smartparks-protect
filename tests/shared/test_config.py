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


def test_the_compose_default_offers_the_same_analysis_modules_as_the_settings() -> None:
    """Compose cannot read the settings, so the module list is written twice. It went stale
    once: on 2026-09-22 the cardiac module was invisible on the dev server because compose's
    default still said `movement,grazing` from analytics phase 1, and a server whose `.env`
    does not pin the value takes that default. This test is what keeps the two equal."""
    import re
    from pathlib import Path

    from shared.config import Settings

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    found = re.search(r"ANALYSIS_MODULES: \$\{ANALYSIS_MODULES:-([^}]*)\}", compose)
    assert found, "docker-compose.yml no longer sets ANALYSIS_MODULES"
    assert found.group(1) == Settings.model_fields["analysis_modules"].default
