"""Settings files per device (decisions D426 to D429)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class SettingsFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    source: str = Field(description="upload (a file from the app) or ble (a snapshot)")
    filename: str
    settings_count: int
    has_credentials: bool
    firmware_version: str | None
    observed_at: datetime | None
    uploaded_by_user_id: uuid.UUID | None
    created_at: datetime


class SettingsFileList(BaseModel):
    items: list[SettingsFileRead]
    total: int
    can_download_credentials: bool = Field(
        description="The caller may control the device, so a download may hold the credentials"
    )


class SettingsFileUpload(BaseModel):
    """A file exported by the ble-settings-app, as the browser read it."""

    filename: str = Field(min_length=1, max_length=255)
    document: dict[str, Any] = Field(description="The file's JSON: setting name to value")
    exported_at: AwareDatetime | None = Field(
        default=None,
        description="When the file was exported, read by the browser from the app's file "
        "name; without it the file only fills in settings Protect does not know yet",
    )


class SettingsFileStored(BaseModel):
    file: SettingsFileRead
    created: bool = Field(description="False when the device held the same file already")
    recorded: int = Field(description="Settings whose known value changed")
    unknown: list[str] = Field(description="Names the catalogue of the device's firmware lacks")
    invalid: dict[str, str] = Field(description="Names whose value does not fit, with the reason")


class SettingsReadValue(BaseModel):
    id: int = Field(ge=0, le=0xFFFF, description="The catalogue id of the firmware named")
    hex: str = Field(max_length=128, pattern=r"^([0-9A-Fa-f]{2})*$")


class SettingsSnapshotRequest(BaseModel):
    """A read of the device's settings over Web Bluetooth, as the browser got it."""

    values: list[SettingsReadValue] = Field(max_length=512)
    firmware: str | None = Field(
        default=None, max_length=32, description="The firmware the status of this session named"
    )
    read_at: AwareDatetime
    complete: bool = Field(
        description="The device confirmed the end of the report; only then a snapshot is kept"
    )


class SettingsSnapshotStored(BaseModel):
    recorded: int
    file: SettingsFileRead | None = Field(
        description="The snapshot, when the read was whole; the newest file when it equals it"
    )
    created: bool
