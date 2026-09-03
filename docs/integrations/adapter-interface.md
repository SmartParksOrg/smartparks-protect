# Adapter interface

An adapter knows one external platform: how to receive its events, how to send commands (phase 6) and how to list its devices. It never looks inside a device payload. Adapters live in `shared/connectivity/adapters/<provider>/` and are registered in `shared/connectivity/registry.py`. Provider-specific code lives nowhere else; a test enforces this from phase 7. Use `examples/adapters/example_platform/` as the starting point.

## Contract

```python
class Adapter(Protocol):
    key: ClassVar[str]  # "chirpstack"
    label: ClassVar[str]
    default_capabilities: ClassVar[AdapterCapabilities]
    default_link_templates: ClassVar[dict[str, str]]  # OPEN_DEVICE and so on
    config_schema: ClassVar[dict[str, Any]]  # JSON schema of the data source config

    def event_connector(self, source: DataSourceContext) -> EventConnector | None: ...
    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]: ...
```

Push platforms implement `parse_webhook`; the API calls it with the body of `POST /api/v1/ingest/http/{data_source_id}`. Platforms that need a long-running connection implement `event_connector`, which returns an object whose `run(emit)` blocks and calls `emit(InboundMessage)` per message; the ingest service runs it and restarts it when it ends. The transports under `shared/connectivity/transports/` (MQTT with reconnect, polling, websocket, HTTP helpers) do the generic part.

## InboundMessage

`external_id` (the provider's device identifier), `event_type` (uplink, join, ack, status, ...), `payload` (the provider's message as a JSON object), `acquisition_channel`, `ingestion_method`, `provider_metadata`, and the provenance times the platform knows (`network_received_at` and the satellite, BLE and file times). The adapter fills what the platform exposes and leaves the rest empty. It never invents a device time.

## Capabilities and links

`AdapterCapabilities` (architecture 8.2) is stored per data source; the adapter's defaults are the starting point and administrators adjust them for an account that exposes less. `default_link_templates` are URL templates with placeholders from the external identity, used for "Open in ..." links.

## Errors

A malformed body raises `ApplicationError` with `PAYLOAD_DECODE_FAILED`; the API answers 422. A connector that loses its connection reconnects; one that crashes is restarted after ten seconds and the crash is logged.

## Runbook

Every production adapter ships a runbook under `docs/integrations/<provider>/`: setup, authentication, uplink and downlink flow, timestamps, troubleshooting, example payloads (architecture 28.7).
