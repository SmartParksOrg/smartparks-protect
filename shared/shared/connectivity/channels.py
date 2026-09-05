"""Channel switches on a data source: which channel owns the event connector, the webhook and
the platform API, and whether the source has it switched on. A missing switch means on."""

from typing import Any

from shared.connectivity.registry import ADAPTERS, channels_of

STREAM_KEYS = ("mqtt", "stream", "poll")


def channel_enabled(switches: dict[str, Any] | None, key: str | None) -> bool:
    if key is None:
        return True
    value = (switches or {}).get(key)
    return True if value is None else bool(value)


def _keys(adapter_key: str, direction: str) -> list[str]:
    adapter = ADAPTERS.get(adapter_key)
    if adapter is None:
        return []
    return [str(c["key"]) for c in channels_of(adapter) if c.get("direction") == direction]


def stream_channel_key(adapter_key: str) -> str | None:
    """The inbound channel the ingest service runs a connector for (MQTT, websocket, polling)."""
    return next((k for k in _keys(adapter_key, "in") if k in STREAM_KEYS), None)


def webhook_channel_key(adapter_key: str) -> str | None:
    return next((k for k in _keys(adapter_key, "in") if k == "http"), None)


def api_channel_key(adapter_key: str) -> str | None:
    return next((k for k in _keys(adapter_key, "out")), None)
