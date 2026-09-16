"""OpenCollar Edge control actions (protocol research section 4: commands on FPort 32 as
`cmd_id length argument`, settings on FPort 3 as `id length value`). Responses arrive on the
message's natural port, which is how the interpreters recognise them."""

import struct
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.control.actions import (
    CommandResult,
    ConfirmationPolicy,
    ControlAction,
    EncodedCommand,
    NoParameters,
    ResponseContext,
)
from shared.permissions import Permission

PORT_SETTINGS = 3
PORT_COMMANDS = 32

CMD_RESET = 0xA1
CMD_SEND_STATUS = 0xA4
CMD_SEND_POSITION = 0xA5
CMD_GET_UBLOX_FIX = 0xB8
SETTING_UBLOX_SEND_INTERVAL = 0x02


def command(cmd_id: int, argument: bytes = b"") -> bytes:
    return bytes([cmd_id, len(argument)]) + argument


def setting(setting_id: int, value: bytes) -> bytes:
    return bytes([setting_id, len(value)]) + value


class GnssIntervalParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: int = Field(
        ge=0,
        le=172_800,
        description="Seconds between u-blox position uplinks; 0 disables periodic positions",
    )


def _encode_reset(_: BaseModel) -> EncodedCommand:
    return EncodedCommand(payload=command(CMD_RESET), f_port=PORT_COMMANDS)


def _encode_request_status(_: BaseModel) -> EncodedCommand:
    return EncodedCommand(payload=command(CMD_SEND_STATUS), f_port=PORT_COMMANDS)


def _encode_request_position(_: BaseModel) -> EncodedCommand:
    return EncodedCommand(payload=command(CMD_GET_UBLOX_FIX), f_port=PORT_COMMANDS)


CMD_SEND_ALL_SETTINGS = 0xA7
CMD_SEND_SINGLE_SETTING = 0xA8


class SettingNameParameters(BaseModel):
    """One catalogue setting by name."""

    model_config = ConfigDict(extra="forbid")

    setting: str = Field(min_length=1, max_length=64, description="The setting's catalogue name")


def _encode_request_setting(params: BaseModel) -> EncodedCommand:
    assert isinstance(params, SettingNameParameters)
    item = _catalog_item(params.setting)
    return EncodedCommand(
        payload=command(CMD_SEND_SINGLE_SETTING, bytes([int(item["id"])])),
        f_port=PORT_COMMANDS,
        metadata={"requested_setting": params.setting, "setting_id": int(item["id"])},
    )


class SettingParameters(BaseModel):
    """One catalogue setting by name and its new value, checked against the type and range."""

    model_config = ConfigDict(extra="forbid")

    setting: str = Field(min_length=1, max_length=64, description="The setting's catalogue name")
    value: Any = Field(description="The new value: a number, a boolean, a string or hex bytes")


def _catalog_item(name: str) -> dict[str, Any]:
    from shared.domain.reporting import driver_catalog

    for item in driver_catalog("opencollar"):
        if item.get("name") == name:
            return item
    raise ValueError(f"no setting {name!r} in the OpenCollar catalogue")


def _encode_setting(params: BaseModel) -> EncodedCommand:
    assert isinstance(params, SettingParameters)
    from shared.domain.reporting_rules import encode_setting_value

    item = _catalog_item(params.setting)
    value = encode_setting_value(item, params.value)
    return EncodedCommand(
        payload=setting(int(item["id"]), value),
        f_port=PORT_SETTINGS,
        metadata={"setting": params.setting, "setting_id": int(item["id"]), "value": params.value},
    )


def _encode_request_settings(_: BaseModel) -> EncodedCommand:
    return EncodedCommand(payload=command(CMD_SEND_ALL_SETTINGS), f_port=PORT_COMMANDS)


def _encode_gnss_interval(params: BaseModel) -> EncodedCommand:
    assert isinstance(params, GnssIntervalParameters)
    value = struct.pack("<I", params.interval_seconds)
    return EncodedCommand(
        payload=setting(SETTING_UBLOX_SEND_INTERVAL, value),
        f_port=PORT_SETTINGS,
        metadata={
            "setting": "ublox_send_interval",
            "setting_id": SETTING_UBLOX_SEND_INTERVAL,
            "value": params.interval_seconds,
        },
    )


