# ChirpStack

ChirpStack v4 is the reference LoRaWAN network server of Smart Parks Protect: it runs locally in the compose stack and exposes every event type, so the adapter, the OpenCollar driver and device control are tested here before any paid network.

## What the adapter does

- Subscribes to the ChirpStack MQTT integration (`application/+/device/+/event/+`, JSON marshaler) and turns every event into a source event: `up` becomes `uplink`, plus `join`, `status`, `downlink_ack` (from `ack`), `downlink_transmitted` (from `txack`), `log` and `location`.
- Records every gateway reception of an uplink with RSSI, SNR and frequency, and the best RSSI and SNR, spreading factor, port and frame counter as provider metadata.
- Keeps the ChirpStack receive time as `network_received_at`; the device time comes from the driver.
- Merges tenant, application and device profile ids and names into the external identity, so "Open in ChirpStack" links can be built.
- Lists applications, devices and gateways through ChirpStack's gRPC API (management connector) and tests the connection.
- Accepts the same events over the ChirpStack HTTP integration at `POST /api/v1/ingest/http/{data_source_id}?event=up` with the source's bearer token.

Downlinks go through the gRPC device queue, see [device control](../../devices/device-control.md).

## Data source configuration

| Key | Meaning |
| --- | --- |
| `mqtt_host`, `mqtt_port`, `mqtt_tls` | The broker ChirpStack publishes to (`chirpstack-mosquitto`, 1883 in compose) |
| `topic_prefix` | Only when ChirpStack is configured with an integration topic prefix |
| `api_url` | ChirpStack's gRPC API: `grpc://chirpstack:8080` in compose, `grpcs://host:443` through a TLS proxy |
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

## Channels

A ChirpStack source is three channels, and the source's form and its Status show which ones
the settings switch on and whether each works:

| Channel | Direction | Needs | Enables | Working when |
| --- | --- | --- | --- | --- |
| HTTP integration | in | nothing, the webhook token is issued on save | uplinks, joins, downlink acknowledgements | messages arrive on the webhook |
| MQTT subscription | in | `mqtt_host` (and `mqtt_username`, `mqtt_password` when the broker asks) | the same events plus gateway statistics | the ingest service reports its connection as connected |
| gRPC API | out | `api_url` (`grpcs://host:443` or `grpc://host:8080`) and the `api_token` credential | downlinks, device sync, gateway sync, Test connection | the last Test connection answered |

Each channel has its own switch on the source. A new source starts with the MQTT and API
channels off, since both need input; turn one on once its fields are filled in. Off means the webhook answers 409, the ingest
service runs no connector, or commands and syncs are refused, without touching the other
channels. Capabilities an unconfigured or switched-off channel would provide are held back:
with no API channel the source shows no downlink capability, whatever its declared
capabilities say. The form groups the settings per channel with the fields each needs (no
JSON), and Server admin, Data sources, Status lists the channels with their state.

## Connecting an existing ChirpStack

A ChirpStack v4 that already serves gateways and collars connects in one of two ways:

- **HTTP integration (no broker exposure).** Server admin, Data sources, New data source,
  adapter ChirpStack, with `mqtt_host` left empty, `web_url` the ChirpStack web UI and
  `tenant_id` the tenant. Copy the webhook URL and the bearer token shown once. In ChirpStack,
  open the application, Integrations, HTTP: payload encoding JSON, the webhook URL as the
  event endpoint URL, and a header `Authorization` with `Bearer <token>`. ChirpStack appends
  `?event=up`, `?event=join` and so on, which the webhook understands. Save; the next uplink
  appears under Network, Traffic.
- **MQTT.** When the broker ChirpStack publishes to is reachable from the server (a TLS
  listener with a user for this purpose), set `mqtt_host`, `mqtt_port`, `mqtt_tls` and the
  `mqtt_username` and `mqtt_password` credentials; the ingest service subscribes to the
  application and gateway topics and no HTTP integration is needed.

Downlinks, device sync and gateway sync use ChirpStack's gRPC API, the only API of
ChirpStack v4 (the REST gateway is not used): `api_url` is `grpcs://host:443` through a TLS
proxy or `grpc://host:8080` straight to ChirpStack on a private network, and `api_token` is an
API key of the tenant. Without an API channel the uplink path works and commands are held
back until one is configured.

