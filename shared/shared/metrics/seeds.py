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
    # air quality (OpenCollar port 21, firmware 7.2.0 and later)
    MetricSeed(
        "air_q_iaq", "Air quality index", None, N, "environment", "BME690 indoor air quality index"
    ),
    MetricSeed(
        "air_q_temperature",
        "Air temperature (air quality sensor)",
        "°C",
        N,
        "environment",
        "BME690 temperature",
    ),
    MetricSeed("air_q_pressure", "Air pressure", "hPa", N, "environment", "BME690 pressure"),
    MetricSeed("air_q_humidity", "Air humidity", "%", N, "environment", "BME690 relative humidity"),
    MetricSeed(
        "air_q_raw_gas", "Gas resistance", "Ω", N, "environment", "BME690 raw gas resistance"
    ),
    MetricSeed(
        "air_q_pm2_5_mass",
        "PM2.5 mass",
        "µg/m³",
        N,
        "environment",
        "BMV080 particulate mass, 2.5 µm",
    ),
    MetricSeed(
        "air_q_pm1_mass", "PM1 mass", "µg/m³", N, "environment", "BMV080 particulate mass, 1 µm"
    ),
    MetricSeed(
        "air_q_pm10_mass", "PM10 mass", "µg/m³", N, "environment", "BMV080 particulate mass, 10 µm"
    ),
    MetricSeed(
        "air_q_pm2_5_number",
        "PM2.5 count",
        "1/cm³",
        N,
        "environment",
        "BMV080 particle count, 2.5 µm",
    ),
    MetricSeed(
        "air_q_pm1_number", "PM1 count", "1/cm³", N, "environment", "BMV080 particle count, 1 µm"
    ),
    MetricSeed(
        "air_q_pm10_number", "PM10 count", "1/cm³", N, "environment", "BMV080 particle count, 10 µm"
    ),
    MetricSeed(
        "air_q_obstructed",
        "Particle sensor obstructed",
        None,
        B,
        "environment",
        "BMV080 reports an obstruction",
    ),
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
        "Change of the acceleration vector between two status messages (m/s²) for OpenCollar; "
        "a device-specific index for other drivers",
    ),
    MetricSeed(
        "ble_contacts",
        "Bluetooth contacts",
        None,
        N,
        "behaviour",
        "Devices a Bluetooth scan saw, one sample per scan window; zero means the device looked "
        "and saw nothing, which is a different thing from not having looked",
    ),
    MetricSeed(
        "human_presence",
        "Human presence",
        None,
        N,
        "behaviour",
        "1 when a scan under the phone filter heard a device people carry (decision D260). "
        "Presence in a window and never an identity: addresses rotate, so this is never a count "
        "of people",
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
    # volts, as the FenceEdge reports them (a u16 of volts, research 3.10); the fence panel shows
    # kV, which is how a fence person reads a fence (corrected 2026-09-19, the seed said kV)
    MetricSeed(
        "fence_voltage", "Fence voltage", "V", N, "infrastructure", "Electric fence peak voltage"
    ),
    MetricSeed(
        "fence_pulse_count",
        "Fence pulses",
        None,
        N,
        "infrastructure",
        "Pulses counted in one fence sampling window",
    ),
    MetricSeed(
        "fence_energy",
        "Fence pulse energy",
        None,
        N,
        "infrastructure",
        "Average pulse energy of a fence measurement, in the device's own units",
    ),
    MetricSeed("trap_triggered", "Trap triggered", None, B, "infrastructure", "Trap trigger state"),
    MetricSeed("tank_level", "Tank level", "%", N, "infrastructure", "Fill level of a tank"),
    MetricSeed("flow_rate", "Flow rate", "L/min", N, "infrastructure", "Water flow"),
    # the cardiac tag an OpenCollar Edge follows (port 15, phase 34, decisions D282 and D283).
    # The first two are ours, derived from the published arithmetic; the rest are what the tag
    # sent, under the reference decoder's own names. Five of them have no published meaning.
    MetricSeed(
        "heart_rate",
        "Heart rate",
        "bpm",
        N,
        "physiology",
        "Beats per minute from the cardiac tag's median R-R interval (6000 / rr_median, which is "
        "published in tens of milliseconds). Absent when the tag was heard but reported no "
        "cardiac reading",
    ),
    MetricSeed(
        "heart_rate_variability",
        "Heart rate variability",
        "ms",
        N,
        "physiology",
        "RMSSD in milliseconds: the square root of the tag's mean squared successive R-R "
        "difference. Firmware 6.9.0 and later; older firmware sends no HRV",
    ),
    MetricSeed(
        "cmdq_temperature",
        "Body temperature (cardiac tag)",
        "°C",
        N,
        "physiology",
        "Temperature from the cardiac tag, raw * 0.0248 - 18.09. Absent when the raw value is "
        "zero, which is the tag saying it has no reading",
    ),
    MetricSeed(
        "cmdq_success",
        "Cardiac reading succeeded",
        None,
        B,
        "physiology",
        "True when the tag's advertisement carried a temperature above zero, which is how the "
        "firmware's own decoder judges a reading. A sighting without one means the tag was "
        "heard and the heart was not",
    ),
    MetricSeed(
        "cmdq_rr_median",
        "R-R median",
        "10 ms",
        N,
        "physiology",
        "Median time between cardiac R peaks in tens of milliseconds, as the tag sends it. The "
        "source of the heart rate, kept because it is the measured value",
    ),
    MetricSeed(
        "cmdq_raw_temperature",
        "Raw temperature (cardiac tag)",
        None,
        N,
        "physiology",
        "The tag's raw temperature value, from which the temperature is derived",
    ),
    MetricSeed(
        "cmdq_hrv_raw",
        "Raw HRV (cardiac tag)",
        None,
        N,
        "physiology",
        "The tag's raw HRV value, the mean of squared successive R-R differences",
    ),
    MetricSeed(
        "cmdq_rr_median_modesum",
        "R-R median mode sum",
        None,
        N,
        "physiology",
        "Sent by the cardiac tag; its meaning is not published (IRNAS issue 389). Stored as the "
        "number it is",
    ),
    MetricSeed(
        "cmdq_activity_average",
        "Tag activity, average",
        None,
        N,
        "physiology",
        "The implant's own accelerometer score, unitless from 0 to 255: high while the animal is "
        "awake and moving, low in its sleep. A 0 is the implant's hourly fault, not a reading "
        "(D287). Not the device's own accelerometer activity",
    ),
    MetricSeed(
        "cmdq_activity_max",
        "Tag activity, highest",
        None,
        N,
        "physiology",
        "Sent by the cardiac tag; its meaning and unit are not published (IRNAS issue 389)",
    ),
    MetricSeed(
        "cmdq_active_min_in_last_hour",
        "Tag active minutes in the last hour",
        None,
        N,
        "physiology",
        "Sent by the cardiac tag; read as minutes, though the unit is not published (IRNAS "
        "issue 389)",
    ),
    MetricSeed(
        "cmdq_impedance",
        "Tag impedance",
        None,
        N,
        "physiology",
        "Sent by the cardiac tag; its meaning and unit are not published (IRNAS issue 389). It "
        "reads as a contact quality, which is a guess and not documented",
    ),
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
