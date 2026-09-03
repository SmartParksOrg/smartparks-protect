# 0011. Connectivity adapter boundary

Date: 2026-09-03

Status: accepted

## Context

The architecture's central rule is that connectivity adapters understand platforms and nothing about devices, drivers understand devices and nothing about networks, and the domain understands neither (sections 2, 7, 9). Phase 2 implements the pipeline before any provider-specific adapter so that provider shapes cannot leak into the domain.

## Decision

- `shared/connectivity/base.py` defines `Adapter`, `EventConnector`, `CommandConnector`, `ManagementConnector`, `InboundMessage` and `AdapterCapabilities`. Adapters produce `InboundMessage` and never decode payloads.
- `shared/device_drivers/base.py` defines `DeviceDriver`, `SourceEventData` and the decoded record types. Drivers never read provider fields.
- The ingest core (`shared/ingest.py`) and the decoder never import an adapter or driver module directly; they go through the registries.
- Two entry points share one ingest function: the API webhook endpoint for push platforms and the ingest service for connectors.
- The first adapters are generic HTTP and generic MQTT, the first driver is generic JSON. ChirpStack and OpenCollar follow in phase 3 without changes to the domain or the pipeline.

## Alternatives considered

- Building ChirpStack first: faster to a demo, but the pipeline would carry ChirpStack's shapes.
- Adapters that decode as well: simpler for one device family, breaks the moment the same device arrives over a second network.

## Consequences

A new platform is one directory under `adapters/`, a new device family one under `device_drivers/`. A guard test in phase 7 fails when provider names appear outside the adapters directory.
