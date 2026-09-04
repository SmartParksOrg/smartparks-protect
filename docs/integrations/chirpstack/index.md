# ChirpStack

ChirpStack v4 is the reference LoRaWAN network server of Smart Parks Protect: it runs locally in the compose stack and exposes every event type, so the adapter, the OpenCollar driver and device control are tested here before any paid network.

## What the adapter does

- Subscribes to the ChirpStack MQTT integration (`application/+/device/+/event/+`, JSON marshaler) and turns every event into a source event: `up` becomes `uplink`, plus `join`, `status`, `downlink_ack` (from `ack`), `downlink_transmitted` (from `txack`), `log` and `location`.
- Records every gateway reception of an uplink with RSSI, SNR and frequency, and the best RSSI and SNR, spreading factor, port and frame counter as provider metadata.
- Keeps the ChirpStack receive time as `network_received_at`; the device time comes from the driver.
- Merges tenant, application and device profile ids and names into the external identity, so "Open in ChirpStack" links can be built.
- Lists applications, devices and gateways through the ChirpStack REST API (management connector, phase 3) and tests the connection.
- Accepts the same events over the ChirpStack HTTP integration at `POST /api/v1/ingest/http/{data_source_id}?event=up` with the source's bearer token.

Downlinks go through the REST API device queue, see [device control](../../devices/device-control.md).

## Data source configuration

| Key | Meaning |
| --- | --- |
| `mqtt_host`, `mqtt_port`, `mqtt_tls` | The broker ChirpStack publishes to (`chirpstack-mosquitto`, 1883 in compose) |
| `topic_prefix` | Only when ChirpStack is configured with an integration topic prefix |
| `api_url` | ChirpStack REST API (`http://chirpstack-rest-api:8090` in compose) |
| `web_url` | ChirpStack web UI, used in deep links (`http://localhost:8080`) |
| `tenant_id` | Tenant whose applications and gateways are listed |

Credentials: `api_token` (a ChirpStack API key), optional `mqtt_username` and `mqtt_password`.

## Local setup

```bash
docker compose --profile chirpstack up -d
scripts/dev.sh bootstrap-admin you@example.org       # once, then register through the link
scripts/dev.sh chirpstack-bootstrap --protect-email you@example.org --protect-password '...'
```

The bootstrap creates a tenant, the application `OpenCollar`, the device profile `OpenCollar EU868`, a simulated gateway and a device, mints a ChirpStack API key for the local stack, and registers the data source `ChirpStack (local)` in Smart Parks Protect. The ingest service picks the new source up within a minute and connects to the broker.

Then create a device type with the driver you want (`generic_json` for a first test, `opencollar` for real payloads), a device with the external identity `70B3D57ED0001234` on that data source, assign it to a project, and run the simulator:

```bash
scripts/dev.sh simulate --dev-eui 70B3D57ED0001234 --application-id <id printed by the bootstrap> --count 20 --rate 2
```

The simulator publishes uplinks on the same broker and topics a real ChirpStack uses, so everything from the ingest service onwards runs as in production. The radio path (gateway bridge, join, deduplication) is not simulated; a real gateway on UDP port 1700 exercises it.

## Timestamps

`time` on a ChirpStack event is when the network server processed the uplink. It is stored as `network_received_at` on the source event and is never the canonical time of a record unless the driver declares network time semantics for a record type (devices without a clock).

## Troubleshooting

- No events: check the ingest log for `connector started` with the source name and `mqtt subscribed`. The broker host must be reachable from the ingest container; in compose that is the service name, not `localhost`.
- Events arrive but Needs Attention shows an unknown identity: the DevEUI has no external identity on this data source. Create the device from Needs Attention or link the identity.
- `CONNECTIVITY_AUTH_FAILED` from the management connector: the API key is wrong or belongs to another tenant.
- Trace Explorer: search by DevEUI or device; a ChirpStack uplink trace has the steps source event stored, identity resolved, driver selected, payload decoded, canonical rows written.

## Example payloads

`tests/fixtures/payloads/chirpstack/` holds one JSON example per event type from the ChirpStack documentation; recorded events from a live instance are added there with a note of their origin.
