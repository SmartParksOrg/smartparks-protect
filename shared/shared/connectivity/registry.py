"""Explicit adapter registry (decision D10): in-repo modules, no dynamic loading."""

from typing import Any

from shared.connectivity.adapters.actility_thingpark import ActilityThingParkAdapter
from shared.connectivity.adapters.addaxai_connect import AddaxAiConnectAdapter
from shared.connectivity.adapters.akenza import AkenzaAdapter
from shared.connectivity.adapters.chirpstack import ChirpStackAdapter
from shared.connectivity.adapters.cloudloop import CloudloopAdapter
from shared.connectivity.adapters.cra_iot import CraIotAdapter
from shared.connectivity.adapters.generic_http import GenericHttpAdapter
from shared.connectivity.adapters.generic_mqtt import GenericMqttAdapter
from shared.connectivity.adapters.kpn_thingpark import KpnThingParkAdapter
from shared.connectivity.adapters.log_file import LogFileAdapter
from shared.connectivity.adapters.loriot import LoriotAdapter
from shared.connectivity.adapters.netmore import NetmoreAdapter
from shared.connectivity.adapters.traccar import TraccarAdapter
from shared.connectivity.adapters.tts import TtsAdapter
from shared.connectivity.adapters.webble import WebBleAdapter
from shared.connectivity.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    adapter.key: adapter
    for adapter in (
        GenericHttpAdapter(),
        GenericMqttAdapter(),
        ChirpStackAdapter(),
        KpnThingParkAdapter(),
        CraIotAdapter(),
        LoriotAdapter(),
        TtsAdapter(),
        ActilityThingParkAdapter(),
        NetmoreAdapter(),
        AkenzaAdapter(),
        TraccarAdapter(),
        AddaxAiConnectAdapter(),
        CloudloopAdapter(),
        WebBleAdapter(),
        LogFileAdapter(),
    )
}


def channels_of(adapter: Adapter) -> list[dict[str, Any]]:
    """The ways a source of this adapter talks to its platform, each with what it needs in
    the config and credentials and what it enables. Adapters declare `channels`; the rest is
    derived from their flags so every source has at least its receiving channel."""
    declared = getattr(adapter, "channels", None)
    if declared:
        return [dict(c) for c in declared]
    channels: list[dict[str, Any]] = []
    if getattr(adapter, "push", False):
        channels.append(
            {
                "key": "http",
                "label": "HTTP push",
                "direction": "in",
                "purpose": "The platform posts events to the webhook URL with the bearer token",
                "config_keys": [],
                "credential_keys": [],
            }
        )
    if getattr(adapter, "polling", False):
        channels.append(
            {
                "key": "poll",
                "label": "API polling",
                "direction": "in",
                "purpose": "The ingest service asks the platform for new records on a schedule",
                "config_keys": [],
                "credential_keys": list(getattr(adapter, "credentials_schema", {}) or {}),
            }
        )
    elif not getattr(adapter, "push", False) and not getattr(adapter, "builtin", False):
        channels.append(
            {
                "key": "stream",
                "label": "Live connection",
                "direction": "in",
                "purpose": "The ingest service keeps a connection to the platform open",
                "config_keys": [],
                "credential_keys": [],
            }
        )
    if hasattr(adapter, "command_connector") or hasattr(adapter, "management_connector"):
        channels.append(
            {
                "key": "api",
                "label": "Platform API",
                "direction": "out",
                "purpose": "Downlinks and the device and gateway sync",
                "config_keys": [],
                "credential_keys": list(getattr(adapter, "credentials_schema", {}) or {}),
            }
        )
    return channels


def describe_adapter(adapter: Adapter) -> dict[str, Any]:
    """Registry metadata for the API and the frontend, so no screen names a provider."""
    return {
        "channels": channels_of(adapter),
        "key": adapter.key,
        "label": adapter.label,
        "push": bool(getattr(adapter, "push", False)),
        "can_send_commands": hasattr(adapter, "command_connector"),
        "can_manage": hasattr(adapter, "management_connector"),
        "polling": bool(getattr(adapter, "polling", False)),
        "builtin": bool(getattr(adapter, "builtin", False)),
        "requires_client": bool(getattr(adapter, "requires_client", False)),
        "webhook_token_in_query": bool(getattr(adapter, "webhook_token_in_query", False)),
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
