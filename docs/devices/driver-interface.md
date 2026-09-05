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

`SourceEventData` carries the payload, provider metadata, the network receive time, the ingest time and the device and device type settings. For a LoRaWAN device the decoder service has already extracted the application payload: `event.frame` holds the bytes and `event.f_port` the port, whatever adapter delivered the uplink (`lorawan_frame` in `shared/device_drivers/base.py` reads ChirpStack's base64 `data` or the `frame_hex` other adapters store). `event.acquisition_channel` says whether the delivery came over LoRaWAN, Web Bluetooth, a log file or satellite. `DecodedRecords` holds lists of `DecodedPosition`, `DecodedMeasurement`, `DecodedState` and `DecodedEvent`, each with its canonical `time`.

## What a family needs

1. The driver module under `shared/device_drivers/<family>/` and its line in `registry.py`; the registry test in `tests/shared/test_adapters_and_drivers.py` lists the keys.
2. Metric keys that exist in the registry. The seeds are in `shared/metrics/seeds.py` and reach the database through a migration (`seed_sql()`, see migration 0003); a new key needs a new migration that runs `seed_sql()` again. Values with no metric of their own (a sensor's orientation, a dilution of precision) go into the position's `attributes` or a `DecodedState`.
3. Control actions, when the device takes downlinks: a `control_actions` class attribute with `ControlAction` objects from `shared/control/actions.py` (parameters as a Pydantic model, an encoder returning `EncodedCommand` with the payload and port, an optional interpreter that recognises the answer in later decoded records). The OpenCollar driver's `control.py` is the reference; [device control](device-control.md) explains the lifecycle.
4. Fixtures and golden tests under `tests/fixtures/payloads/<family>/` with a README naming the source of every payload; the vendor manual's worked examples are acceptable until recorded uplinks exist.
5. A page under `docs/devices/` (frame, what the driver produces, control, setup, testing), its line in `docs/devices/index.md` and `mkdocs.yml`, and a changelog entry.
6. A device type in the running system: Server admin, Device types, with the driver key; the family's DevEUIs then resolve to devices of that type through external identities or Needs attention.

## Rules

- Raise `ApplicationError` with `PAYLOAD_DECODE_FAILED` or `TIMESTAMP_INVALID` for a payload the driver cannot read. Set `user_actionable=True` when an administrator can fix it and `component="driver.<family>"`; the specifics go into `context`, a dict the trace shows. Do not return partial garbage.
- Every time must be timezone-aware. Use the embedded device time when the protocol has one; declare `NETWORK_TIME` semantics for record types that do not.
- Set `fingerprint` on a record when two different records can share device, time and type.
- Metric keys are lowercase snake_case and exist in the metric registry with the canonical unit. Convert in the driver, never downstream.
- Keep provider specifics out: a driver never reads a ChirpStack or KPN field.

## Testing

Golden tests over recorded payloads under `tests/fixtures/payloads/<family>/`, each with a README that says where the payload came from. The generic JSON driver and its tests in `tests/shared/test_adapters_and_drivers.py` show the shape.
