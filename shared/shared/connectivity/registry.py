"""Explicit adapter registry (decision D10): in-repo modules, no dynamic loading."""

from shared.connectivity.adapters.generic_http import GenericHttpAdapter
from shared.connectivity.adapters.generic_mqtt import GenericMqttAdapter
from shared.connectivity.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    adapter.key: adapter for adapter in (GenericHttpAdapter(), GenericMqttAdapter())
}


def get_adapter(key: str) -> Adapter:
    try:
        return ADAPTERS[key]
    except KeyError:
        raise KeyError(f"unknown adapter {key!r}; known: {sorted(ADAPTERS)}") from None
