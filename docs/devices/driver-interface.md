# Driver interface

A driver turns a source event of one device family into decoded records, and later encodes control actions. It knows nothing about the network the message came over. Drivers live in `shared/device_drivers/<family>/` and are registered in `shared/device_drivers/registry.py` (decision D10). Use `examples/device-drivers/example_device/` as the starting point.

## Contract

```python
class DeviceDriver(Protocol):
    key: ClassVar[str]  # "opencollar"
    label: ClassVar[str]
    capabilities: ClassVar[frozenset[str]]  # {"gnss", "battery", ...}
    timestamp_semantics: ClassVar[dict[str, TimestampSemantics]]  # per record type

    def decode(self, event: SourceEventData) -> DecodedRecords: ...
```

`SourceEventData` carries the payload, provider metadata, the network receive time, the ingest time and the device and device type settings. `DecodedRecords` holds lists of `DecodedPosition`, `DecodedMeasurement`, `DecodedState` and `DecodedEvent`, each with its canonical `time`.

## Rules

- Raise `ApplicationError` with `PAYLOAD_DECODE_FAILED` or `TIMESTAMP_INVALID` for a payload the driver cannot read. Set `user_actionable=True` when an administrator can fix it. Do not return partial garbage.
- Every time must be timezone-aware. Use the embedded device time when the protocol has one; declare `NETWORK_TIME` semantics for record types that do not.
- Set `fingerprint` on a record when two different records can share device, time and type.
- Metric keys are lowercase snake_case and exist in the metric registry with the canonical unit. Convert in the driver, never downstream.
- Keep provider specifics out: a driver never reads a ChirpStack or KPN field.

## Testing

Golden tests over recorded payloads under `tests/fixtures/payloads/<family>/`, each with a README that says where the payload came from. The generic JSON driver and its tests in `tests/shared/test_adapters_and_drivers.py` show the shape.
