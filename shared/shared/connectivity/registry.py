"""Explicit adapter registry (decision D10): in-repo modules, no dynamic loading."""

from typing import Any

from shared.connectivity.adapters.akenza import AkenzaAdapter
from shared.connectivity.adapters.chirpstack import ChirpStackAdapter
from shared.connectivity.adapters.generic_http import GenericHttpAdapter
from shared.connectivity.adapters.generic_mqtt import GenericMqttAdapter
from shared.connectivity.adapters.kpn_thingpark import KpnThingParkAdapter
from shared.connectivity.adapters.loriot import LoriotAdapter
from shared.connectivity.adapters.netmore import NetmoreAdapter
from shared.connectivity.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    adapter.key: adapter
    for adapter in (
        GenericHttpAdapter(),
        GenericMqttAdapter(),
        ChirpStackAdapter(),
        KpnThingParkAdapter(),
        LoriotAdapter(),
        NetmoreAdapter(),
        AkenzaAdapter(),
    )
}


def describe_adapter(adapter: Adapter) -> dict[str, Any]:
    """Registry metadata for the API and the frontend, so no screen names a provider."""
    return {
        "key": adapter.key,
        "label": adapter.label,
        "push": bool(getattr(adapter, "push", False)),
        "can_send_commands": hasattr(adapter, "command_connector"),
        "acquisition_channel": str(getattr(adapter, "acquisition_channel", None) or "other"),
        "default_capabilities": adapter.default_capabilities.model_dump(),
        "default_link_templates": dict(adapter.default_link_templates),
        "config_schema": dict(adapter.config_schema),
        "config_example": dict(getattr(adapter, "config_example", {}) or {}),
        "credentials_schema": dict(getattr(adapter, "credentials_schema", {}) or {}),
        "setup_hint": str(getattr(adapter, "setup_hint", "") or ""),
    }


def get_adapter(key: str) -> Adapter:
    try:
        return ADAPTERS[key]
    except KeyError:
        raise KeyError(f"unknown adapter {key!r}; known: {sorted(ADAPTERS)}") from None
