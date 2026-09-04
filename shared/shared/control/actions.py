"""Control action definitions (architecture 17.3, decision D49).

A driver declares its actions as `ControlAction` objects: a stable key, typed parameters as a
Pydantic model (exported as JSON schema for the UI and rules), the permission and confirmation
policy, the connectivity capability the route must have, an encoder that turns parameters into
a protocol payload, and an optional interpreter that recognises the device's response in later
decoded records. Definitions are code and carry a `schema_version`; a command stores the version
it was created with.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from shared.device_drivers.base import DecodedRecords
from shared.permissions import Permission

DEFAULT_EXPIRY_SECONDS = 24 * 3600


class ConfirmationPolicy(StrEnum):
    NONE = "none"  # runs at once
    CONFIRM = "confirm"  # the UI asks the user to confirm
    PRIVILEGED = "privileged"  # high-impact permission plus confirmation (architecture 27.6)


class NoParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class EncodedCommand:
    """What the adapter delivers: the payload and its transport options."""

    payload: bytes
    f_port: int
    confirmed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The device's answer as the driver reads it from decoded records."""

    confirmed: bool
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResponseContext:
    """What an interpreter sees: the records decoded from one later source event, the event
    type, and the parameters the command was created with."""

    event_type: str
    records: DecodedRecords
    parameters: dict[str, Any]


Encoder = Callable[[BaseModel], EncodedCommand]
Interpreter = Callable[[ResponseContext], CommandResult | None]


@dataclass(frozen=True, slots=True)
class ControlAction:
    key: str
    label: str
    description: str
    parameters: type[BaseModel]
    encode: Encoder
    permission: Permission = Permission.DEVICES_CONTROL
    confirmation: ConfirmationPolicy = ConfirmationPolicy.CONFIRM
    required_capability: str = "downlink"
    interpret: Interpreter | None = None
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS
    schema_version: int = 1

    def parameters_schema(self) -> dict[str, Any]:
        return self.parameters.model_json_schema()

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "parameters_schema": self.parameters_schema(),
            "permission": self.permission.value,
            "confirmation": self.confirmation.value,
            "required_capability": self.required_capability,
            "confirms": self.interpret is not None,
            "schema_version": self.schema_version,
        }


def actions_of(driver: Any) -> dict[str, ControlAction]:
    """The actions a driver declares; drivers without control declare none."""
    actions = getattr(driver, "control_actions", None)
    return dict(actions) if actions else {}
