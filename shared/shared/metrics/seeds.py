"""Canonical metrics with their unit, value type and category.

A driver converts to the canonical unit before emitting a measurement. Keys are lowercase
snake_case. Adding a metric here needs a migration that calls `seed_metrics`; the decoder also
registers unknown keys automatically with category `uncategorized`, which administrators then
curate.
"""

from dataclasses import dataclass

from shared.enums import ValueType


@dataclass(frozen=True, slots=True)
class MetricSeed:
    key: str
    label: str
    unit: str | None
    value_type: ValueType
    category: str
    description: str


N = ValueType.NUMERIC
B = ValueType.BOOLEAN

METRIC_SEEDS: tuple[MetricSeed, ...] = (
    # device health
    MetricSeed(
        "battery_voltage",
        "Battery voltage",
        "V",
        N,
        "device_health",
        "Battery voltage of the device",
    ),
    MetricSeed(
        "battery_level", "Battery level", "%", N, "device_health", "Battery charge, 0 to 100"
    ),
    MetricSeed(
        "solar_voltage", "Solar voltage", "V", N, "device_health", "Voltage from the solar panel"
    ),
    MetricSeed(
        "charge_current", "Charge current", "mA", N, "device_health", "Battery charging current"
    ),
    MetricSeed(
        "device_temperature",
        "Device temperature",
        "°C",
        N,
        "device_health",
        "Temperature measured inside the device",
    ),
    MetricSeed("uptime", "Uptime", "s", N, "device_health", "Seconds since the device started"),
    MetricSeed(
        "reset_count", "Reset count", None, N, "device_health", "Number of resets since production"
    ),
    MetricSeed(
        "error_count", "Error count", None, N, "device_health", "Errors counted by the firmware"
    ),
    MetricSeed(
        "free_memory", "Free memory", "B", N, "device_health", "Free memory reported by the device"
    ),
    # environment
    MetricSeed("temperature", "Temperature", "°C", N, "environment", "Ambient temperature"),
    MetricSeed("humidity", "Relative humidity", "%", N, "environment", "Relative humidity"),
    MetricSeed("pressure", "Air pressure", "hPa", N, "environment", "Barometric pressure"),
    MetricSeed("wind_speed", "Wind speed", "m/s", N, "environment", "Wind speed"),
    MetricSeed(
        "wind_direction",
        "Wind direction",
        "°",
        N,
        "environment",
        "Wind direction, degrees from north",
    ),
    MetricSeed(
        "rainfall", "Rainfall", "mm", N, "environment", "Precipitation in the reporting interval"
    ),
    MetricSeed(
        "water_level",
        "Water level",
        "m",
        N,
        "environment",
        "Water level above the sensor reference",
    ),
    MetricSeed("soil_moisture", "Soil moisture", "%", N, "environment", "Volumetric soil moisture"),
    MetricSeed("light", "Light", "lx", N, "environment", "Illuminance"),
    # movement and behaviour
    MetricSeed("speed", "Speed", "m/s", N, "movement", "Speed over ground from GNSS or derived"),
    MetricSeed("heading", "Heading", "°", N, "movement", "Course over ground, degrees from north"),
    MetricSeed("altitude", "Altitude", "m", N, "movement", "Height above mean sea level"),
    MetricSeed(
        "distance", "Distance", "m", N, "movement", "Distance travelled in the reporting interval"
    ),
    MetricSeed(
        "activity",
        "Activity",
        None,
        N,
        "behaviour",
        "Device-specific activity index, normalized per driver",
    ),
    MetricSeed(
        "acceleration_x", "Acceleration X", "m/s²", N, "behaviour", "Acceleration along the X axis"
    ),
    MetricSeed(
        "acceleration_y", "Acceleration Y", "m/s²", N, "behaviour", "Acceleration along the Y axis"
    ),
    MetricSeed(
        "acceleration_z", "Acceleration Z", "m/s²", N, "behaviour", "Acceleration along the Z axis"
    ),
    MetricSeed(
        "acceleration_magnitude",
        "Acceleration magnitude",
        "m/s²",
        N,
        "behaviour",
        "Magnitude of the acceleration vector",
    ),
    # positioning quality
    MetricSeed(
        "gnss_satellites", "GNSS satellites", None, N, "positioning", "Satellites used in the fix"
    ),
    MetricSeed(
        "gnss_hdop", "GNSS HDOP", None, N, "positioning", "Horizontal dilution of precision"
    ),
    MetricSeed(
        "gnss_accuracy", "GNSS accuracy", "m", N, "positioning", "Estimated horizontal accuracy"
    ),
    MetricSeed(
        "gnss_time_to_fix",
        "GNSS time to fix",
        "s",
        N,
        "positioning",
        "Seconds the receiver needed for the fix",
    ),
    MetricSeed(
        "gnss_fix", "GNSS fix", None, B, "positioning", "Whether the last attempt produced a fix"
    ),
    # connectivity
    MetricSeed(
        "rssi", "RSSI", "dBm", N, "connectivity", "Received signal strength at the best gateway"
    ),
    MetricSeed("snr", "SNR", "dB", N, "connectivity", "Signal to noise ratio at the best gateway"),
    MetricSeed(
        "spreading_factor",
        "Spreading factor",
        None,
        N,
        "connectivity",
        "LoRa spreading factor of the uplink",
    ),
    MetricSeed(
        "gateway_count",
        "Gateway count",
        None,
        N,
        "connectivity",
        "Gateways that received the uplink",
    ),
    MetricSeed(
        "frame_counter", "Frame counter", None, N, "connectivity", "LoRaWAN uplink frame counter"
    ),
    MetricSeed(
        "link_margin",
        "Link margin",
        "dB",
        N,
        "connectivity",
        "Demodulation margin reported by the device",
    ),
    # infrastructure
    MetricSeed("door_open", "Door open", None, B, "infrastructure", "Gate or door is open"),
    MetricSeed(
        "fence_voltage", "Fence voltage", "kV", N, "infrastructure", "Electric fence voltage"
    ),
    MetricSeed("trap_triggered", "Trap triggered", None, B, "infrastructure", "Trap trigger state"),
    MetricSeed("tank_level", "Tank level", "%", N, "infrastructure", "Fill level of a tank"),
    MetricSeed("flow_rate", "Flow rate", "L/min", N, "infrastructure", "Water flow"),
)


def seed_sql() -> str:
    """INSERT statement for a migration. Existing rows are left untouched."""
    values = ",\n".join(
        "({})".format(
            ", ".join(
                _literal(v)
                for v in (m.key, m.label, m.unit, m.value_type.value, m.category, m.description)
            )
        )
        for m in METRIC_SEEDS
    )
    return (
        "INSERT INTO metrics (key, label, unit, value_type, category, description) VALUES\n"
        f"{values}\nON CONFLICT (key) DO NOTHING"
    )


def _literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"
