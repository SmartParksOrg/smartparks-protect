"""Outbound connector contract (architecture 18, decisions D60 to D62).

A connector owns the translation from canonical Smart Parks objects to one target platform and
the delivery itself. It knows nothing about the delivery table, retries or filters: the
integration service loads the object, calls `render`, then `deliver`, and records the outcome.
Transient failures (network, 5xx, 429) raise `TransientFailure` and are retried on the schedule;
permanent ones (other 4xx, a payload the target refuses, no location) raise `PermanentFailure`
and end the delivery as failed. `Skipped` ends it as skipped with a reason.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

from shared.notifications.dispatch import PermanentFailure, Skipped, TransientFailure

__all__ = [
    "CodeLogin",
    "DeliveryItem",
    "DeliveryResult",
    "IntegrationContext",
    "LoginResult",
    "OutboundConnector",
    "PartlyRegistered",
    "PermanentFailure",
    "Skipped",
    "Subject",
    "SubjectChoice",
    "SubjectOptions",
    "SubjectRegistrar",
    "SubjectStatus",
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
    entity_type_parent_key: str | None = field(
        default=None,
        metadata={"doc": "The type a sub-type sits under (D166): wildlife for an elephant"},
    )
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


@dataclass(frozen=True, slots=True)
class Subject:
    """An entity an integration forwards, with the device it has now: what a target that
    keeps a register of its own (an animal with its sensor) needs to know (decision D408)."""

    entity_id: uuid.UUID
    entity_name: str
    entity_type_key: str | None = None
    entity_type_label: str | None = None
    entity_type_parent_key: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    device_serial: str | None = None
    device_identity: str | None = None
    assigned_from: datetime | None = field(
        default=None, metadata={"doc": "Since when the device has been on the entity"}
    )


@dataclass(slots=True)
class SubjectStatus:
    """What the target has for one subject: `registered` since a moment, under a name."""

    registered: bool
    sensor_id: str | None = None
    external_id: str | None = None
    external_name: str | None = None
    since: datetime | None = None


@dataclass(frozen=True, slots=True)
class SubjectChoice:
    """One thing a user may pick for a subject on the target, such as a species."""

    id: str
    name: str
    common_name: str | None = None


@dataclass(slots=True)
class SubjectOptions:
    """What a user needs to see before integrating one entity (decision D413): how the target
    will know it, what it has for it already, what may be chosen and Protect's proposal, or
    why it cannot be integrated as it is."""

    sensor_id: str | None
    status: SubjectStatus
    species: list[SubjectChoice] = field(default_factory=list)
    proposed_species_id: str | None = None
    blocked: str | None = None


@runtime_checkable
class SubjectRegistrar(Protocol):
    """A connector whose target keeps a register of the subjects (decisions D408 and D412)."""

    async def options(self, integration: IntegrationContext, subject: Subject) -> SubjectOptions:
        """What may be chosen for one subject, read from the target."""
        ...

    async def statuses(
        self, integration: IntegrationContext, subjects: list[Subject]
    ) -> dict[uuid.UUID, SubjectStatus]:
        """What the target has for each subject, by entity id, in one read."""
        ...

    async def register(
        self,
        integration: IntegrationContext,
        subject: Subject,
        settings: dict[str, Any],
        external_id: str | None,
    ) -> SubjectStatus:
        """Register one subject as the user chose. `external_id` is what an earlier attempt
        made already. A refusal after something was made raises `PartlyRegistered` with its
        id, so the caller keeps it."""
        ...


@dataclass(frozen=True, slots=True)
class LoginResult:
    """What a login gave: the credentials to keep (encrypted, never shown) and the account
    they belong to, with what it may do on the target."""

    credentials: dict[str, Any]
    account: str
    scopes: list[str] = field(default_factory=list)


@runtime_checkable
class CodeLogin(Protocol):
    """A connector whose target signs an account in with a code sent by email (decision
    D414): the user never handles the token."""

    async def request_code(self, integration: IntegrationContext, email: str) -> None:
        """Ask the target to mail a code to the account's address."""
        ...

    async def exchange_code(
        self, integration: IntegrationContext, email: str, code: str
    ) -> LoginResult:
        """Trade the code for the credentials. A wrong or expired code is a
        `PermanentFailure` with what the target said."""
        ...


class PartlyRegistered(PermanentFailure):
    """The target made the first part of a registration and refused the rest."""

    def __init__(self, message: str, *, external_id: str) -> None:
        super().__init__(message)
        self.external_id = external_id


def require_config(integration: IntegrationContext, *keys: str) -> None:
    missing = [k for k in keys if not integration.config.get(k)]
    if missing:
        raise PermanentFailure(f"integration {integration.name} is missing {', '.join(missing)}")


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")
