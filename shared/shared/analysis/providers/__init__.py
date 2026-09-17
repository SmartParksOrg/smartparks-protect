"""The environmental providers (decision D245). Importing this package registers the ones whose
settings are there; the analysis worker and the API import it with the modules."""

from __future__ import annotations

from shared.analysis.environment import register
from shared.analysis.providers.copernicus import CopernicusProvider
from shared.config import get_settings


def register_providers() -> None:
    settings = get_settings()
    if settings.landscape_configured:
        register(
            CopernicusProvider(
                client_id=str(settings.copernicus_client_id),
                client_secret=str(settings.copernicus_client_secret),
            )
        )


register_providers()

__all__ = ["CopernicusProvider", "register_providers"]