Exposing the gRPC API through an existing nginx that fronts ChirpStack on 443 needs care:
ChirpStack's own web UI calls the same `/api.` paths as grpc-web over HTTP/1.1, so a
location that sends every `/api.` request to `grpc_pass` locks everyone out of the web UI.
Route on the content type instead: native gRPC (`application/grpc`) from this server goes to
`grpc_pass`, everything else keeps going to ChirpStack as before. A `map` outside the server
block and one location before `location /`:

```nginx
map "$http_content_type:$remote_addr" $chirpstack_api_route {
    "~^application/grpc(\+[^:]+)?:<this server's address>$"  grpc;
    "~^application/grpc(\+[^:]+)?:"                          deny;
    default                                                  web;
}

server {
    listen 443 ssl http2;
    # ... certificate and the existing settings ...

    location ~ ^/api\. {
        if ($chirpstack_api_route = deny) { return 403; }
        if ($chirpstack_api_route = web) { proxy_pass http://localhost:8080; }
        grpc_pass grpc://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        # unchanged
    }
}
```

Escape the dots of the address in the map (`178\.62\.201\.128`); to admit more clients, add a
line per address. The regular expression matches the gRPC protocol's content type
(`application/grpc`, optionally with a `+proto` or other suffix) and not grpc-web's
`application/grpc-web...`, which is how the browser is told apart. ChirpStack's gRPC services
live under paths such as `/api.DeviceService/Enqueue`, which is what the regular expression
matches; the server block must carry `http2`. Then `api_url` is `grpcs://<host>:443`. This
was checked against nginx 1.18 and ChirpStack 4.19.1: the web UI's login (grpc-web) and
pages keep working, native gRPC from the listed address reaches ChirpStack, and from any
other address answers 403.

Other setups:

- ChirpStack's `[api] bind` port (8080 in the standard docker-compose deployment) serves the
  web UI, grpc-web and native gRPC together and has no TLS option. On a private network or
  VPN, `api_url` can be `grpc://<host>:8080` with no proxy at all; over the internet that
  sends the API key in the clear, so use a TLS proxy or a firewall rule for this server's
  address.
- A separate TLS server block for gRPC only (for example port 8443 with `location / {
  grpc_pass grpc://127.0.0.1:8080; }` plus `allow`/`deny`) avoids the content-type routing
  and leaves the 443 block untouched; `api_url` is then `grpcs://<host>:8443`.
- Caddy speaks HTTP/2 to backends: `reverse_proxy h2c://chirpstack:8080` carries the web UI,
  grpc-web and native gRPC alike, so no special location is needed (Caddy's `versions`
  transport option documents `h2c`). In ChirpStack, Tenant, API keys: create a key and store it as the
`api_token` credential. "Test connection" on the data source calls the API with it; "Sync
devices" turns the tenant's devices into identities to link; "Sync gateways" fills the
gateway registry.

The DevEUI is the identity: register the collars' DevEUIs on the data source, or accept them
from Needs attention as their first uplinks arrive. While connecting, Server admin, Data
sources, Traffic shows every message the source receives, linked to a device or not, with
the raw payload; it refreshes every five seconds.

## Timestamps

`time` on a ChirpStack event is when the network server processed the uplink. It is stored as `network_received_at` on the source event and is never the canonical time of a record unless the driver declares network time semantics for a record type (devices without a clock).

## Troubleshooting

- No events: check the ingest log for `connector started` with the source name and `mqtt subscribed`. The broker host must be reachable from the ingest container; in compose that is the service name, not `localhost`.
- Events arrive but Needs Attention shows an unknown identity: the DevEUI has no external identity on this data source. Create the device from Needs Attention or link the identity.
- `CONNECTIVITY_AUTH_FAILED` from the management connector: the API key is wrong or belongs to another tenant.
- Trace Explorer: search by DevEUI or device; a ChirpStack uplink trace has the steps source event stored, identity resolved, driver selected, payload decoded, canonical rows written.

## Example payloads

`tests/fixtures/payloads/chirpstack/` holds one JSON example per event type from the ChirpStack documentation; recorded events from a live instance are added there with a note of their origin.
