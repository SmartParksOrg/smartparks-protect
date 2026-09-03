"""Adapter contract (architecture 7 and 8.2).

An adapter knows one external platform: how to receive its events (event connector), how to
send commands to it (command connector, phase 6) and how to list its devices (management
connector). It produces `InboundMessage` objects and never looks inside a device payload.
Provider-specific code lives only under `shared/connectivity/adapters/<provider>/`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel

from shared.enums import AcquisitionChannel, IngestionMethod


class AdapterCapabilities(BaseModel):
    """What a data source can do. Stored per data source, defaults per adapter."""

    uplink: bool = False
    downlink: bool = False
    join_events: bool = False
    downlink_status: bool = False
    mac_events: bool = False
    device_management: bool = False
    gateway_metadata: bool = False
    gateway_management: bool = False
    gateway_status: bool = False
    statistics: bool = False


@dataclass(slots=True)
class InboundMessage:
    """One delivery from an external platform, before any device decoding."""

    external_id: str | None
    event_type: str
    payload: dict[str, Any]
    acquisition_channel: AcquisitionChannel
    ingestion_method: IngestionMethod
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    network_received_at: datetime | None = None
    satellite_delivered_at: datetime | None = None
    ble_synced_at: datetime | None = None
    file_uploaded_at: datetime | None = None
    identity_type: str = "dev_eui"


@dataclass(frozen=True, slots=True)
class DataSourceContext:
    """What an adapter needs from a data source row, without the ORM object."""

    id: uuid.UUID
    name: str
    adapter_key: str
    config: dict[str, Any]
    credentials: dict[str, Any]
    capabilities: AdapterCapabilities


Emit = Callable[[InboundMessage], Awaitable[None]]


@runtime_checkable
class EventConnector(Protocol):
    """External platform to Smart Parks Protect. `run` blocks until cancelled and calls `emit`
    for every message."""

    async def run(self, emit: Emit) -> None: ...


@runtime_checkable
class CommandConnector(Protocol):
    """Smart Parks Protect to external platform (phase 6)."""

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]: ...


@runtime_checkable
class ManagementConnector(Protocol):
    async def list_devices(self) -> list[dict[str, Any]]: ...


class Adapter(Protocol):
    """One per external platform. Registered in `shared.connectivity.registry`."""

    key: ClassVar[str]
    label: ClassVar[str]
    default_capabilities: ClassVar[AdapterCapabilities]
    default_link_templates: ClassVar[dict[str, str]]
    config_schema: ClassVar[dict[str, Any]]

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        """A long-running connector (MQTT, polling, websocket), or None for push sources."""
        ...

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        """Turn one HTTP push into messages. Raises `ApplicationError` on a malformed body."""
        ...
