"""Raw device log files and browser syncs (architecture 25.6, phase 11)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from protect_api.schemas.common import ORMModel


class DeviceLogFileRead(ORMModel):
    id: uuid.UUID
    device_id: uuid.UUID
    project_id: uuid.UUID | None
    data_source_id: uuid.UUID
    acquisition_channel: str
    original_filename: str
    sha256: str
    size_bytes: int
    uploaded_by_user_id: uuid.UUID | None
    uploaded_at: datetime
    ble_synced_at: datetime | None
    status: str
    error_code: str | None
    error_message: str | None
    frames_total: int
    frames_failed: int
    records_found: int
    records_new: int
    records_duplicate: int
    period_start: datetime | None
    period_end: datetime | None
    firmware_version: str | None
    decoder_version: str | None
    trace_id: uuid.UUID | None
    processed_at: datetime | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class BleSyncRequest(BaseModel):
    """Frames the browser read from the device over Web Bluetooth, hex encoded, each starting
    with the port byte. Stored as a log file of channel `webble`."""

    frames: list[str] = Field(min_length=1, max_length=50_000)
    ble_synced_at: datetime | None = Field(
        default=None, description="When the browser read the frames; default now"
    )
    label: str = Field(
        default="", max_length=120, description="Shown as the file name, for example the reason"
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Session context: device name, browser, firmware"
    )


class DriverCatalog(BaseModel):
    driver_key: str
    catalog: dict[str, Any]
