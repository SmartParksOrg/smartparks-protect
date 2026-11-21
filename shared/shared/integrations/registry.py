"""Explicit outbound connector registry (decision D10): in-repo modules, no dynamic loading."""

from typing import Any

from shared.integrations.base import CodeLogin, OutboundConnector, SubjectRegistrar
from shared.integrations.connectors.earthranger import EarthRangerConnector
from shared.integrations.connectors.ferustracker import FerusTrackerConnector
from shared.integrations.connectors.gundi import GundiConnector
from shared.integrations.connectors.mqtt import MqttConnector
from shared.integrations.connectors.webhook import WebhookConnector
from shared.integrations.connectors.wildlifenl import WildlifeNlConnector

CONNECTORS: dict[str, OutboundConnector] = {
    connector.key: connector
    for connector in (
        GundiConnector(),
        EarthRangerConnector(),
        WildlifeNlConnector(),
        FerusTrackerConnector(),
        WebhookConnector(),
        MqttConnector(),
    )
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
        # the target keeps a register of the entities, which Protect can fill (D408)
        "registers_subjects": isinstance(connector, SubjectRegistrar),
        # how an account signs in, when Protect does it for the user (D414)
        "login": "email_code" if isinstance(connector, CodeLogin) else None,
        # the servers a person chooses from, for a target that has a fixed few; with a
        # sign-in this makes the whole setup a name and a choice (decision D415)
        "servers": [dict(server) for server in getattr(connector, "servers", ())],
        "intro": getattr(connector, "intro", None),
    }


def get_connector(key: str) -> OutboundConnector:
    try:
        return CONNECTORS[key]
    except KeyError:
        raise KeyError(f"unknown connector {key!r}; known: {sorted(CONNECTORS)}") from None
