"""Outbound connector contract (architecture 18, decisions D60 to D62).

A connector owns the translation from canonical Smart Parks objects to one target platform and
the delivery itself. It knows nothing about the delivery table, retries or filters: the
integration service loads the object, calls `render`, then `deliver`, and records the outcome.
Transient failures (network, 5xx) raise `TransientFailure` and are retried on the schedule;
permanent ones (4xx, a payload the target refuses, no location) raise `PermanentFailure` and end
the delivery as failed. `Skipped` ends it as skipped with a reason.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

from shared.notifications.dispatch import PermanentFailure, Skipped, TransientFailure

__all__ = [
    "DeliveryItem",
    "DeliveryResult",
    "IntegrationContext",
    "OutboundConnector",
    "PermanentFailure",
    "Skipped",
    "TransientFailure",
]


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    """The integration row without the ORM object: what a connector needs."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    connector_key: str
    config: dict[str, Any]
    credentials: dict[str, Any]


@dataclass(slots=True)
class DeliveryItem:
    """One canonical object with the names around it, ready to render. `location` is the
    object's own point or, for an event without one, the entity's latest known position."""

    object_type: str
    object_id: str
    object_version: int
    time: datetime
    project_id: uuid.UUID
    project_name: str
    project_slug: str
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    entity_type_key: str | None = None
    entity_type_label: str | None = None
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    device_serial: str | None = None
    device_type_key: str | None = None
    device_identity: str | None = field(
        default=None,
        metadata={
            "doc": "The device's primary external identity (DevEUI, IMEI, serial), the value "
            "printed on the hardware, for targets that register sensors by it"
        },
    )
    data_source_name: str | None = None
    location: tuple[float, float] | None = None
    location_is_fallback: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    link: str | None = None
    previous_external_id: str | None = field(
        default=None,
        metadata={
            "doc": "The target's id from an earlier delivery of the same object, so a corrected "
            "object updates instead of duplicating where the target allows it"
        },
    )


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    external_id: str | None = None
    response: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class OutboundConnector(Protocol):
    key: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    supports: ClassVar[frozenset[str]]
    config_schema: ClassVar[dict[str, Any]]
    config_example: ClassVar[dict[str, Any]]
    credentials_schema: ClassVar[dict[str, str]]
    setup_hint: ClassVar[str]

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        """The payload for one object. Pure: no network, no clock. Raises `Skipped` or
        `PermanentFailure` when the object cannot be represented."""
        ...

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        """Send one rendered payload."""
        ...

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        """Send something visible on the target, or check the connection when the target has
        no harmless test object. Returns what the target answered."""
        ...


def require_config(integration: IntegrationContext, *keys: str) -> None:
    missing = [k for k in keys if not integration.config.get(k)]
    if missing:
        raise PermanentFailure(f"integration {integration.name} is missing {', '.join(missing)}")


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")
