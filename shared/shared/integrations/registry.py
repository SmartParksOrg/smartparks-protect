"""Explicit outbound connector registry (decision D10): in-repo modules, no dynamic loading."""

from typing import Any

from shared.integrations.base import OutboundConnector
from shared.integrations.connectors.earthranger import EarthRangerConnector
from shared.integrations.connectors.gundi import GundiConnector
from shared.integrations.connectors.mqtt import MqttConnector
from shared.integrations.connectors.webhook import WebhookConnector

CONNECTORS: dict[str, OutboundConnector] = {
    connector.key: connector
    for connector in (GundiConnector(), EarthRangerConnector(), WebhookConnector(), MqttConnector())
}


def describe_connector(connector: OutboundConnector) -> dict[str, Any]:
    return {
        "key": connector.key,
        "label": connector.label,
        "description": connector.description,
        "supports": sorted(connector.supports),
        "config_schema": dict(connector.config_schema),
        "config_example": dict(connector.config_example),
        "credentials_schema": dict(connector.credentials_schema),
        "setup_hint": connector.setup_hint,
    }


def get_connector(key: str) -> OutboundConnector:
    try:
        return CONNECTORS[key]
    except KeyError:
        raise KeyError(f"unknown connector {key!r}; known: {sorted(CONNECTORS)}") from None