def _status_records(context: ResponseContext) -> bool:
    return any(m.record_type == "status" for m in context.records.measurements)


def _interpret_status(context: ResponseContext) -> CommandResult | None:
    if _status_records(context):
        return CommandResult(confirmed=True, detail={"response": "status uplink on port 4"})
    return None


def _interpret_reset(context: ResponseContext) -> CommandResult | None:
    """A reboot shows as a join (OTAA rejoins on boot) or a status uplink whose reset reason
    is a software request."""
    if context.event_type == "join":
        return CommandResult(confirmed=True, detail={"response": "device rejoined"})
    for state in context.records.states:
        reason: dict[str, Any] = state.state.get("reset_reason") or {}
        if reason.get("software"):
            return CommandResult(
                confirmed=True, detail={"response": "status uplink after software reset"}
            )
    return None


def _interpret_position(context: ResponseContext) -> CommandResult | None:
    for position in context.records.positions:
        if position.attributes.get("port") == 2:
            return CommandResult(
                confirmed=True,
                detail={"response": "position uplink on port 2", "time": position.time.isoformat()},
            )
    return None


CONTROL_ACTIONS: dict[str, ControlAction] = {
    "REQUEST_STATUS": ControlAction(
        key="REQUEST_STATUS",
        label="Request status",
        description=(
            "Ask the device for a status message (battery, temperature, errors, versions)."
        ),
        parameters=NoParameters,
        encode=_encode_request_status,
        permission=Permission.DEVICES_CONTROL,
        confirmation=ConfirmationPolicy.NONE,
        interpret=_interpret_status,
    ),
    "REQUEST_POSITION": ControlAction(
        key="REQUEST_POSITION",
        label="Request position",
        description="Ask the device for a GNSS fix now. The fix arrives as a normal position.",
        parameters=NoParameters,
        encode=_encode_request_position,
        permission=Permission.DEVICES_CONTROL,
        confirmation=ConfirmationPolicy.NONE,
        interpret=_interpret_position,
    ),
    "SET_GNSS_INTERVAL": ControlAction(
        key="SET_GNSS_INTERVAL",
        label="Set GNSS interval",
        description=(
            "Change how often the device sends a u-blox position (setting ublox_send_interval)."
        ),
        parameters=GnssIntervalParameters,
        encode=_encode_gnss_interval,
        permission=Permission.DEVICES_CONTROL_HIGH_IMPACT,
        confirmation=ConfirmationPolicy.PRIVILEGED,
    ),
    "REQUEST_SETTING": ControlAction(
        key="REQUEST_SETTING",
        label="Request one setting",
        description=(
            "Ask the device for one setting by name (cmd_send_single_setting): a few bytes each "
            "way, the right choice over LoRaWAN or satellite."
        ),
        parameters=SettingNameParameters,
        encode=_encode_request_setting,
        permission=Permission.DEVICES_CONTROL,
        confirmation=ConfirmationPolicy.NONE,
    ),
    "REQUEST_SETTINGS": ControlAction(
        key="REQUEST_SETTINGS",
        label="Request all settings",
        description=(
            "Ask the device to report every setting (cmd_send_all_settings). Over Bluetooth the "
            "whole table arrives; over LoRaWAN or satellite only the first part does and it costs "
            "the device power: read all over Bluetooth, or ask for one setting at a time."
        ),
        parameters=NoParameters,
        encode=_encode_request_settings,
        permission=Permission.DEVICES_CONTROL,
        confirmation=ConfirmationPolicy.NONE,
    ),
    "SET_SETTING": ControlAction(
        key="SET_SETTING",
        label="Set a setting",
        description=(
            "Change one setting of the device by its catalogue name; the value is checked "
            "against the setting's type and range before it is sent."
        ),
        parameters=SettingParameters,
        encode=_encode_setting,
        permission=Permission.DEVICES_CONTROL_HIGH_IMPACT,
        confirmation=ConfirmationPolicy.PRIVILEGED,
    ),
    "RESET": ControlAction(
        key="RESET",
        label="Reset device",
        description=(
            "Reboot the device. It rejoins the network and sends a status message afterwards."
        ),
        parameters=NoParameters,
        encode=_encode_reset,
        permission=Permission.DEVICES_CONTROL_HIGH_IMPACT,
        confirmation=ConfirmationPolicy.PRIVILEGED,
        interpret=_interpret_reset,
    ),
}
