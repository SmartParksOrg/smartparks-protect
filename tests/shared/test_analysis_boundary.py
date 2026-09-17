"""The analysis package stays outside the core (docs/ANALYTICS_PHASE1_PLAN.md, section 5): no
core module imports it, the registry lists what is enabled, and the provider boundary is empty."""

import importlib
import sys

from shared.config import Settings


def _fresh_import(name: str) -> None:
    for key in [
        k for k in sys.modules if k == "shared.analysis" or k.startswith("shared.analysis.")
    ]:
        del sys.modules[key]
    importlib.import_module(name)


def test_core_modules_do_not_import_the_analysis_package():
    for name in (
        "shared.ingest",
        "shared.rules.evaluator",
        "shared.curation.apply",
        "shared.exports.runner",
        "shared.connectivity.network_location",
        "shared.device_drivers.registry",
    ):
        _fresh_import(name)
        assert not any(k.startswith("shared.analysis") for k in sys.modules), name


def test_enabled_modules_follow_the_setting(monkeypatch):
    from shared.analysis import MODULES, enabled_modules

    monkeypatch.setitem(MODULES, "movement", object())  # type: ignore[misc]
    monkeypatch.setitem(MODULES, "grazing", object())  # type: ignore[misc]
    base = {
        "database_url": "postgresql+asyncpg://x",
        "redis_url": "redis://x",
        "jwt_secret": "s" * 32,
        "credentials_key": "c" * 16,
    }
    assert enabled_modules(Settings(**base)) == ["movement", "grazing"]
    assert enabled_modules(Settings(**base, analysis_modules="grazing")) == ["grazing"]
    assert enabled_modules(Settings(**base, analysis_modules="grazing, unknown")) == ["grazing"]
    assert enabled_modules(Settings(**base, analysis_modules="")) == []


def test_a_provider_registers_only_when_its_settings_are_there():
    """The boundary stays empty unless a server configured a provider (decision D245): a
    module asks for a layer and gets nothing, and the analysis carries on without it."""
    import shared.analysis.environment as env
    import shared.analysis.providers as providers

    assert env.PROVIDERS == []  # no Copernicus settings in the test environment
    assert env.provider_for("ndvi") is None
    providers.register_providers()  # importing the package again registers nothing either
    assert env.PROVIDERS == []
