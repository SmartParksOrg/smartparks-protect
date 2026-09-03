"""Explicit driver registry (decision D10)."""

from shared.device_drivers.base import DeviceDriver
from shared.device_drivers.generic_json import GenericJsonDriver

DRIVERS: dict[str, DeviceDriver] = {driver.key: driver for driver in (GenericJsonDriver(),)}


def get_driver(key: str) -> DeviceDriver:
    try:
        return DRIVERS[key]
    except KeyError:
        raise KeyError(f"unknown driver {key!r}; known: {sorted(DRIVERS)}") from None
