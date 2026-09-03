# Smart Parks Protect

## Conceptual Architecture & Development Specification

SMART PARKS PROTECT

Proposal for a separate platform derived from AddaxAI Connect

    Purpose of this document
    This document consolidates the concept discussed for Smart Parks Protect into a shareable technical direction for the developer of AddaxAI Connect. It is intended as a starting point for architectural discussion, repository setup, technical spikes and definition of an MVP. It deliberately separates stable architectural principles from implementation choices that still need prototyping.

Draft v16 • 23 August 2026

# 1. Executive summary

Smart Parks Protect is proposed as a self-hosted, open and
integration-oriented operational data platform for Smart Parks
deployments. It should ingest data from heterogeneous device and IoT
ecosystems, normalize it into a consistent internal model, make that
data immediately useful for operations and analysis, and provide a
powerful rules and automation layer to turn data into events and
actions.

The platform must not be designed around one transport, one LoRaWAN
Network Server, one device family or one conservation use case.
OpenCollar and LoRaWAN are the first and most important implementation
targets, but the architecture should already accommodate other device
platforms such as Traccar, satellite services, direct MQTT or HTTP
devices, and future IoT systems.

The existing AddaxAI Connect codebase is a strong starting point because
it is already an actively developed, self-hosted multi-service platform
with a web application, PostgreSQL, Redis-based processing, projects,
RBAC, notifications, maps, charts and export. The proposal is therefore
to create a separate sibling/fork repository and reuse the generic
platform capabilities while replacing the camera/AI-specific domain with
a Smart Parks domain.

    Core product idea
    Smart Parks Protect should be the system of record and operational application layer between devices/external IoT platforms and users or downstream systems. It should monitor, analyze, export, integrate, control and automate across animals, people, vehicles, gates, traps, fences, weather stations, water systems and other Smart Parks assets.

# 2. Product principles

| Principle \| Meaning \|

| --- \| --- \|

| Source-agnostic \| No domain component may depend directly on
  ChirpStack, KPN, LORIOT, Actility, The Things Stack, Traccar or
  another external platform. \|

| Device-agnostic \| OpenCollar is the first-class initial device
  family, but device logic must be implemented through drivers rather
  than hard-coded into platform services or UI components. \|

| Entity-centric \| Users work with real-world entities such as an
  animal, person, vehicle, gate, trap or weather station. Devices can be
  assigned to those entities and replaced without losing entity history.
  \|

| Raw data is retained \| Original source events and payloads remain
  available for debugging, re-decoding, scientific traceability and
  future migrations. \|

| Normalized data is first-class \| Positions, measurements, events and
  state must use stable internal schemas regardless of their source. \|

| Analytics is a primary use case \| Tables, charts, aggregation,
  filtering and export are core product capabilities, not secondary
  features behind the live map. \|

| Rules produce meaning \| A powerful stateful rules engine turns
  observations and history into events, alerts and automated actions. \|

| Integrations are first-class \| EarthRanger, webhooks, MQTT and APIs
  are modeled as durable outbound integrations with retry and delivery
  tracking. \|

| Control is bidirectional \| Where supported, Smart Parks Protect can
  issue commands, configuration changes and downlinks without exposing
  network-provider specifics to the user. \|

| Self-hosted and project-aware \| The platform should preserve the
  multi-project, role-based and self-hosted model that already works
  well in AddaxAI Connect. \|

| Traceable provenance \| Every derived position, measurement, event and
  command must remain traceable to its source DataSource and external
  identity. Where possible, the UI provides an Open in source / Manage
  in source deep link to the external platform instead of duplicating
  all external management functionality. \|

| Entity-device temporal separation \| Entities and Devices have
  independent identities. Time-bounded assignments determine which
  device monitored which entity at any point in time, so devices can be
  replaced or reused without corrupting historical ownership of data. \|

| Capability-driven device control \| Device control actions are defined
  by DeviceType/DeviceDriver and routed through the active DataSource
  adapter. The driver defines what a command means and how it is
  encoded; the connectivity adapter defines how it is delivered to KPN,
  ChirpStack, LORIOT or another platform. \|

| WildlifeNL \| Outbound wildlife data platform \|

| FerusTracker \| Outbound tracking/monitoring platform \|

| Movebank \| Outbound animal movement platform \|

# 3. Relationship to AddaxAI Connect

AddaxAI Connect currently processes camera-trap images through an
ingestion and AI pipeline and presents the results through a self-hosted
web application. Its published architecture already separates processing
steps into Docker services, uses Redis queues, PostgreSQL and MinIO, and
supports multiple projects with role-based access control. These generic
platform characteristics should be reused where practical.

| AddaxAI Connect concept \| Smart Parks Protect equivalent / direction
  \|

| --- \| --- \|

| Camera \| Device \|

| Camera profile \| Device driver / device profile \|

| Site / camera deployment \| Entity, Site and Device Assignment /
  Deployment \|

| Image \| Source Event / raw device message \|

| EXIF extraction \| Connectivity adapter + device decoder \|

| Detection / classification \| Normalization + rules / scientific
  processing \|

| Species observation \| Position / Measurement / Event / Observation \|

| Camera health / battery \| Device State / Connectivity State \|

| Image ingestion via FTPS \| Multiple inbound adapters: LoRaWAN,
  Traccar, MQTT, REST, webhooks, etc. \|

| Notifications \| Notification + Automation actions \|

| Map / charts / export \| Retain and substantially expand \|

| MinIO \| Optional; required only where binary objects are actually
  used \|

| AI workers \| Replace with decoder, rule, aggregation and integration
  workers as needed \|

# 4. High-level architecture

    EXTERNAL SYSTEMS / CONNECTIVITY
      LoRaWAN: KPN | LORIOT | ChirpStack | TTS | Actility
      Tracking: Traccar
      Direct: MQTT | HTTP/Webhook | REST | WebSocket
      Future: Satellite | File import | Other IoT platforms
                             |
                             v
                  CONNECTIVITY ADAPTERS
           event | command | management connectors
                             |
                             v
                      SOURCE EVENTS
                    raw + traceable
                             |
                             v
                      DEVICE DRIVERS
              OpenCollar | GPS | weather | ...
                             |
                             v
                     NORMALIZED DOMAIN
     Position | Measurement | DeviceState | Event | Gateway data
                             |
          +------------------+-------------------+
          |                  |                   |
          v                  v                   v
       MONITOR             ANALYZE              RULES
     live map / ops    tables / charts      stateful logic
          |                  |                   |
          +------------------+-------------------+
                             |
                             v
                     AUTOMATION / CONTROL
     alerts | commands | EarthRanger | webhooks | MQTT | APIs
                             |
                             v
                     PostgreSQL/PostGIS
                (+ TimescaleDB to evaluate)

# 5. Smart Parks domain model

The top-level business domain should be broader than wildlife. Smart
Parks deployments include mobile entities, infrastructure, environmental
sensors and operational assets. A generic Entity model avoids forcing
every use case into the concept of a wildlife subject.

| Domain group \| Example entity types \| Typical data / state \|

| --- \| --- \| --- \|

| Tracked entities \| Animal, person, vehicle \| Position, movement,
  activity, speed, status \|

| Infrastructure \| Gate, fence, trap, water point, building \|
  Open/closed, triggered, voltage, faults, level \|

| Environmental monitoring \| Weather station, water sensor, soil
  sensor, acoustic station \| Time-series sensor measurements \|

| Equipment / assets \| Mobile equipment, devices, boats, aircraft \|
  Position, usage, state, alarms \|

| Sites & geography \| Park, reserve, area, zone, geofence, route \|
  Point, line or polygon geometry \|

A Device is hardware. An Entity is the real-world object being
monitored. They are linked through a time-bounded assignment or
deployment. This allows hardware replacement without breaking historical
continuity.

    Entity: "North Gate" [GATE]
           |
           +-- DeviceAssignment (2026-03-01 -> present)
                   |
                   +-- Device SP08xxxx [GateEdge]
                           |
                           +-- Connectivity: KPN LoRaWAN

    Entity: "Rhino 14" [ANIMAL]
           |
           +-- DeviceAssignment
                   |
                   +-- Device SP05xxxx [CollarEdge]
                           |
                           +-- Connectivity: LORIOT

# 6. Core entities and suggested data model

| Entity \| Purpose \|

| --- \| --- \|

| Organization \| Tenant/owner boundary if required. \|

| Project \| Access-control and operational grouping. \|

| Site \| Named location or area. \|

| Entity \| Real-world monitored object or asset. \|

| EntityType \| Animal, person, vehicle, gate, trap, weather station,
  etc. \|

| Device \| Physical device hardware. \|

| DeviceType / DeviceProfile \| Capabilities and family metadata. \|

| DeviceAssignment / Deployment \| Time-bounded relation between Device
  and Entity. \|

| DataSource \| External system or integration endpoint. \|

| ExternalIdentity \| Mapping from internal objects to DevEUI, Traccar
  ID, EarthRanger ID, etc. \|

| SourceEvent \| Immutable inbound event with original payload and
  metadata. \|

| NormalizedMessage \| Internal processing envelope. \|

| Position \| Canonical time-stamped geospatial observation. \|

| Measurement \| Canonical time-series metric value. \|

| DeviceState \| Latest operational state of the device. \|

| ConnectivityState \| Latest connectivity/network state. \|

| Event \| Meaningful domain event, often produced by a rule. \|

| Alert \| Event requiring user attention. \|

| Rule / RuleVersion \| Versioned logic producing events or decisions.
  \|

| Automation \| Actions initiated by events/rules. \|

| Command / CommandExecution \| Bidirectional device/network action with
  lifecycle. \|

| Integration / IntegrationDelivery \| Outbound data synchronization
  with durable delivery tracking. \|

| Gateway / GatewayReception \| Gateway state and per-uplink reception
  data when exposed by the network. \|

# 7. Connectivity layer

The Connectivity Layer is responsible for communicating with external
platforms. It must be explicitly separated from device semantics. For
example, a LORIOT adapter understands LORIOT, but it does not understand
OpenCollar. An OpenCollar driver understands OpenCollar payloads and
commands, but it does not understand LORIOT.

## 7.1 DataSource and connector types

| Connector responsibility \| Direction \| Examples \|

| --- \| --- \| --- \|

| Event Connector \| External platform → Smart Parks Protect \| MQTT
  subscription, HTTP webhook, WebSocket feed, polling \|

| Command Connector \| Smart Parks Protect → external platform \|
  LoRaWAN downlink, Traccar command, REST command \|

| Management Connector \| Bidirectional control-plane \| List devices,
  sync registrations, gateway status, statistics \|

Transport and provider logic should also remain conceptually separate.
One provider may support MQTT for events and REST for management;
another may expose gRPC. This avoids duplicating generic MQTT/HTTP
behavior throughout provider-specific adapters.

## 7.2 Initial external platform targets

| Platform \| Initial role \| Notes \|

| --- \| --- \| --- \|

| ChirpStack \| Full-feature reference LoRaWAN implementation \| Ideal
  for testing uplink, downlink, joins, gateway data and management under
  full control. \|

| KPN / ThingPark \| Primary Netherlands production LoRaWAN source \|
  Public-network capabilities may be more limited, especially gateway
  control. \|

| LORIOT \| International LoRaWAN source \| Important production use
  case. \|

| The Things Stack \| Additional LoRaWAN integration \| Good event and
  gateway APIs depending on rights. \|

| Actility / ThingPark \| Public or private LoRaWAN integration \|
  Capabilities depend strongly on deployment and permissions. \|

| Traccar \| Non-LoRaWAN tracking source \| Demonstrates that
  connectivity abstraction is genuinely generic. \|

| Generic MQTT / HTTP \| Future-proof direct integration \| Allows
  custom IoT feeds without creating a full platform adapter. \|

| AddaxAI Connect \| Application-level detection/event source \|
  Standard inbound connector for camera/AI detections such as species
  observations. Preserve source detection IDs, camera/site context,
  confidence and a direct link back to AddaxAI Connect. \|

| Cloudloop / Iridium \| Satellite connectivity source \| Inbound
  Iridium messages and outbound MT/SBD commands; preserve satellite
  delivery time separately from device-origin record time. \|

| WebBLE \| Direct local OpenCollar connectivity \| Browser-mediated
  settings, control and log/data offload; can deliver records already
  received through another path. \|

# 8. LoRaWAN specialization

LoRaWAN remains an important specialization within the generic
connectivity layer. Smart Parks Protect should normalize
application-plane and, where available, network-plane events.

## 8.1 Normalized LoRaWAN event types

-   Application uplink and downlink data.

-   Join request, join accept and rejoin lifecycle where exposed.

-   Downlink queued, accepted, scheduled, transmitted, acknowledged,
    failed and expired states where exposed.

-   MAC-related information where the LNS/API makes it available.

-   Gateway receptions per uplink, including RSSI/SNR and gateway
    identity.

-   Gateway connected/disconnected/status/statistics where available.

-   Network/device errors and diagnostics.

## 8.2 Capabilities model

Capabilities must be stored per configured DataSource, not inferred only
from the provider name. A public KPN/ThingPark account and a private
ThingPark installation may expose very different control-plane and
gateway features.

    capabilities:
      uplink: true
      downlink: true
      join_events: true
      downlink_status: true
      mac_events: false
      device_management: true
      gateway_metadata: true
      gateway_management: false
      gateway_status: false
      statistics: true

## 8.3 LoRaWAN traffic viewer

A technical traffic view should become a standard operations screen. It
should combine normalized events with the raw provider payload, decoder
result, network metadata, gateway receptions and processing history.

| Time \| Device \| Type \| Port \| FCnt \| Network \|

| --- \| --- \| --- \| --- \| --- \| --- \|

| 11:31:02 \| SP051583 \| UPLINK \| 13 \| 18234 \| KPN \|

| 11:30:46 \| SP051307 \| MAC \| - \| 8221 \| LORIOT \|

| 11:30:23 \| SP051583 \| DOWNLINK \| 3 \| 415 \| KPN \|

| 11:29:58 \| SP051307 \| JOIN \| - \| - \| LORIOT \|

# 9. Device drivers and OpenCollar

Device semantics belong in drivers. A driver exposes capabilities,
decodes inbound payloads into normalized objects, and encodes generic
commands into protocol-specific payloads. The frontend should consume
device capabilities instead of checking hard-coded device type names.

    Device Driver: OpenCollar
      capabilities:
        gnss
        accelerometer
        magnetometer
        ble_scanner
        wifi_scanner
        rf_scanner
        flash_logging
        remote_settings
        dropoff

      inbound:
        decode(source_event) -> positions / measurements / states / events

      outbound:
        encode(command) -> protocol payload + channel/port metadata

OpenCollar is the first driver family to implement comprehensively. It
should centralize port mappings, decoder versions, command encoding,
capabilities and protocol metadata that are currently distributed over
firmware, Node-RED flows, decoders and dashboards.

# 10. Data model for analytics

Analytics is a primary product requirement. The storage model must
support efficient time-series queries while preserving raw traceability.

## 10.1 Four accessible data levels

| Level \| Purpose \|

| --- \| --- \|

| Raw \| Original source event/payload exactly as received. \|

| Decoded \| Provider/device-specific decoded representation. \|

| Normalized \| Canonical Smart Parks metrics, positions, states and
  events. \|

| Aggregated \| Server-side time buckets and statistics for analysis and
  dashboards. \|

## 10.2 Metric registry

Measurements should use a semantic Metric registry so that values from
different device types can be compared and queried consistently.

| Metric key \| Canonical unit \| Category \| Example sources \|

| --- \| --- \| --- \| --- \|

| battery_voltage \| V \| device_health \| OpenCollar, tracker, sensor
  \|

| temperature \| °C \| environment / device \| Weather station, collar
  \|

| wind_speed \| m/s \| environment \| Weather station \|

| activity \| device-specific normalized metric \| behavior \|
  OpenCollar \|

| rssi \| dBm \| connectivity \| LoRaWAN \|

| snr \| dB \| connectivity \| LoRaWAN \|

| speed \| km/h or m/s canonicalized \| movement \| GNSS / Traccar \|

| water_level \| m / % \| environment \| Water sensor \|

## 10.3 Storage technology

PostgreSQL and PostGIS should remain core dependencies. Because large
time-series analysis is explicitly in scope, TimescaleDB should be
evaluated early as a PostgreSQL extension for measurements, network
metrics and device metrics. This is an implementation decision to
prototype, not yet a mandatory dependency.

# 11. Monitor: operational user experience

The live map remains a flagship view, but it is one of several top-level
workspaces. The map should primarily show Entities rather than technical
device identifiers, while allowing rapid drill-down to the assigned
Device and connectivity details.

| Primary workspace \| Purpose \|

| --- \| --- \|

| Live Map \| Current positions, tracks, geofences, infrastructure and
  events. \|

| Entities \| Animals, people, vehicles, gates, traps, weather stations
  and other monitored assets. \|

| Devices \| Hardware health, assignments, firmware, telemetry and
  commands. \|

| Network \| Network servers, LoRaWAN traffic, gateways and connectivity
  health. \|

| Alerts \| Operational events requiring attention. \|

Updates should be event-driven through WebSockets or equivalent, so a
new position, state change or event can update the UI immediately
without polling the entire page.

# 12. Analyze: tables, charts and dashboards

The Data Explorer should be a peer of the live map, not a hidden
technical feature. Users must be able to select projects, entities,
devices, metrics and time windows and switch directly between table,
chart, statistics and export views.

## 12.1 Data Explorer capabilities

-   Entity/device/metric/network filtering.

-   Flexible time ranges and timezone handling.

-   Server-side aggregation: raw, mean, min, max, median, sum, count.

-   Time buckets: 5 min, 15 min, hourly, daily, weekly and custom where
    practical.

-   Interactive line, scatter, bar, histogram and state/timeline
    visualizations.

-   Multi-series comparison across devices/entities.

-   Fast virtualized tables with sort, filter, column selection and
    grouping.

-   Saved queries/views and later project dashboards.

-   Drill-down from aggregated data back to normalized and raw source
    events.

# 13. Scalability, geospatial serving and large time-series

Scalability must be treated as an architectural requirement from the
first implementation. Smart Parks Protect should not depend on loading
unbounded raw position or sensor datasets into the browser. The storage,
API and frontend layers must use current-state representations,
server-side aggregation, level-of-detail strategies and efficient
geospatial delivery from day one.

## 13.1 Reference scale and design envelope

The following targets are design goals for architecture and performance
testing rather than hard product limits. They deliberately exceed the
expected size of many individual deployments so that the first
implementation does not embed assumptions that become expensive to
remove later.

| Dimension \| Initial design target \| Reason / interpretation \|

| --- \| --- \| --- \|

| Registered devices \| 25,000 per installation \| Includes inactive,
  historical and intermittently connected devices. \|

| Actively reporting devices \| 10,000 \| Devices producing telemetry
  during a normal operational period. \|

| Entities on live map \| 5,000 simultaneously visible \| Current
  positions/state should remain interactive without one DOM/SVG marker
  per item. \|

| Sustained ingest \| 250 source events/second \| Comfortable headroom
  above most current Smart Parks deployments. \|

| Burst ingest \| 1,000 source events/second for short periods \| Allows
  reconnect bursts, gateway/network recovery and batched platform
  delivery. \|

| Position history \| \>= 250 million Position records \| Representative
  of multi-year, multi-project tracking history. \|

| Measurements \| \>= 1 billion Measurement records \| Sensor projects
  can produce many metrics per message and exceed position volume
  rapidly. \|

| Retention \| 5+ years online/queryable \| Longitudinal research and
  operational history should not require routine archival restores. \|

| Concurrent interactive users \| 100 \| Reasonable self-hosted target
  for maps, analysis and operations without a cloud-scale architecture.
  \|

For reference, 1,000 devices reporting a GPS position every 5 minutes
produce approximately 105 million positions per year. If each message
produces ten normalized measurements, the same deployment can approach
one billion measurement rows per year. These orders of magnitude should
be used in synthetic performance tests.

## 13.2 Current state must be separate from history

The live map and device/entity overview must never determine current
state by repeatedly searching the entire Position or Measurement
history. Maintain a dedicated current/latest-state representation for
Entity and Device state, updated transactionally or through the domain
event pipeline.

    EntityCurrentState / DeviceCurrentState
      latest_position
      last_seen
      latest_device_state
      connectivity_state
      active_alerts / status summary
      updated_at

A live-map query for thousands of entities should therefore read a
compact current-state dataset rather than perform a
latest-row-per-entity calculation over hundreds of millions of
historical rows.

## 13.3 Geospatial map serving and level of detail

Historical positions and events should be served according to viewport,
zoom level, selected time range and requested detail. The browser must
not receive every raw point simply because it exists. PostGIS should
provide spatial filtering and the map API should support vector-tile or
equivalent WebGL-friendly delivery for dense layers.

-   Use bounding-box / viewport filtering for map requests.

-   Use zoom-dependent clustering for dense current-position and event
    layers.

-   Use vector tiles (for example Mapbox Vector Tile output from
    PostGIS) or an equivalent binary/tiled representation for large
    geospatial datasets rather than large GeoJSON responses.

-   Use track simplification / decimation based on zoom and time range.
    Preserve raw data in storage; simplify only the representation
    returned to the client.

-   Limit rendered historical track points per selected entity to
    approximately 5,000-10,000 points at any one level of detail;
    request finer detail as the user zooms spatially or temporally.

-   Keep tile/viewport payloads bounded. As a working target, individual
    map responses should normally remain below a few megabytes
    compressed and avoid tens of thousands of browser objects per layer.

-   Use a WebGL-capable renderer for high-volume point, line and
    vector-tile layers. Avoid architectures that require one DOM/SVG
    marker per position.

## 13.4 Historical tracks

A user should be able to request months or years of history without
transferring all raw points. The server should select an appropriate
resolution automatically and allow progressive drill-down to raw data.

| Selected period \| Typical map representation \| Indicative target \|

| --- \| --- \| --- \|

| Hours / 1 day \| Raw or near-raw positions \| Up to \~10,000 points
  per entity if useful. \|

| Days / weeks \| Decimated or time-bucketed track \| Thousands rather
  than hundreds of thousands of vertices. \|

| Months / years \| Strongly simplified / aggregated track \| Overview
  first; raw detail retrieved on zoom/drill-down. \|

For a one-year 5-minute track (\~105,000 raw points per entity), the
first map response should normally contain a simplified representation
rather than 105,000 individual features. Raw points remain accessible
for analysis, export and fine-grained drill-down.

## 13.5 Analytics resolution and server-side aggregation

Charts have the same scaling problem as maps. The API must select or
accept an explicit resolution and perform aggregation server-side. A
three-year chart should not download millions of raw measurements merely
to draw a line a few thousand pixels wide.

-   Target no more than roughly 2,000-5,000 plotted samples per series
    for normal interactive charts.

-   Use automatic time buckets based on selected period, with user
    override where appropriate.

-   Support mean, min, max, median, sum, count and other domain-relevant
    aggregates server-side.

-   Retain the ability to drill from an aggregate bucket back to the
    underlying normalized and raw records.

-   Precompute common aggregates/continuous aggregates when benchmarks
    show repeated expensive queries.

## 13.6 Database partitioning, indexing and retention

Large append-heavy tables must be designed for time-based pruning and
spatial/device lookup from the first database migrations. The exact
implementation should be benchmarked, but the schema must allow
partitioning/hypertables without later domain redesign.

-   Evaluate TimescaleDB hypertables for Measurement and potentially
    Position/network metric tables.

-   Use appropriate time-oriented indexes (including BRIN where useful
    for very large append-only tables).

-   Use GiST/SP-GiST PostGIS indexes for geometry queries.

-   Index common combinations such as device/entity + timestamp
    according to measured query patterns.

-   Do not add indexes indiscriminately; write throughput and storage
    cost must be part of benchmarking.

-   Support retention/downsampling policies in the architecture even if
    the default is to keep normalized data online for at least five
    years.

-   Raw SourceEvent retention may use a different policy from normalized
    scientific/operational records; the relationship and provenance must
    remain traceable.

## 13.7 Realtime performance targets

| Operation \| Target under normal load \|

| --- \| --- \|

| Normalized event -\> live client update \| p95 \< 2 seconds after
  processing/commit \|

| Open live map with \~5,000 current entities \| Interactive in \~3
  seconds on a normal broadband workstation \|

| Pan/zoom dense map \| Progressive/tiled updates without freezing the
  UI; target \< 1 second for cached tiles and \< 2 seconds for typical
  uncached viewport queries \|

| Open entity/device detail \| p95 \< 1 second for current state and
  recent summary \|

| Typical Data Explorer aggregate query \| p95 \< 3 seconds for common
  project/time ranges \|

| Historical track overview \| p95 \< 2-3 seconds for simplified
  representation \|

These figures are performance budgets for development and benchmarking,
not contractual SLAs. They make regressions visible and force bounded
API behavior.

## 13.8 Large export requirements

Large exports must be generated on the server and must never require the
browser to hold all records in memory. Small exports may be returned
immediately; large exports should use a durable export job with
progress/state, streaming generation and a downloadable result.

-   Interactive/direct export target: up to roughly 100,000 rows where
    response size remains reasonable.

-   Server-side export job target: at least 10 million rows for CSV
    without exhausting application memory.

-   Use streaming/chunked database reads and writers rather than
    building a complete dataframe in RAM.

-   For very large XLSX requests, enforce practical Excel-format limits
    and suggest CSV/Parquet-like future formats where appropriate.

-   Export filters, metric definitions, units, timezone and provenance
    metadata must be reproducible and recorded with the export job.

## 13.9 Performance test dataset and acceptance test

A synthetic scale dataset should be created early and kept as a
repeatable benchmark fixture. Functional development should not be
considered complete only because it works on a few test devices.

    Recommended benchmark fixture
      10,000 active devices
      5,000 entities with current positions
      250,000,000 historical positions
      1,000,000,000 measurements (or scaled generator capable of reaching this)
      multiple projects and data sources
      realistic spatial clustering and time distributions

    Benchmark:
      live-map load and updates
      viewport/vector-tile queries
      1-day / 30-day / 1-year tracks
      Data Explorer aggregates
      rules using rolling windows/geofences
      exports
      ingest bursts

## 13.10 Architectural rule: bounded queries

Every user-facing map, chart and table endpoint must have an explicit
bound: viewport, time range, pagination, resolution, row limit or
aggregation. An API endpoint that can accidentally return hundreds of
millions of raw records is considered an architectural defect, even if
the UI currently does not request that much data.

# 14. Export

Export must be designed as a backend capability, not merely a download
of whatever rows happen to be visible in the browser. An export should
be reproducible from explicit filters and formatting options.

| Export option \| Examples \|

| --- \| --- \|

| Formats \| CSV, XLSX, JSON, GeoJSON and optionally GPX/KML for tracks.
  \|

| Data level \| Raw, decoded, normalized or aggregated. \|

| Layout \| Long/tidy format or wide/pivoted format. \|

| Metadata \| Entity, device, source, metric unit, network metadata,
  timestamps. \|

| Time handling \| UTC by default, with explicit requested timezone. \|

| Scale \| Large exports should be generated server-side without loading
  all rows in the browser. \|

# 15. Rules & Automation Engine

Rules and automation are a core differentiator. The engine must support
simple operational thresholds, spatial/geofence logic, stateful
time-window conditions and more scientific detection rules. Rules create
transparent, versioned Events. Automations decide what to do with those
Events.

## 15.1 Rule inputs

-   Position and movement.

-   Measurements and historical aggregates.

-   DeviceState and ConnectivityState.

-   Entity type, assignment and deployment context.

-   Geospatial relationships and geofences.

-   Existing events.

-   Gateway/network state where relevant.

## 15.2 Required rule constructs

| Category \| Examples \|

| --- \| --- \|

| Threshold \| battery \< 3.2 V; temperature \> 40 °C \|

| Spatial \| ENTER, EXIT, INSIDE, OUTSIDE, NEAR, CROSSED, DWELL \|

| Movement \| speed \> limit; distance travelled \< threshold \|

| Temporal \| condition FOR 12 h; COUNT within 10 min \|

| Aggregation \| AVG, MIN, MAX, SUM, RATE, TREND, STDDEV \|

| Baseline \| value relative to individual 30-day baseline \|

| Correlation \| combine different devices, metrics or entities \|

| Event chaining \| rule triggered by a previous domain event \|

## 15.3 Example operational rule

    WHEN
      Entity type = VEHICLE
      AND speed > 40 km/h
      AND position INSIDE "Core Conservation Area"
    FOR 30 seconds

    THEN
      create Event:
        type = SPEED_LIMIT_VIOLATION
        severity = WARNING

    ACTIONS
      show alert in Smart Parks Protect
      send event to EarthRanger

## 15.4 Example scientific rule

    IF
      AVG(activity, 6h) < BASELINE(activity, 30d) * 0.35
      AND distance_travelled(6h) < 150 m
      AND battery_voltage > 3.2 V

    THEN
      create Event:
        type = POSSIBLE_IMMOBILITY
        include trigger values and confidence/context

## 15.5 Rule versioning and historical evaluation

Every generated Event should reference the exact RuleVersion that
created it. Rules must be testable against historical data before
activation. This is essential for scientific reproducibility and for
tuning thresholds without losing the rationale for historical
detections.

# 16. Events, alerts and actions

An Event represents something meaningful that happened. An Alert
represents an Event that requires user attention. These should not be
the same object.

| Object \| Meaning \|

| --- \| --- \|

| Event \| A domain fact or detection: geofence exit, possible
  immobility, trap triggered, heavy rainfall. \|

| Alert \| An event requiring attention, acknowledgement or resolution.
  \|

| Automation \| A configured reaction to an event/rule result. \|

| Action \| Concrete side effect: notification, webhook, EarthRanger
  post, MQTT publish, device command. \|

# 17. Bidirectional control and command lifecycle

## 17.1 Device Control Framework

## 17.2 Configurable control actions

    RESET DEVICE
        |
        +-- Device Driver = OpenCollar
        |       encode reset -> FPort / payload / confirmed flag
        |
        +-- active DataSource / Connectivity Adapter
                +-- KPN/ThingPark -> provider-specific downlink API
                +-- ChirpStack   -> MQTT or API/gRPC
                +-- LORIOT       -> provider-specific command path
        |
        +-- CommandExecution lifecycle / audit

Device control must be capability-driven and configurable per
DeviceType/DeviceDriver. The application exposes meaningful actions such
as RESET, REQUEST_LOCATION, REQUEST_STATUS or SET_CONFIGURATION. The
Device Driver owns protocol semantics and encoding; the active
Connectivity Adapter owns delivery to the external platform.

## 17.3 Same action, different network

The frontend should build its Actions menu from these capabilities. An
action is enabled only when both the Device Driver and the active
DataSource support the required functionality. If it is unavailable, the
UI should explain why.

| Property \| Purpose \|

| --- \| --- \|

| Action key \| Stable semantic identifier such as RESET,
  REQUEST_LOCATION or SET_GNSS_INTERVAL. \|

| Label / description \| User-facing action name and explanation. \|

| Parameters \| Typed parameters with validation, defaults, units and
  allowed ranges. \|

| Permissions \| Role/permission required to execute the action. \|

| Confirmation policy \| Whether the UI requires explicit confirmation,
  especially for disruptive or costly actions. \|

| Encoder \| DeviceDriver function that turns the semantic action into
  protocol-specific payload/metadata. \|

| Required connectivity capability \| For example DOWNLINK, COMMAND_API
  or BIDIRECTIONAL_MQTT. \|

| Result interpretation \| Optional mapping of subsequent device
  response/event to DEVICE_CONFIRMED or failure state. \|

## 17.4 Manual and automated control use the same path

    OpenCollar RESET
      -> OpenCollar driver produces the same protocol downlink
      -> Device A uses KPN: KPN adapter submits it
      -> Device B uses ChirpStack: ChirpStack adapter submits it

    No OpenCollar UI/domain code contains provider-specific logic.

User-facing commands must be provider-neutral. A generic command such as
REQUEST_LOCATION or SET_CONFIGURATION is handled by the Device Driver
and then routed through the appropriate connectivity adapter.

    User action
      -> DeviceCommand
      -> Device Driver encoding
      -> Connectivity adapter
      -> External network/platform
      -> Device
      -> optional device response
      -> CommandExecution status update

The lifecycle should preserve as much detail as the underlying platform
exposes: CREATED, ENCODED, SUBMITTED, ACCEPTED_BY_NETWORK, QUEUED,
SCHEDULED, TRANSMITTED, ACKNOWLEDGED, CONFIRMED_BY_DEVICE, FAILED and
EXPIRED. Unsupported lifecycle stages remain unknown rather than being
fabricated.

    User action --------+
                        +--> Device Control Action --> Device Driver --> Connectivity Adapter
    Rule / Automation --+

Rules and automations should invoke the same Device Control Action API
as a user in the UI. This avoids separate downlink implementations for
automation and makes permissions, audit logging, encoding, delivery
status and retry behavior consistent.

# 18. Integrations and EarthRanger

Outbound integrations should be durable, configurable and independent
from the ingest path. A temporary EarthRanger outage must never block
data ingestion or Smart Parks Protect.

## 18.1 Integration architecture

    Normalized Position / Measurement / Event
                  |
                  v
             Domain Event Bus
                  |
         +--------+---------+----------------+
         |                  |                |
     Live WebSocket      Rule Engine      Integration worker
                                             |
                                     +-------+-------+
                                     |       |       |
                                EarthRanger MQTT  Webhook/API

## 18.2 EarthRanger as first official outbound connector

-   Configurable project/entity mapping.

-   Realtime forwarding of selected Positions and Events.

-   Optional synchronization of Entities/subjects where appropriate.

-   Historical backfill over a selected date range.

-   Durable IntegrationDelivery state with retry, failure reason and
    payload/response inspection.

-   Rule actions can explicitly choose whether an event should be sent
    to EarthRanger.

This approach makes EarthRanger an important consumer of Smart Parks
Protect data rather than the primary store for device protocol, raw
telemetry or connectivity state.

## 18.3 AddaxAI Connect as a standard inbound application integration

Smart Parks Protect should include a supported
application-to-application connector for AddaxAI Connect. The goal is
not to merge both applications or duplicate camera and AI workflows, but
to let detections and observations generated in AddaxAI Connect enter
the same normalized Smart Parks event pipeline as device and sensor
data.

The preferred integration pattern is event-driven: AddaxAI Connect
publishes a detection through a webhook or API integration when it is
created or reaches a configured state. Smart Parks Protect stores the
original payload as a SourceEvent and maps it to a normalized Event
and/or Observation.

| AddaxAI Connect \| Smart Parks Protect \|

| --- \| --- \|

| AddaxAI project \| Smart Parks Project / configured integration
  mapping \|

| Camera \| Source Entity and/or external source context \|

| Camera/site location \| Event/Observation position and source context
  \|

| Detection / classification \| Smart Parks Event or Observation \|

| Species, e.g. wolf \| Event/Observation taxonomy attributes \|

| Confidence score \| Confidence / model result context \|

| Capture / detection time \| Observed/event timestamp \|

| Image / detection ID \| ExternalIdentity / source reference \|

| AddaxAI detection URL \| Provenance link: Open in AddaxAI Connect \|

A wolf detection, for example, should be able to become a Smart Parks
Event with the species/classification, confidence, timestamp,
camera/site, location, project mapping and original AddaxAI detection
reference. Rules can then enrich or react to that event exactly as they
do to LoRaWAN, Traccar or sensor-derived events.

    AddaxAI Connect detection
      species = wolf
      confidence = 0.94
      camera = Camera 17
      source_detection_id = ...
            |
            v
    Smart Parks SourceEvent [ADDAXAI_CONNECT]
            |
            v
    Normalized Event: SPECIES_DETECTION
      entity/source context = Camera 17
      species = wolf
      confidence = 0.94
      provenance_url = Open in AddaxAI Connect
            |
            +--> Live map / Event view
            +--> Rules & Automation
            +--> EarthRanger / webhook / notification

-   Inbound integration should support idempotency so that the same
    AddaxAI detection cannot accidentally create duplicate Smart Parks
    events.

-   The connector should preserve raw payloads and model/classification
    metadata for provenance and future reprocessing or audit.

-   Where AddaxAI Connect exposes a stable web URL for a detection,
    camera or project, Smart Parks Protect should surface an "Open in
    AddaxAI Connect" link rather than attempting to reproduce all
    camera-management functionality.

-   The integration should be configurable per project: users decide
    which detection types, species/classes, confidence thresholds and
    projects are forwarded.

-   A later bidirectional integration may be possible, but the initial
    requirement is a robust AddaxAI Connect → Smart Parks Protect event
    path.

# 19. Internal event bus

Normalized domain changes should produce internal events such as
position.created, measurement.created, event.created, alert.created and
device.state_changed. Consumers can independently handle realtime UI,
rules, notifications, integrations and aggregation. The exact
implementation could initially reuse Redis capabilities already present
in AddaxAI Connect, while preserving an interface that could later
migrate to a stronger event broker if scale requires it.

# 20. Gateway and network monitoring

Gateway monitoring should be available when an external platform exposes
the necessary information. Gateways are separate objects from Devices.

-   Gateway registry and location.

-   Online/offline/unknown state and last seen.

-   Uplink/downlink counts and TX errors where available.

-   Per-uplink GatewayReception records with RSSI/SNR.

-   Gateway diversity and best-gateway analysis.

-   Provider-specific diagnostics stored as attributes without polluting
    the canonical schema.

Network health and device health should be distinct. A device can be
healthy but poorly connected, or connected well while reporting internal
device faults.

Consider a reusable ExternalLink or link-template mechanism on
DataSource/ExternalIdentity rather than hard-coding provider URLs
throughout the frontend. It can expose actions such as OPEN_DEVICE,
OPEN_GATEWAY, OPEN_APPLICATION or OPEN_EVENT and build the URL from
provider-specific identifiers.

# 21. Data provenance and external source navigation

## 21.1 Provenance chain

Smart Parks Protect should make data lineage visible to users rather
than hiding the external system behind normalization. A user inspecting
a GPS point, sensor measurement, event or device should be able to
determine where the data came from and, where the external platform
supports a stable URL, open the corresponding device or resource
directly in that platform.

## 21.2 Open in source / Manage in source

The assignment must be resolved using the timestamp of the data, not
only the device's current assignment. This guarantees that historical
data remains associated with the correct animal, vehicle or other Entity
after a device is moved or reused.

    Entity / Position / Measurement / Event
            |
            +-- DeviceAssignment valid at event timestamp
            |       +-- Device
            |
            +-- SourceEvent
                    +-- DataSource
                    +-- ExternalIdentity
                    +-- raw provider event
                    +-- external resource URL / deep link

## 21.3 ExternalLink model

The goal is not to replicate every function of the external platform.
Smart Parks Protect should provide the functions needed for
cross-platform operations and analytics, while preserving a clear escape
hatch to the authoritative external management UI for provider-specific
administration.

| Context \| Expected navigation \|

| --- \| --- \|

| GPS point received via KPN LoRaWAN \| Show DataSource = KPN,
  DevEUI/external identity and a link to the relevant KPN/ThingPark
  management page when a stable URL can be constructed or stored. \|

| OpenCollar device via ChirpStack \| Show the ChirpStack source and an
  Open in ChirpStack link to the corresponding device/application where
  supported. \|

| Position received from Traccar \| Show Traccar as the source and link
  to the corresponding device/resource where possible. \|

| Outbound EarthRanger delivery \| Show the IntegrationDelivery and,
  where possible, the resulting external EarthRanger object/link. \|

# 22. Security, tenancy and traceability

-   Retain AddaxAI Connect's project-aware RBAC model where possible.

-   Credentials for DataSources and integrations must be stored securely
    and never embedded in project configuration exports.

-   SourceEvent and processing references should make normalized data
    traceable back to the original inbound message.

-   Rule changes and high-impact control actions should be auditable.

-   Raw provider payloads can contain sensitive identifiers; access
    should respect project/role boundaries.

-   Outbound integrations should have scoped access to selected
    projects/data types.

# 23. UI/UX and initial Smart Parks branding

For the initial Smart Parks Protect version, the existing AddaxAI
Connect visual language and user experience should be retained wherever
practical. The first implementation is a functional domain
transformation and rebranding exercise, not a general frontend redesign.
This deliberately reduces scope and allows development effort to focus
on the new Smart Parks domain, connectivity, analytics, rules,
integrations and device control.

## 23.1 Initial rebranding scope

-   Replace the AddaxAI Connect product name with Smart Parks Protect in
    the application shell and relevant user-facing locations.

-   Replace the AddaxAI Connect logo with the Smart Parks logo.

-   Use Smart Parks dark green #52735E as the primary brand colour.

-   Use Smart Parks light green #90AE9B as the secondary/supporting
    brand colour.

-   Retain the existing typography, spacing, component styling, cards,
    buttons, dialogs, responsive behaviour and other established AddaxAI
    Connect UI patterns unless a functional requirement makes a change
    necessary.

## 23.2 Reuse before redesign

Existing AddaxAI Connect layouts and components should be reused for
equivalent Smart Parks Protect functions wherever possible. New
interaction patterns should only be introduced where the new domain
requires functionality that does not exist in AddaxAI Connect, for
example the Data Explorer, Rules Builder, Device Control views,
LoRaWAN/Network Traffic views and integration delivery tooling.

## 23.3 Explicitly out of scope for the initial version

-   A complete visual redesign of the application.

-   A new design system or replacement component library.

-   Changing established interaction patterns solely for cosmetic
    reasons.

-   Reworking existing responsive behaviour unless required by new
    functionality.

-   Broad visual experimentation that delays the first working Smart
    Parks Protect demonstrator.

Development work should distinguish clearly between (1) rebranding, (2)
domain refactoring and (3) genuinely new functionality. This makes it
easier to preserve proven AddaxAI Connect frontend behaviour while
independently evolving Smart Parks Protect.

# 24. Smart Parks Icon System and map symbology

Smart Parks Protect should use a consistent, high-quality icon system
for wildlife, people, vehicles, infrastructure, devices, sensors and
events. The initial architecture should define how icons are referenced,
rendered and extended without yet committing to the exact SVG asset for
every type. EarthRanger should be evaluated as the primary
visual/semantic reference for wildlife and conservation assets,
supplemented by a well-licensed general SVG library and a small Smart
Parks-specific set where necessary.

## 24.1 Smart Parks Icon Registry

Application data must reference semantic icon keys rather than filenames
or library-specific identifiers. A central Smart Parks Icon Registry
maps those stable keys to the actual SVG assets and records provenance,
licensing, aliases, fallbacks and optional EarthRanger mappings. This
allows icon artwork to be replaced or improved later without changing
Entity, Device, Event or Feature records.

    Examples of stable icon keys

    wildlife.elephant
    wildlife.rhino
    wildlife.wolf
    wildlife.pangolin

    person.ranger
    person.researcher

    vehicle.car
    vehicle.4x4
    vehicle.truck
    vehicle.motorcycle
    vehicle.boat
    vehicle.helicopter
    vehicle.drone

    infrastructure.gate
    infrastructure.fence
    infrastructure.electric_fence
    infrastructure.water_point

    device.camera_trap
    device.lora_gateway
    device.weather_station
    device.opencollar
    device.sensor

    event.alert
    event.fire
    event.detection
    event.mortality
    event.geofence
    event.device_offline

| Registry field \| Purpose \|

| --- \| --- \|

| icon_key \| Stable semantic identifier used by application/domain
  data. \|

| category \| Wildlife, person, vehicle, infrastructure, device, event,
  etc. \|

| label \| Human-readable name. \|

| svg_asset \| Current SVG resource selected for rendering. \|

| source \| EarthRanger, external open library, or Smart Parks. \|

| license \| Recorded reuse/license information for the specific asset.
  \|

| aliases \| Alternative names that resolve to the same semantic icon.
  \|

| fallback_icon \| Icon used when a more specific asset is unavailable.
  \|

| earthranger_mapping \| Optional corresponding EarthRanger icon/type
  identifier. \|

## 24.2 Wildlife and species icon hierarchy

Wildlife should use recognizable species silhouettes wherever a suitable
icon exists. The system should not require a unique icon for every
biological species. Instead it should use a hierarchical fallback model
so that uncommon species still receive a meaningful taxonomic/group
icon.

    Species-specific icon
      Canis lupus -> wildlife.wolf
            |
            v if unavailable
    Taxonomic/group icon
      Canidae -> wildlife.canid
            |
            v if unavailable
    Generic wildlife icon
      wildlife.generic

The registry should therefore support both species-level and broader
group icons such as canid, feline, antelope, primate, bird, raptor,
reptile, fish and insect. The exact initial species catalogue can be
populated later based on Smart Parks deployments and the legally
reusable EarthRanger assets that can be identified.

## 24.3 Operational assets and technical infrastructure

The same icon system must cover non-wildlife Smart Parks assets.
EarthRanger should be reused where suitable assets are legally and
technically available. Missing technical symbols can be sourced from a
consistent open SVG library, while Smart Parks-specific hardware may use
purpose-made icons in the same monochrome silhouette style.

| Category \| Examples that should be covered \|

| --- \| --- \|

| People \| Ranger, researcher, field staff, generic person. \|

| Vehicles \| Car, 4x4, truck, motorcycle, bicycle, boat, aircraft,
  helicopter, drone. \|

| Infrastructure \| Gate, fence, electric fence, fence energizer,
  building, ranger post, water point, water tank, pump. \|

| Monitoring devices \| Camera trap, CCTV camera, LoRaWAN gateway,
  weather station, acoustic sensor, water sensor, BLE beacon. \|

| Smart Parks hardware \| OpenCollar/collar, TrapEdge, GateEdge and
  other core device families where a dedicated symbol adds value. \|

| Connectivity \| LoRaWAN gateway, satellite/Iridium connectivity, base
  station where relevant. \|

## 24.4 Visual consistency and status semantics

All icons should be rendered through a Smart Parks presentation layer
with consistent marker shape, padding, line/silhouette weight and
sizing. The icon communicates object type; colour should primarily
communicate state or status rather than being the only way to
distinguish object categories.

| Visual dimension \| Recommended meaning \|

| --- \| --- \|

| Central icon/silhouette \| What the object is: wolf, vehicle, gate,
  gateway, camera, etc. \|

| Marker family/shape \| Whether it is an entity/asset, infrastructure
  feature or event. \|

| Colour/state treatment \| Normal, warning, critical, offline, selected
  or historical. \|

| Badge/overlay \| Optional secondary state such as alert, connectivity
  issue or selected status. \|

## 24.5 Entities, infrastructure and events must be visually distinct

A tracked entity and an event involving that entity are different
concepts and must not look identical on the map. For example, a tracked
wolf should use the normal wildlife entity marker, while a wolf
detection from AddaxAI Connect should use the event marker family with a
wolf/detection symbol. Likewise a camera trap is an asset, while a
camera-generated detection is an event.

## 24.6 Configurable icons per domain type

Administrators should be able to select an icon_key for EntityType,
DeviceType, EventType and map FeatureType definitions. Projects can
therefore use the standard registry without hard-coded frontend logic. A
later phase may optionally allow project-specific SVG uploads, subject
to security, validation and licensing rules.

## 24.7 EarthRanger interoperability

Because EarthRanger is an important Smart Parks integration, the
registry should support optional mappings between Smart Parks icon
keys/types and corresponding EarthRanger presentation identifiers. This
helps maintain visual and semantic familiarity across both systems
without making Smart Parks Protect dependent on EarthRanger's internal
asset filenames or implementation details.

    Example mapping

    Smart Parks                  EarthRanger
    wildlife.elephant      ->    elephant
    wildlife.wolf          ->    wolf
    vehicle.4x4            ->    all-terrain vehicle equivalent
    device.camera_trap     ->    camera trap equivalent
    device.lora_gateway    ->    LoRa gateway equivalent
    infrastructure.gate    ->    park gate equivalent

## 24.8 Asset sourcing strategy

The exact icon catalogue is intentionally deferred. During
implementation, each candidate SVG should be reviewed for visual
quality, technical suitability and license/reuse terms before being
imported into the Smart Parks-controlled asset set. The preferred order
is: (1) suitable EarthRanger icon where reuse is confirmed, (2)
consistent well-licensed general SVG icon, (3) purpose-made Smart Parks
icon for domain-specific hardware or concepts.

Runtime dependence on third-party icon CDNs or unstable external asset
paths should be avoided. Approved SVGs should be vendored into the Smart
Parks Protect repository or another controlled build asset package
together with attribution/license metadata where required.

## 24.9 Suggested repository structure

    frontend/
      assets/
        icons/
          wildlife/
          people/
          vehicles/
          infrastructure/
          devices/
          events/
        icon-registry.json

    Example registry entry:
    {
      "wildlife.wolf": {
        "asset": "wildlife/wolf.svg",
        "category": "wildlife",
        "fallback": "wildlife.canid",
        "source": "to-be-confirmed",
        "license": "to-be-confirmed",
        "earthranger_mapping": "wolf"
      }
    }

## 24.10 Initial implementation requirement

The MVP does not need the final complete icon catalogue. It does need
the Icon Registry, fallback mechanism and consistent marker renderer
from the beginning. A representative starter set should cover the main
Smart Parks concepts (common wildlife, person/ranger, vehicle/4x4, gate,
electric fence, camera trap, LoRaWAN gateway, weather station,
OpenCollar and core event states). The library can then be expanded
without changing the application architecture.

# 25. Multi-path OpenCollar data, WebBLE, raw logs and satellite connectivity

OpenCollar devices can deliver the same underlying device-generated data
through more than one path. A CollarEdge may send a record through a
LoRaWAN Network Server, expose the same stored record later through
WebBLE, or include it in a raw log file that is uploaded manually. Some
deployments may also use Iridium satellite connectivity through
Cloudloop. Smart Parks Protect must preserve every delivery for
traceability while presenting only one canonical observation in maps,
charts, rules and normal analysis.

## 25.1 Origin, acquisition path and delivery are separate concepts

The architecture must distinguish what generated the data from how that
data reached Smart Parks Protect. A physical Device is the origin.
LoRaWAN, WebBLE, file upload or Iridium are acquisition/connectivity
paths. KPN, LORIOT, ChirpStack and Cloudloop are external platforms.
MQTT, webhook, API, browser synchronization or file upload are ingestion
mechanisms.

| Dimension \| Examples \| Purpose \|

| --- \| --- \| --- \|

| Origin device \| OpenCollar SP051583 / physical EUI \| Identifies the
  hardware that generated the record. \|

| Acquisition channel \| LoRaWAN, WebBLE, raw log file, Iridium \|
  Describes the route from device to upstream system/user. \|

| External platform \| KPN, LORIOT, ChirpStack, Cloudloop \| Identifies
  the system managing or relaying connectivity. \|

| Ingestion method \| MQTT, webhook, REST/API, browser sync, file upload
  \| Describes how Smart Parks Protect receives the delivery. \|

## 25.2 Canonical data versus source deliveries

Smart Parks Protect must never delete or collapse raw SourceEvents
merely because they appear to contain the same device record.
Deduplication occurs when constructing the canonical domain
representation. Multiple source deliveries remain linked to one
canonical record.

    OpenCollar creates one GNSS record
                |
          +-----+------+----------------+
          |            |                |
       LoRaWAN       WebBLE          raw log file
          |            |                |
     KPN/LORIOT      browser          upload
          |            |                |
          +------------+----------------+
                       |
                  SourceEvents
              (all retained)
                       |
              canonicalization
                       |
                  ONE Position
                       |
           map / chart / rules
              show it once

## 25.3 Deduplication identity and timestamp semantics

No additional record identifier should be added to the OpenCollar radio
protocol solely for Smart Parks Protect deduplication because the
protocol overhead is undesirable. For OpenCollar, the preferred
deduplication identity is the physical device EUI together with the
semantically correct device-origin timestamp, normally supplemented by
record/message type and, where needed, an internally calculated stable
payload fingerprint.

    Preferred canonical key:
      device_eui
      + canonical_device_timestamp
      + record_type
      [+ stable payload fingerprint when required]

    Never substitute:
      LoRaWAN Network Server receive time
      gateway receive time
      Cloudloop delivery/session time
      browser BLE sync time
      Smart Parks Protect ingest time
      file upload time

Timestamp semantics must be defined explicitly per Device Driver and
record type. In particular, an OpenCollar log record transported inside
a later LoRaWAN uplink can contain its original device timestamp deeper
in the decoded log structure. That embedded timestamp is the canonical
time for deduplication and temporal/scientific interpretation; the
LoRaWAN Network Server timestamp only describes delivery.

| Timestamp \| Meaning \| Deduplication \|

| --- \| --- \| --- \|

| device_timestamp \| Time the OpenCollar device generated/stored the
  underlying record. \| YES - preferred \|

| network_received_at \| Time KPN/LORIOT/ChirpStack received a LoRaWAN
  packet. \| No; provenance only \|

| satellite_session/delivery time \| Time Iridium/Cloudloop handled or
  delivered a satellite message. \| No; provenance only \|

| ble_synced_at \| Time a browser retrieved stored data through WebBLE.
  \| No; provenance only \|

| ingested_at \| Time Smart Parks Protect accepted the delivery. \| No;
  latency only \|

| file_uploaded_at \| Time a user uploaded a raw log file. \| No; file
  management only \|

## 25.4 WebBLE as a first-class OpenCollar connectivity path

WebBLE should be integrated into the Smart Parks Protect frontend for
supported OpenCollar devices. The browser communicates locally with the
nearby device and then synchronizes data/state to the backend. The
existing public Smart Parks OpenCollar WebBLE application should be
evaluated as the implementation basis so proven BLE protocol, settings
and control logic can be reused.

    OpenCollar device
          |
       WebBLE
          |
    Smart Parks Protect browser
          |
          +-- read/write settings
          +-- device status
          +-- control actions
          +-- retrieve stored logs/data
          +-- future DFU workflows where appropriate
          |
     HTTPS/API
          |
    Smart Parks Protect backend

## 25.5 Device Control may select LoRaWAN, WebBLE or satellite routes

The semantic Device Control action remains owned by the OpenCollar
Device Driver. The execution route is selected separately according to
active connectivity and DataSource capabilities. For example, RESET or
REQUEST_LOCATION may be possible through WebBLE when the device is
nearby, via a LoRaWAN provider when remote, or through an Iridium route
when the device/protocol supports the corresponding satellite command.

## 25.6 Raw OpenCollar log files are managed assets

Raw log files must be treated as managed device assets rather than
temporary upload inputs. Users should be able to upload a file
previously retrieved to a phone/computer, associate it with the correct
Device, inspect processing status, re-decode it after decoder updates,
download the original, and see how many records were new versus already
known through another path.

| DeviceLogFile capability \| Purpose \|

| --- \| --- \|

| device_id / EUI \| Association with the physical OpenCollar device. \|

| original filename + SHA-256 \| File identity and exact-file duplicate
  detection. \|

| log period \| Earliest/latest canonical device timestamp found. \|

| firmware + decoder version \| Reproducible decoding and re-processing.
  \|

| parse status \| Queued, processing, complete, failed. \|

| record counts \| Found, new canonical, duplicates, malformed. \|

| storage reference \| Pointer to S3-compatible/MinIO object storage. \|

This makes S3-compatible object storage, including the MinIO
infrastructure already present in AddaxAI Connect, useful for Smart
Parks Protect even though normalized telemetry itself belongs in
PostgreSQL/time-series storage.

## 25.7 Canonical presentation and raw provenance

Maps, normal charts, dashboards, standard exports and domain Rules must
operate on canonical Positions/Measurements so that the same GPS fix or
sensor record is shown and evaluated once. Technical analysis must still
allow the user to inspect all underlying SourceEvents and filter by
acquisition channel.

## 25.8 Late/offloaded historical data and rule freshness

WebBLE offload or a raw-log upload can introduce genuinely new
historical records long after they occurred. Rules may evaluate those
records for scientific completeness, but Automations must understand
event age and ingestion latency so that historical backfill does not
accidentally generate stale operational alerts.

## 25.9 Iridium satellite connectivity through Cloudloop

Iridium is an explicit supported connectivity family. The initial
platform is Cloudloop (Ground Control). Cloudloop provides an API-first
platform for Iridium data, supports inbound message delivery and
programmatic outbound SBD/MT messages, and exposes device/Thing
management capabilities. Smart Parks Protect should therefore implement
Cloudloop as an adapter with Event Connector, Command Connector and
optional Management Connector responsibilities.

| Cloudloop capability \| Smart Parks Protect mapping \|

| --- \| --- \|

| Inbound Iridium messages \| SourceEvent ingestion with
  Cloudloop/Iridium provenance metadata. \|

| Outbound SBD/MT messages \| Device Control route where supported by
  the OpenCollar device/protocol. \|

| Thing/subscriber management API \| ExternalIdentity and optional
  management synchronization. \|

| Push/pull delivery methods \| Adapter transport can follow the
  selected Cloudloop delivery configuration. \|

| Thing identifier / Iridium IMEI \| External identities linked to the
  same physical Device. \|

| External management UI \| Provide an Open in Cloudloop deeplink where
  feasible. \|

Cloudloop's satellite session/delivery timestamps must remain separate
from the OpenCollar device-origin timestamp used for canonical
deduplication whenever the payload contains the original record
timestamp. The multi-path model intentionally allows the same canonical
record to have LoRaWAN, WebBLE, raw-log and Iridium deliveries.

# 26. Observability, error handling and end-to-end traceability

Error handling and traceability are first-class product capabilities.
Smart Parks Protect should make the processing flow understandable from
the frontend for administrators while keeping the authoritative
processing state, structured errors and technical telemetry in backend
services. The objective is that an administrator can quickly determine
where a data item, command, import or integration failed without
requiring shell access, Docker logs or developer intervention for
routine diagnosis.

## 26.1 Uniform processing trace model

Every significant processing flow should receive a trace/correlation
identifier. Backend components append structured ProcessingSteps to that
trace. The same model should be used for inbound telemetry, WebBLE
synchronization, raw-log imports, device commands, rules, integrations
and large export jobs.

    Example inbound flow

    SourceEvent received
            |
    Connectivity Adapter
            |
    Device Driver / decoder
            |
    Timestamp semantics resolved
            |
    Canonicalization / deduplication
            |
    Position / Measurement created
            |
    Rule evaluation
            |
    Event / Automation
            |
    EarthRanger delivery

| ProcessingStep field \| Purpose \|

| --- \| --- \|

| trace_id \| Correlation identifier shared by all processing steps. \|

| component/service \| API, ingest, adapter, decoder, rules,
  integration, export, etc. \|

| operation \| Human-readable/structured processing operation. \|

| started_at / completed_at \| Timing and performance diagnostics. \|

| status \| PENDING, PROCESSING, SUCCESS, SKIPPED, DUPLICATE, RETRYING,
  FAILED or DEAD_LETTER. \|

| input_reference / output_reference \| Links between SourceEvent,
  canonical data, Event, Command, delivery, etc. \|

| error_reference \| Structured ApplicationError when the step fails. \|

| retry_count \| Number of automatic/manual retries. \|

| duration_ms \| Performance/latency analysis. \|

| metadata \| Limited structured context required to understand the
  step. \|

## 26.2 Frontend System Health

Administrators should have a System Health view summarizing the state of
major application pipelines rather than only infrastructure processes.
It should highlight degraded components and provide drill-down into
affected traces.

| Area \| Example health indicators \|

| --- \| --- \|

| Ingestion \| Events/minute, rejected messages, source connectivity,
  ingest latency. \|

| Decoding/canonicalization \| Decode failures, timestamp errors,
  duplicate rate, unknown devices. \|

| Rules/automation \| Evaluation failures, processing backlog, action
  failures. \|

| Integrations \| EarthRanger/AddaxAI/webhook delivery failures, retries
  and backlog. \|

| Device Control \| Queued commands, provider rejection, expired
  commands, confirmation latency. \|

| File processing \| Raw-log imports queued/failed, malformed records,
  processing duration. \|

| Exports \| Queued/running/failed jobs and generation duration. \|

## 26.3 Processing Trace Explorer

A dedicated Trace Explorer should allow administrators to search
processing history by Device, Entity, EUI, trace ID, DataSource,
acquisition channel, time range, event type, status and error code.
Opening a trace should show a visual timeline/flow with expandable
technical details.

    SP051583 / Trace 8f3...
    --------------------------------
    OK  KPN uplink received
    OK  SourceEvent stored
    OK  OpenCollar driver selected
    OK  device_timestamp extracted
    OK  canonical key calculated
    DUP Duplicate canonical record detected
    OK  linked to existing Position
    SKIP rule evaluation (already evaluated)
    OK  processing complete

## 26.4 Object-level provenance and trace drill-down

Traceability must be reachable from normal application objects. A
Position, Measurement, Event, Alert, DeviceLogFile, Command or
IntegrationDelivery should expose a 'View processing trace' action where
relevant. For canonical data, the trace/provenance view should also show
all source deliveries, such as LoRaWAN/KPN, WebBLE, raw-log upload or
Cloudloop/Iridium.

## 26.5 Structured application error taxonomy

Application errors should use stable error codes and structured
attributes rather than relying on free-text log messages. Each error
should indicate severity, whether it is retryable, whether an
administrator can resolve it, the responsible component and relevant
context.

    Example error codes

    CONNECTIVITY_AUTH_FAILED
    CONNECTIVITY_UNAVAILABLE
    DEVICE_NOT_FOUND
    DEVICE_IDENTITY_AMBIGUOUS
    PAYLOAD_DECODE_FAILED
    TIMESTAMP_INVALID
    CANONICALIZATION_FAILED
    RULE_EVALUATION_FAILED
    INTEGRATION_DELIVERY_FAILED
    COMMAND_REJECTED
    COMMAND_EXPIRED
    FILE_PARSE_FAILED
    EXPORT_FAILED

The frontend can use these codes to offer contextual remediation
actions. For example, an unknown EUI can offer 'Create device' or 'Link
to existing device'; expired provider credentials can link to the
DataSource configuration; a failed integration delivery can offer Retry.

## 26.6 Needs Attention and dead-letter workflow

Failed items that cannot be resolved automatically should enter a
visible Needs Attention/dead-letter workflow. Administrators should be
able to Retry, Reprocess, Reassign, Ignore or Resolve an item according
to its error type, with all manual actions recorded in the audit trail.

    Needs Attention
    ------------------------------
    12 failed decodes
     3 unknown devices
     2 EarthRanger delivery failures
     1 malformed raw-log file

## 26.7 Device Control uses the same trace model

Outbound commands should use the same traceability infrastructure as
inbound data. The frontend should show the semantic action, driver
encoding, selected connectivity route, external platform response and
any subsequent device confirmation without inventing lifecycle stages
that the provider cannot observe.

    RESET DEVICE
        |
    OpenCollar action encoding
        |
    LoRaWAN route selected
        |
    KPN/ThingPark adapter
        |
    accepted by external platform
        |
    queued / transmitted (if exposed)
        |
    device response (if available)

## 26.8 Application traces versus technical observability

Smart Parks Protect should distinguish administrator-facing process
traces from low-level developer telemetry. Application traces explain
what happened in domain language. Technical logs, metrics and
distributed traces provide deeper implementation diagnostics.
OpenTelemetry should be evaluated as the standard technical
instrumentation layer across services, with correlation IDs linking
technical telemetry back to Smart Parks ProcessingTrace records.

| Layer \| Audience and purpose \|

| --- \| --- \|

| Application trace \| Administrator/operations: understandable
  processing state, provenance, errors, retries and remediation. \|

| Technical distributed trace \| Developer/operator: service-to-service
  spans, timings and dependency diagnostics. \|

| Metrics \| Health, throughput, queue depth, latency and error-rate
  monitoring. \|

| Technical logs \| Detailed service diagnostics and stack/error
  context. \|

The Smart Parks frontend should not simply expose raw OpenTelemetry or
container logs as its primary admin interface. It should present
structured domain-level information first, with optional technical
details or links for deeper diagnosis.

## 26.9 Trace retention and scalability

Observability must not create more persistent data than the telemetry
platform itself. Successful high-volume sensor flows should therefore
use compact trace records, while errors, retries, commands and
audit-sensitive operations retain more detail.

| Trace class \| Suggested initial retention strategy \|

| --- \| --- \|

| Successful routine telemetry \| Compact processing trace;
  approximately 7-30 days online. \|

| Failed/retried/dead-letter flows \| Detailed application trace;
  approximately 90-365 days. \|

| Device commands/control \| Longer audit-oriented retention according
  to project policy. \|

| Administrative/audit actions \| Long-term retention according to
  security/project requirements. \|

| Detailed technical OpenTelemetry spans \| Shorter operational
  retention; configurable by deployment. \|

Exact retention values should be configurable, but the data model should
support different policies from the first implementation.

## 26.10 Core backend objects

    ProcessingTrace
      trace_id
      root_object_type
      root_object_id
      status
      started_at
      completed_at

    ProcessingStep
      trace_id
      sequence
      component
      operation
      status
      input_ref
      output_ref
      timing
      error_ref
      metadata

    ApplicationError
      error_code
      severity
      retryable
      user_actionable
      component
      message
      technical_context

## 26.11 MVP requirements

-   Introduce correlation/trace IDs and the
    ProcessingTrace/ProcessingStep contract before multiple adapters and
    workers are implemented.

-   Provide a basic administrator System Health screen.

-   Provide a searchable Trace Explorer with drill-down for failed and
    duplicate messages.

-   Expose trace/provenance links from at least Positions, SourceEvents,
    Commands and IntegrationDeliveries.

-   Implement a stable initial ApplicationError taxonomy and
    retry/dead-letter workflow.

-   Instrument core backend services with consistent structured logging
    and evaluate OpenTelemetry for distributed traces/metrics.

-   Ensure routine successful telemetry tracing remains compact enough
    for the platform's target data volumes.

# 27. AI and agent integration through MCP

Smart Parks Protect should be designed to expose selected platform
capabilities safely to modern AI assistants and autonomous/agentic
clients. The recommended integration standard is the Model Context
Protocol (MCP), implemented as a separate Smart Parks Protect MCP Server
above the normal application/service API. MCP is not a replacement for
the REST/application API; it is an AI-oriented interoperability layer
that exposes carefully designed Smart Parks resources and tools.

## 27.1 Architectural position of MCP

The MCP Server must not connect directly to database tables. It should
use the same authenticated Smart Parks service/API layer as the frontend
and other integrations. This preserves one authorization model, one
domain model, one audit trail and one set of business rules.

    AI clients
      ChatGPT
      Claude
      other MCP-compatible clients
               |
               | MCP + OAuth
               v
    Smart Parks Protect MCP Server
               |
      authorization / scopes
      rate limits
      AI action policy
      audit + ProcessingTrace
               |
               v
    Smart Parks Service / API Layer
               |
       +-------+--------+---------+
       |       |        |         |
    Entities Analytics Rules   Device Control
               |
               v
    Canonical Smart Parks data

## 27.2 MCP resources

Resources are suitable for bounded contextual objects that an AI client
may inspect. Large time-series datasets should not be exposed as
unbounded resources.

    Example resources

    smartparks://projects/{project_id}
    smartparks://entities/{entity_id}
    smartparks://devices/{device_id}
    smartparks://events/{event_id}
    smartparks://rules/{rule_id}
    smartparks://datasources/{source_id}
    smartparks://traces/{trace_id}

## 27.3 MCP read and analysis tools

The first MCP implementation should focus primarily on read and analysis
tools. Tools should express Smart Parks capabilities rather than generic
SQL or raw backend operations.

| Tool \| Purpose \|

| --- \| --- \|

| list_projects \| List projects accessible to the authenticated user.
  \|

| search_entities \| Find animals, people, vehicles, gates, traps and
  other entities. \|

| get_entity \| Return entity metadata, current state and current device
  assignment. \|

| search_devices \| Find devices by name, EUI, type, project or status.
  \|

| get_device \| Return device details, assignments, capabilities and
  provenance. \|

| get_device_health \| Return current device and connectivity health. \|

| get_latest_position \| Return the latest canonical position. \|

| get_track \| Return a bounded/simplified historical track. \|

| query_measurements \| Query normalized sensor/time-series data with
  server-side aggregation. \|

| query_events \| Search domain events. \|

| get_alerts \| Return active or historical alerts. \|

| get_processing_trace \| Explain how data or an action flowed through
  Smart Parks Protect. \|

| get_data_sources \| Inspect KPN, LORIOT, ChirpStack, Cloudloop,
  Traccar and other configured sources. \|

| create_export \| Create a controlled export for data volumes
  unsuitable for direct AI retrieval. \|

## 27.4 Controlled write and action tools

Write actions should be introduced gradually and classified by impact.
The same Device Control, Rules and Integration frameworks used by human
users must be reused by MCP tools; MCP must not create alternative
control paths.

| Class \| Examples \| Recommended policy \|

| --- \| --- \| --- \|

| Read \| Search entities, query measurements, read events \| Allowed
  according to normal RBAC. \|

| Analysis \| Run aggregate queries, inspect traces, test a rule \|
  Allowed with query limits and normal RBAC. \|

| Safe write \| Create event, acknowledge alert \| Permission-gated;
  confirmation may be required. \|

| Operational control \| Request status, request device location \|
  Explicit device-control scope and confirmation. \|

| High-impact control \| Reset, configuration changes \| Privileged
  scope plus explicit confirmation. \|

| Safety-critical/irreversible \| Actions such as physical drop-off
  where applicable \| Do not expose through general AI tooling unless a
  separate safety design explicitly approves it. \|

## 27.5 Authentication, OAuth and RBAC

AI access must represent an authenticated Smart Parks Protect user or
explicitly configured service identity. MCP must reuse project
permissions and RBAC; it must never grant broad administrator access
merely because the client is ChatGPT, Claude or another AI host. A
remote MCP deployment should use OAuth/OIDC-compatible authorization
with scoped tokens.

    Illustrative scopes

    projects:read
    entities:read
    devices:read
    measurements:read
    events:read
    traces:read

    alerts:write
    events:write
    rules:test

    devices:control
    rules:write

    admin

## 27.6 AI Action Policy

In addition to normal RBAC, Smart Parks Protect should implement an
AI-specific action policy. This allows organizations to decide which
tool classes are available to AI clients and which require explicit
confirmation even when the underlying user has permission.

    Example policy

    READ                         allowed
    ANALYTICS                    allowed
    CREATE EVENT                 confirmation
    ACKNOWLEDGE ALERT            confirmation
    REQUEST DEVICE LOCATION      confirmation
    RESET DEVICE                 privileged + confirmation
    CHANGE CONFIGURATION         privileged + confirmation
    SAFETY-CRITICAL ACTION       disabled by default

## 27.7 Query limits and AI-safe data access

MCP must use the same scalability and Level-of-Detail principles as the
Smart Parks analytics and map APIs. An AI client must not be allowed to
request millions of raw rows in one tool call. Large requests should be
aggregated, paginated, simplified or converted into an export job.

| Data type \| Recommended behavior \|

| --- \| --- \|

| Measurements \| Server-side aggregation and bounded result sets,
  typically thousands rather than millions of points. \|

| Tracks \| Time/viewport filtering plus simplification/level of detail.
  \|

| Events \| Pagination, filtering and explicit maximum result counts. \|

| Raw/source records \| Restricted diagnostic access and pagination. \|

| Large datasets \| Use create_export and return a managed file/resource
  instead of full inline payload. \|

## 27.8 Provenance and traceability through MCP

MCP should expose the provenance and ProcessingTrace capabilities
already defined for the frontend. This allows an AI assistant to answer
questions such as where a GPS point originated, whether the same
OpenCollar record was received through KPN and WebBLE, why an
EarthRanger delivery failed, or where a device-data flow stopped.

    Example AI troubleshooting flow

    User:
      "Why has SP051583 stopped updating?"

    AI tools:
      get_device_health
      get_recent_source_events
      get_processing_trace
      get_data_sources

    Possible answer:
      "The device is still transmitting. KPN delivered three
       recent uplinks, but two failed during OpenCollar decoding
       with PAYLOAD_DECODE_FAILED on the same message type."

## 27.9 MCP prompts / guided workflows

Reusable MCP prompts can provide consistent guided AI workflows without
hard-coding those workflows into a specific AI vendor. Examples include
device-health investigation, missing-data diagnosis, animal-movement
analysis, network-quality review and rule review.

    Example guided workflows

    analyze-device-health
    investigate-missing-data
    analyze-animal-movement
    analyze-network-quality
    review-rule

## 27.10 MCP as a separate service

The MCP endpoint should be implemented as a separate service or clearly
isolated module so it can be enabled, disabled, updated, scaled and
audited independently from the core API. The service should expose
stable domain-level tools while relying on internal service/API
contracts for execution.

    services/
      api/
      frontend/
      ingest/
      decoder/
      rules/
      automation/
      integration/
      export/
      mcp/

## 27.11 Audit and ProcessingTrace integration

Every MCP tool invocation that reads sensitive information or performs
an action should be auditable. Write/control actions should create
normal ProcessingTrace records and indicate that the initiating actor
was an MCP/AI client while retaining the authenticated Smart Parks user
identity.

    Actor
      user: <Smart Parks user>
      client_type: MCP
      client_name: ChatGPT / Claude / other
      tool: request_device_position
      trace_id: ...
      result: submitted via KPN adapter

## 27.12 ChatGPT, Claude and future AI clients

The MCP contract should remain vendor-neutral. ChatGPT and Claude are
important initial targets, but the platform should not contain
client-specific logic in core domain services. Where a vendor later
supports richer UI/app experiences on top of MCP, those can be added
without changing the underlying Smart Parks tools and resources.

## 27.13 Initial MCP proof of concept

The first MCP proof of concept should remain deliberately small and
read-focused. Its purpose is to validate authentication, tool schemas,
permissions, traceability and interoperability with multiple AI clients.

-   search_entities

-   get_entity

-   get_device

-   get_latest_position

-   query_measurements

-   query_events

-   get_processing_trace

After this works with at least ChatGPT and Claude, controlled
write/actions can be introduced incrementally, starting with low-impact
functions such as acknowledge_alert or request_device_status.

# 28. Documentation, developer experience and open-source maintainability

Documentation quality is a first-class product and engineering
requirement for Smart Parks Protect. The project should aim for the same
practical strength that makes AddaxAI Connect approachable: a new
developer or operator should be able to understand the purpose of the
platform, start a local instance, configure integrations, troubleshoot
common failures and extend the system without reverse-engineering the
codebase. Documentation should be maintained as code in the repository
and evolve in the same pull requests as the functionality it describes.

## 28.1 Documentation layers

| Layer \| Required content \|

| --- \| --- \|

| Repository / getting started \| README, project purpose,
  screenshots/architecture overview, prerequisites, quick start, Docker
  deployment, configuration, environment variables, development setup
  and common troubleshooting. \|

| Architecture \| System context, services, data model, processing
  flows, provenance, canonicalization/deduplication, scalability,
  security, observability and Architecture Decision Records. \|

| Developer / integration \| REST/OpenAPI, MCP, Device Driver interface,
  Connectivity Adapter interface, Integration Connectors, Rules/Actions,
  webhooks, decoder development, test fixtures and example payloads. \|

| User / administrator \| Projects, entities, devices, DataSources, map,
  Data Explorer, dashboards, Rules, exports, Device Control, WebBLE, raw
  logs, System Health, Trace Explorer and permissions. \|

| Operations \| Installation, backups, upgrades, migrations, monitoring,
  retention, object storage, scaling, recovery and incident
  troubleshooting. \|

## 28.2 Documentation-as-code repository structure

    /
    ├── README.md
    ├── CONTRIBUTING.md
    ├── CHANGELOG.md
    ├── LICENSE
    ├── SECURITY.md
    ├── CODE_OF_CONDUCT.md
    │
    ├── docs/
    │   ├── getting-started/
    │   ├── architecture/
    │   ├── concepts/
    │   ├── devices/
    │   ├── integrations/
    │   ├── analytics/
    │   ├── rules/
    │   ├── administration/
    │   ├── operations/
    │   ├── troubleshooting/
    │   ├── api/
    │   ├── mcp/
    │   └── adr/
    │
    ├── examples/
    │   ├── payloads/
    │   ├── adapters/
    │   ├── device-drivers/
    │   └── integrations/
    └── ...

The exact static documentation generator can be selected during
implementation. The important architectural requirement is that the
canonical documentation lives in version control alongside the code and
can be built into a searchable documentation site.

## 28.3 README and first-run experience

The root README should remain concise but complete enough to answer what
Smart Parks Protect is, what problems it solves, its major architectural
concepts and how to run a working development instance. A developer
should not need undocumented tribal knowledge to reach a functional
local environment.

-   Product overview and core use cases.

-   High-level architecture diagram.

-   Supported connectivity/integration examples.

-   Prerequisites and one clear recommended quick-start path.

-   Local development and Docker/container startup.

-   Configuration/environment variable reference or link.

-   Links to architecture, API, MCP and extension documentation.

-   Known limitations and project maturity/status.

## 28.4 Architecture Decision Records

Significant technical decisions should be captured as short Architecture
Decision Records (ADRs). This is particularly important for an
open-source platform that may have multiple contributors and long-lived
integrations. ADRs explain not only what was chosen but why, which
alternatives were considered and what consequences follow.

    docs/adr/
      0001-canonical-domain-model.md
      0002-connectivity-adapter-boundary.md
      0003-device-timestamp-deduplication.md
      0004-postgis-and-timeseries-strategy.md
      0005-processing-trace-model.md
      0006-mcp-security-boundary.md

## 28.5 Extension documentation is mandatory

A key documentation goal is that an external developer can build a new
Device Driver, Connectivity Adapter or Integration Connector from
published contracts and examples. Extension documentation must therefore
describe lifecycle, interfaces, schemas, capability negotiation, error
handling, timestamp semantics, provenance requirements, testing and
registration/discovery.

| Extension type \| Documentation must include \|

| --- \| --- \|

| Device Driver \| Message decoding, canonical fields, timestamp
  semantics, control actions, capabilities, examples and tests. \|

| Connectivity Adapter \| Authentication, inbound/outbound transports,
  external identities, source links, provider timestamps, gateway
  support, retry/error behavior. \|

| Integration Connector \| Inbound/outbound event mapping, idempotency,
  filters, credentials, retry behavior and provenance. \|

| Rule Action / condition \| Input schema, evaluation semantics, side
  effects, permissions and examples. \|

| MCP tool/resource \| Schema, authorization scope, limits, side
  effects, confirmation policy and examples. \|

## 28.6 API and schema documentation

Machine-facing contracts should generate documentation wherever
practical. REST endpoints should expose OpenAPI documentation; MCP
tools/resources should have explicit schemas and descriptions;
event/webhook schemas should be versioned; and example
requests/responses should be maintained for important integration paths.

Generated reference documentation should complement, not replace,
conceptual guides. A list of endpoints is insufficient to explain how an
OpenCollar record becomes a canonical Position or how to implement a
safe downlink adapter.

## 28.7 Integration runbooks and troubleshooting

Every production-grade external integration should include an
operator-oriented runbook. This should cover setup, credentials,
expected data flow, health checks, common errors, retry/recovery
procedures and how to use the Smart Parks Trace Explorer to locate
failures.

    Example integration documentation set

    KPN / ThingPark
      setup.md
      authentication.md
      uplink-flow.md
      downlink-flow.md
      timestamps.md
      troubleshooting.md
      example-payloads/

    Cloudloop / Iridium
      setup.md
      inbound-sbd.md
      outbound-mt.md
      identity-mapping.md
      timestamps.md
      troubleshooting.md

## 28.8 Documentation and CI

Documentation should be validated in continuous integration so that
obvious breakage is caught before merge. The exact tooling can be
selected later, but the CI design should support documentation builds
and automated quality checks.

-   Build the documentation site on pull requests.

-   Check internal links and references.

-   Validate OpenAPI/schema generation.

-   Validate Mermaid/diagram syntax where tooling supports it.

-   Check code/config examples that can reasonably be tested.

-   Prevent generated API/MCP reference documentation from silently
    becoming stale.

## 28.9 Versioning, migrations and release documentation

Releases should have a maintained CHANGELOG and clear upgrade/migration
notes. Breaking API, adapter, schema, Device Driver or MCP changes must
be called out explicitly. Database migrations and configuration changes
should include operator guidance and rollback considerations where
practical.

## 28.10 Documentation Definition of Done

A feature is not complete until its relevant documentation is complete.
This requirement should be part of pull-request review and the project
Definition of Done.

| Change type \| Documentation Definition of Done \|

| --- \| --- \|

| New feature \| User/admin behavior documented; screenshots/examples
  where useful; architecture updated if boundaries change. \|

| New adapter/integration \| Setup, credentials, mappings, timestamps,
  provenance, errors, retry behavior and example payloads documented. \|

| New OpenCollar message/decoder behavior \| Payload semantics,
  canonical mapping, device timestamp semantics and deduplication
  implications documented. \|

| New Device Control action \| Parameters, capabilities, encoding
  ownership, supported routes, permissions and lifecycle documented. \|

| New MCP tool \| Tool schema, scopes, limits, side effects,
  confirmation requirements and example invocation documented. \|

| Breaking change \| Migration/upgrade notes and changelog entry
  required. \|

| Bug fix with operational relevance \| Troubleshooting/runbook updated
  when the failure mode is useful to future operators. \|

## 28.11 Documentation ownership and review

Documentation should have clear ownership but remain the responsibility
of all contributors. Pull-request templates should prompt authors to
state whether documentation is required and where it was updated. Core
architectural and integration documentation should receive the same
review attention as implementation code.

## 28.12 Initial implementation requirements

-   Create the documentation directory structure and root
    contributor/security/release files at repository creation time.

-   Publish a strong README and reproducible quick-start before the
    first external developer handoff.

-   Create initial architecture diagrams and ADRs for the core domain
    model, adapter boundaries, timestamp/deduplication model and
    observability model.

-   Generate OpenAPI documentation from the backend API.

-   Document the first OpenCollar Device Driver and at least one LoRaWAN
    Connectivity Adapter as reference implementations.

-   Document the MCP proof of concept with authentication, tool schemas
    and examples.

-   Include documentation checks in CI from the early development phase.

## Additional outbound wildlife data platforms

The outbound Integration Connector framework should explicitly include
WildlifeNL, FerusTracker and Movebank as target platforms in addition to
EarthRanger. These integrations should consume the same canonical Smart
Parks domain data and use the common delivery, retry, audit and
traceability framework.

-   WildlifeNL data platform --- configurable outbound connector for
    relevant wildlife positions, observations and associated metadata.
    Exact API, authentication and target data mappings should be
    confirmed during the integration spike.

-   FerusTracker --- configurable outbound connector for relevant
    tracking and monitoring data. The connector should preserve Smart
    Parks provenance and expose delivery status and traceability; exact
    supported API operations should be confirmed during implementation.

-   Movebank --- outbound connector for animal tracking data, with
    explicit mapping of Entity/animal identity, Device assignment
    periods, timestamps, locations and applicable sensor attributes to
    the Movebank data model.

All outbound connectors should support idempotent delivery where the
target permits it, retry/backoff, structured IntegrationDelivery status,
ProcessingTrace integration, isolated credentials, project-level
enable/disable configuration and explicit source-to-target identity
mappings. Projects must be able to filter which entities, devices,
event/observation types, measurements and historical/backfilled records
are forwarded.

Each Integration Connector owns the translation from canonical Smart
Parks objects to its target platform. Smart Parks Protect must retain
enough delivery metadata for an administrator to determine what was
sent, when it was sent, which external project/object it mapped to, the
response from the target platform and whether delivery ultimately
succeeded.

## Notification channels: email and Telegram

Smart Parks Protect should retain and generalize the notification
capabilities already familiar from AddaxAI Connect. Email and Telegram
must be supported as first-class notification channels in the Rules &
Automation framework, rather than implemented as one-off integrations.

-   Email notifications --- SMTP-based delivery with configurable sender
    identity, recipients, subject/body templates, severity-aware
    formatting and links back to the relevant Smart Parks Protect
    object.

-   Telegram notifications --- configurable bot/chat targets with
    concise event/alert formatting and links back to Smart Parks Protect
    where appropriate.

-   Notifications should be selectable as Actions for Rules, Events,
    Alerts, Device/Network health conditions, integration failures,
    command failures and other automation triggers.

-   Project-level and organization-level notification targets should be
    supported so different projects can route alerts to different teams.

-   Notification actions must use the common ProcessingTrace /
    Automation / Action execution model, including delivery status,
    retries, failures and audit history.

The notification abstraction should remain channel-neutral so additional
channels can be added later without changing the Rule Engine. A rule
should express the intent to notify a configured target, while the
notification service handles channel-specific delivery.

    Conceptual model:

    Rule / Event / Alert
            ↓
    Automation
            ↓
    Notification Action
            ↓
    Notification Target
       ├── Email
       └── Telegram

    Each delivery records:
    - status
    - attempted_at
    - delivered_at
    - retry_count
    - error details
    - related ProcessingTrace

# 28. Device onboarding, project assignment and data ownership

Smart Parks Protect must explicitly resolve which project owns incoming
data, because upstream platforms may know only their own device
identifiers and may push data without any knowledge of the Smart Parks
project structure. Device identity resolution and project attribution
are therefore core platform functions, not assumptions delegated to
LoRaWAN, satellite, tracking or other external providers.

## 28.1 DataSources are independent from project ownership

A DataSource represents an external platform/account/integration such as
KPN, LORIOT, ChirpStack, The Things Network, Cloudloop or Traccar. A
DataSource may serve one project or many projects. Project ownership
must therefore not be inferred merely from the DataSource unless an
administrator has explicitly configured such a mapping.

## 28.2 Devices are server-level physical objects

A physical Device should exist independently of a Project. The same
OpenCollar, camera, tracker, gateway-connected sensor or other device
may be deployed in different projects during its lifetime. The Device
record therefore represents persistent hardware identity; project
membership is a separate time-bounded relationship.

## 28.3 Time-bounded DeviceProjectAssignment

Project membership must be represented by a historical
assignment/deployment record rather than a mutable device.project_id
field. Moving a device to another project closes the previous assignment
and creates a new assignment. Historical data remains attributed to the
project that owned the device at the time the underlying record was
generated.

| Field \| Purpose \|

| --- \| --- \|

| device_id \| Physical device. \|

| project_id \| Smart Parks project responsible for the deployment. \|

| valid_from \| Effective assignment start. \|

| valid_to \| Effective assignment end; null while current. \|

| reason / deployment reference \| Optional deployment/handover context.
  \|

| created_by / changed_by \| Auditability of administrative assignment.
  \|

## 28.4 Device-to-Entity assignment remains separate

DeviceProjectAssignment and DeviceEntityAssignment are separate
concepts. A device can remain within one project while being moved from
one animal, vehicle or other Entity to another. Conversely, a device may
move between projects. Both relationships require effective dates so
historical telemetry can be interpreted correctly.

## 28.5 ExternalIdentity resolves pushed data to a Device

Incoming data should be resolved using the combination of DataSource and
an external identifier. ExternalIdentity links provider-specific
identifiers such as LoRaWAN DevEUI, Cloudloop Thing/Iridium IMEI or
Traccar device ID to the persistent Smart Parks Device. This prevents
provider-specific identifiers from becoming the core domain model.

    Resolution flow:
    DataSource + external identifier
            -> ExternalIdentity
            -> Device
            -> canonical device timestamp
            -> DeviceProjectAssignment valid at that time
            -> Project
            -> optional DeviceEntityAssignment valid at that time
            -> Entity

## 28.6 Unknown devices and unassigned incoming data

Incoming SourceEvents must be retained even when Smart Parks Protect
cannot yet resolve the device or project. Unknown identities should
enter an Unassigned Data / Needs Attention workflow instead of being
discarded or guessed. Once an administrator creates or links the Device
and assigns the appropriate project, retained SourceEvents can be
reprocessed.

The administrator interface should show the DataSource, external
identifier, first/last seen time, message count and any device-type
inference, with actions such as Create device, Link to existing device,
Assign project, Ignore and Reprocess.

## 28.7 Device discovery and bulk onboarding

Where an external platform exposes a management API, a Connectivity
Adapter may discover/list external devices and present them for mapping.
Push-only integrations must remain fully supported. Bulk CSV import
should also be available for deployments containing many known devices.

    Example bulk import fields:
    device_name
    external_identifier / dev_eui
    device_type
    datasource
    project
    effective_from
    optional entity

## 28.8 Optional DataSource and external-group project mappings

A DataSource may optionally be scoped to one or more Projects. Adapters
may also expose external application/group/tenant identifiers that
administrators can map to Smart Parks Projects. These mappings can
provide suggested or, when explicitly enabled, automatic project
assignment for controlled deployments. They are configuration aids
rather than core assumptions.

## 28.9 Project attribution uses canonical event time

Project attribution must use the canonical device-origin timestamp
defined by the Device Driver, not the current project, server receive
time, WebBLE sync time, file upload time or LoRaWAN Network Server
receive time. This is essential for delayed LoRaWAN logs, WebBLE
offload, raw-log imports and satellite delivery.

    Example:
    Device assigned to Project A until 1 August.
    Device assigned to Project B from 10 August.
    A raw log uploaded on 20 August contains a GPS fix generated on 15 July.

    Result:
    The GPS fix belongs to Project A, because 15 July is the canonical device timestamp.

## 28.10 Explicit project handover workflow

Administrators should use a dedicated Move/Hand over device workflow
rather than editing a project field. The workflow selects the
destination Project and effective time, validates that assignments do
not overlap, closes the previous assignment and creates the new one. The
change is audited and must never rewrite historical project ownership.

## 28.11 Unassigned inventory/workshop periods

A Device may legitimately have no active Project assignment, for example
while in inventory, under repair or being tested. Data generated during
such periods remains unassigned and is visible to appropriately
privileged server administrators until explicitly attributed. This
avoids forcing operational/test data into an unrelated project.

## 28.12 Access control follows historical project attribution

Project users may access canonical records belonging to projects for
which they have permission. After a Device moves from Project A to
Project B, Project A users retain access to Project A historical data
but do not automatically gain access to new Project B telemetry.
Server-level administrators can inspect the full Device lifetime subject
to platform policy.

## 28.13 Recommended admin onboarding flow

    Recommended setup:
    1. Create or select Project.
    2. Configure DataSource and credentials.
    3. Verify inbound/outbound connectivity.
    4. Discover, import or manually register Devices.
    5. Resolve ExternalIdentities.
    6. Assign Devices to Project with an effective start time.
    7. Optionally assign Devices to Entities.
    8. Reprocess any retained unassigned SourceEvents.
    9. Confirm data appears in the correct Project.
    10. Monitor unresolved identities in Needs Attention.

## 28.14 Hard architecture rules

-   Project ownership belongs to a time-bounded DeviceProjectAssignment,
    not permanently to the Device.

-   Incoming SourceEvents are retained when identity or project
    resolution is incomplete.

-   The platform never guesses project ownership from a push-only
    provider unless an administrator has explicitly configured a
    deterministic mapping.

-   Historical data is attributed using canonical device/event time.

-   Moving a Device between Projects never moves or rewrites historical
    canonical records.

-   Device-to-Project and Device-to-Entity assignments are independent
    and historically versioned.

-   All assignment, handover, ignore and reprocessing actions are
    auditable and visible through ProcessingTrace where applicable.

# 28. Backup, disaster recovery and business continuity

Smart Parks Protect must be recoverable from complete server loss from
the first production deployment. The design should inherit the practical
deployment/backup/rebuild philosophy demonstrated by AddaxAI Connect,
including reproducible deployment, PostgreSQL backup and full-server
recovery, but strengthen it for continuously accumulating, high-value
telemetry with automated, provider-independent and testable recovery
mechanisms.

## 28.1 Recovery objective

A completely lost or corrupted Smart Parks Protect server must be
replaceable by a clean compatible server using infrastructure/deployment
automation plus restored persistent data. Recovery must not depend
solely on access to the failed machine or on a cloud-provider VM
snapshot.

## 28.2 What must be protected

| Persistent component \| Recovery requirement \|

| --- \| --- \|

| PostgreSQL/PostGIS/time-series data \| Projects, users/RBAC where
  applicable, Devices, assignments, Entities, SourceEvents/canonical
  data, Events, Rules, traces, integrations and configuration. \|

| Object storage \| Raw OpenCollar logs, uploaded files, exports and
  other persistent binary/object assets. \|

| Application configuration \| Non-secret deployment configuration,
  integration definitions and compatible application versions. \|

| Secrets and credentials \| Encrypted, access-controlled recovery
  mechanism separate from ordinary repository configuration. \|

| Schema/migration state \| Enough version information to restore using
  a compatible application/database schema. \|

| Persistent queue/state \| Back up or make safely reconstructable where
  asynchronous processing cannot be recreated from SourceEvents. \|

| Infrastructure definition \| Docker/container configuration,
  Ansible/deployment automation and documented dependencies. \|

## 28.3 Layered recovery model

    Layer 1 - Data recovery
      PostgreSQL base backups + WAL/PITR
      object storage backup/versioning
      configuration and protected secrets
      encrypted off-server copy

    Layer 2 - Reproducible infrastructure
      Git repository
      Docker/container definitions
      Ansible/deployment automation
      versioned migrations and documentation

    Layer 3 - Infrastructure snapshot
      DigitalOcean/cloud/VM snapshot
      used as an additional fast recovery option
      never the only canonical backup

## 28.4 PostgreSQL backup and point-in-time recovery

Manual pg_dump remains useful before upgrades and for portable logical
backups, as in AddaxAI Connect, but production Smart Parks Protect
should additionally support automated database backups and continuous
WAL archiving so Point-in-Time Recovery (PITR) is possible. This
protects against both server loss and logical incidents such as
accidental deletion or corruption.

## 28.5 Object storage recovery

MinIO/S3-compatible object data must be protected independently from the
database. The preferred design is object versioning and/or incremental
replication/backup to remote S3-compatible storage. Database records
referencing objects should be included in recovery-integrity checks so a
successful database restore cannot silently leave missing raw logs or
uploaded assets.

## 28.6 Off-server and provider-independent backups

A backup stored only on the Smart Parks Protect server does not qualify
as disaster recovery. At least one encrypted backup copy must be stored
off-server and preferably in a failure domain independent of the primary
host. Cloud-provider snapshots such as DigitalOcean Droplet snapshots
are useful as an additional fast-recovery layer, but canonical recovery
should also work on a clean Ubuntu/Linux server at another provider or
on-premise.

## 28.7 Full-server recovery procedure

    Clean replacement server
            |
            v
    Install required runtime / bootstrap
            |
            v
    Deploy Smart Parks Protect using Ansible/container definitions
            |
            v
    Restore secrets and configuration
            |
            v
    Restore PostgreSQL + apply required PITR point
            |
            v
    Restore object storage
            |
            v
    Validate schema, migrations and object references
            |
            v
    Run integrity/application health checks
            |
            v
    Reconnect/enable DataSources
            |
            v
    Resume ingestion and processing

## 28.8 Initial RPO and RTO targets

Recovery targets should be configurable by deployment tier. As a
realistic initial baseline for a normal production Smart Parks Protect
installation, the architecture should aim for an RPO of no more than
approximately one hour and an RTO of no more than approximately four
hours. Higher-availability deployments may choose stricter objectives
through more frequent backups, replication or redundant infrastructure.

| Objective \| Initial baseline \|

| --- \| --- \|

| RPO - Recovery Point Objective \| \<= 1 hour for normal production
  deployments. \|

| RTO - Recovery Time Objective \| \<= 4 hours to restore service on
  replacement infrastructure. \|

| Logical recovery \| PITR should allow recovery to a selected point
  before accidental deletion/corruption. \|

| Provider independence \| Recovery procedure should not require the
  original cloud provider. \|

## 28.9 Backup retention

Retention should be configurable, with an initial policy combining
frequent recent recovery points and longer-lived daily/weekly
generations. Exact values depend on storage cost and project
requirements, but the implementation must support multiple generations
rather than overwriting a single backup.

## 28.10 Automated restore verification

A backup is not considered proven merely because a backup job reports
success. Smart Parks Protect should support scheduled restore
verification in an isolated environment. The verification process should
restore the database and representative object data, start a compatible
application stack and perform integrity/health checks. This is
especially important for long-running wildlife and research datasets
that may be irreplaceable.

## 28.11 Admin frontend: Backup & Recovery health

Backup state should be visible to privileged administrators in the Smart
Parks Protect frontend and integrated with System Health. Administrators
should not need server-shell access to determine whether recent
recoverable backups exist.

    Example Backup & Recovery status

    Database backup        OK - 18 minutes ago
    WAL/PITR archive       Healthy
    Object backup          OK - 31 minutes ago
    Off-server copy        Healthy
    Last restore test      Passed - 12 Aug 2026
    Estimated recovery point < 1 hour
    Recovery target          < 4 hours

## 28.12 Backup alerts and notifications

Backup failures, stale backups, broken WAL archiving, failed off-site
replication and failed restore tests must create system alerts. These
alerts should use the common Rules/Automation and notification framework
so administrators can receive email and Telegram notifications.

## 28.13 Security

Backups can contain sensitive location, operational and credential data
and must therefore be encrypted in transit and at rest. Backup
credentials should use least privilege, restoration access should be
restricted and audited, and secrets should not be committed to the Git
repository or stored unencrypted in ordinary backup archives.

## 28.14 Recovery documentation and runbooks

The repository documentation must include backup configuration, backup
schedules, PITR procedures, object-storage recovery, full clean-server
recovery, credential restoration, integrity validation and
troubleshooting. Recovery instructions must be kept compatible with the
current supported release and should be exercised as part of periodic
restore tests.

## 28.15 Definition of Done for backup/recovery

-   A production deployment is not complete until automated off-server
    backups are configured and visible as healthy.

-   Database recovery must include a tested PITR strategy, not only
    manual pre-upgrade dumps.

-   Object storage must have an independent recovery path.

-   A clean-server rebuild must be documented and reproducible using
    version-controlled deployment automation.

-   Infrastructure snapshots are an additional recovery layer and may
    not be the sole backup mechanism.

-   Restore tests must be performed periodically and their result
    recorded.

-   Backup and restore failures must be observable through System Health
    and notification channels.

-   Changes to persistent schemas, object formats or deployment topology
    must include corresponding backup/recovery documentation updates.

# 28. Data curation, corrections and scientific provenance

Smart Parks Protect must support controlled curation of already
processed data when known data-quality problems can be corrected without
invalidating the underlying observation. A common example is valid GNSS
data with an incorrect timestamp caused by a firmware clock or timestamp
bug. Curation must preserve scientific reproducibility: raw/source data
is immutable and corrections are represented as explicit, versioned,
auditable overlays on canonical records.

## 28.1 Immutable source data and layered interpretation

    The data lifecycle should distinguish:

    RAW / SourceEvent
      exact received data; immutable

    DECODED
      protocol/device interpretation

    CANONICAL
      normalized Smart Parks domain record

    CURATED / EFFECTIVE
      approved corrections applied as an overlay

    PRESENTED
      value normally used by map, analytics, rules and exports

Curation must never silently rewrite the original SourceEvent or raw
payload. The original canonical value and the complete correction
history must remain inspectable.

## 28.2 DataCorrection model

| Field \| Purpose \|

| --- \| --- \|

| id \| Stable correction identifier. \|

| target_type / target_id \| Canonical record being corrected,
  e.g. Position or Measurement. \|

| field \| Curatable field such as timestamp, latitude, longitude, value
  or validity. \|

| original_value \| Value before this correction. \|

| corrected_value \| Proposed/effective corrected value. \|

| reason_code \| Structured data-quality reason. \|

| comment \| Human explanation/evidence. \|

| created_by / created_at \| Correction author and timestamp. \|

| approved_by / approved_at \| Optional approval workflow. \|

| status \| ACTIVE, REVERTED, SUPERSEDED or PENDING. \|

| curation_job_id \| Optional link to a bulk correction operation. \|

## 28.3 Curatable fields are explicit

The platform should not expose arbitrary database editing. Each
canonical record type defines which fields may be curated and which
remain immutable. For example, Position timestamp/coordinates/validity
and Measurement timestamp/value/validity may be curatable, while
SourceEvent.raw_payload is never editable.

## 28.4 Timestamp correction use case

    Example:

    Canonical Position
      original timestamp: 2026-08-01T03:14:00Z
      latitude/longitude: valid

    DataCorrection
      field: timestamp
      corrected timestamp: 2026-08-01T15:14:00Z
      reason: DEVICE_FIRMWARE_TIMESTAMP_ERROR

    Effective Position
      timestamp used by normal analysis: 2026-08-01T15:14:00Z

    The original 03:14 timestamp remains available through provenance/history.

## 28.5 Bulk curation and CurationJob

Firmware and configuration defects may affect thousands or millions of
records. Smart Parks Protect therefore needs a bulk CurationJob workflow
rather than requiring record-by-record edits. An
administrator/researcher should be able to select project, device(s),
record type, time range and a constrained transformation such as
timestamp +12 hours, preview affected records and only then apply the
correction.

    Example bulk correction

    Devices: SP051583 - SP051620
    Record type: GNSS Position
    Affected period: 1 Jul - 12 Jul
    Transformation: timestamp + 12 hours
    Reason: firmware v6.12 timestamp bug
    Affected records: 18,428

    Workflow:
    Preview -> validate samples -> apply -> recompute affected derivatives

## 28.6 Reversible and versioned corrections

Corrections must be reversible and versioned. If a correction is later
found to be wrong, it is marked REVERTED or SUPERSEDED and a new
correction can become ACTIVE. The platform must retain all historical
correction decisions rather than overwriting them.

## 28.7 Structured curation reasons

-   DEVICE_FIRMWARE_BUG

-   DEVICE_CLOCK_ERROR

-   TIMEZONE_ERROR

-   GPS_OUTLIER

-   CALIBRATION_ERROR

-   WRONG_ENTITY_ASSIGNMENT

-   WRONG_PROJECT_ASSIGNMENT

-   CLASSIFICATION_CORRECTION

-   MANUAL_QC

-   OTHER

Structured reason codes should be supplemented by free-text
comments/evidence. This enables later reporting on data quality and the
proportion/nature of curated records.

## 28.8 Downstream recomputation and dependency impact

A correction can invalidate derived state. Applying or reverting a
correction should publish an internal change event and determine which
aggregates, track segments, derived measurements, Rules/Events and
cached analytics are affected. The platform should support controlled
recomputation rather than leaving stale derived results.

    Correction applied
          |
          +-- invalidate/rebuild relevant aggregates
          +-- rebuild affected track segment
          +-- recompute derived measurements
          +-- reevaluate affected rules/events where configured
          +-- flag previous outbound deliveries that may now be stale

## 28.9 Project and Entity attribution must be reevaluated

Because DeviceProjectAssignment and DeviceEntityAssignment are
time-bounded, changing a record timestamp can change which Project or
Entity the record belongs to. Timestamp curation must therefore rerun
historical assignment resolution using the corrected effective
timestamp. The system should show this impact before a bulk correction
is committed.

## 28.10 External integrations and corrected data

If corrected records were previously delivered to EarthRanger,
WildlifeNL, FerusTracker, Movebank or another target, Smart Parks
Protect must record that the external delivery may be stale. Automatic
resend/update should be governed by connector capability and project
policy; high-impact bulk corrections should normally present an explicit
review of affected external deliveries before retransmission.

## 28.11 Curation permissions and approval

    Recommended permissions:
    data:curate
    data:curate_bulk
    data:approve
    data:revert

Projects may optionally require a two-step workflow in which a
researcher proposes a correction and a project administrator approves it
before the curated value becomes effective. Large bulk corrections
should require stronger permissions than routine single-record
annotations/corrections.

## 28.12 Frontend curation workspace

    Recommended navigation:

    Data
      Explorer
      Exports
      Curation
        Pending changes
        Applied corrections
        Bulk jobs
        Reverted/superseded corrections
        Downstream impact

Individual records in Data Explorer should expose a Curate record action
where permitted. Curated fields should be visibly marked, with the
original value, reason and correction history accessible without
obscuring the effective value used by normal users.

## 28.13 Export and scientific reproducibility

Exports should default to effective/curated values but allow authorized
users to request original canonical or raw/source views. Scientific
exports should be able to include curation metadata so analyses can be
reproduced and quality-controlled.

    Example export metadata:
    is_curated
    curation_fields
    curation_reason
    original_timestamp
    effective_timestamp
    curated_by
    curated_at
    curation_job_id

## 28.14 ProcessingTrace and audit integration

Creating, approving, applying, reverting or superseding a correction
must be auditable and linked to ProcessingTrace where applicable. For
bulk jobs, the system should preserve the selection
criteria/transformation, record counts, preview/validation results and
the identity of the users who created and approved the operation.

## 28.15 Hard architecture rules

-   Raw SourceEvents and raw payloads are immutable.

-   Corrections are overlays/versioned records, never silent destructive
    edits.

-   Only explicitly defined domain fields are curatable.

-   Every correction records original value, effective value, reason,
    actor and time.

-   Bulk corrections require preview and impact analysis before
    application.

-   Corrections are reversible and may be superseded without losing
    history.

-   Timestamp corrections rerun Project and Entity assignment
    resolution.

-   Derived analytics/rules/caches affected by curation can be
    deterministically recomputed.

-   Outbound deliveries affected by curation remain traceable and are
    flagged for review/update.

-   Exports can distinguish effective curated values from original
    canonical/raw values.

# 28. Proposed application navigation

| Section \| Core screens \|

| --- \| --- \|

| Monitor \| Live Map, Entities, Devices, Alerts \|

| Analyze \| Data Explorer, Saved Views, Dashboards \|

| Network \| Data Sources, LoRaWAN Traffic, Gateways, Connectivity
  Health \|

| Rules \| Rules, Rule Tests, Events, Automations \|

| Integrate \| EarthRanger, Webhooks, MQTT, API integrations, Delivery
  log \|

| Control \| Commands, Device Configuration, Command history \|

| Projects/Admin \| Projects, users, roles, device/entity setup, metrics
  and profiles \|

# 29. Suggested repository/service structure

The exact structure should follow AddaxAI Connect conventions where that
improves reuse. Conceptually, however, the codebase should make domain
boundaries visible.

    smartparks-connect/
      services/
        api/
        frontend/
        ingest/
        decoder/
        rules/
        automation/
        integration/
        aggregation/
        export/

      shared/
        domain/
        schemas/
        metrics/
        device_drivers/
          opencollar/
        connectivity/
          transports/
            mqtt/
            http/
            websocket/
          adapters/
            chirpstack/
            kpn_thingpark/
            loriot/
            tts/
            actility/
            traccar/

      tests/
      docs/
      ansible/
      docker-compose.yml

# 30. MVP recommendation

The architecture should be generic from day one, but the first
implementation should remain deliberately narrow enough to reach a
usable system quickly.

## 30.1 MVP scope

-   Separate repository derived from AddaxAI Connect with generic
    authentication, projects, RBAC, PostgreSQL/PostGIS, Redis,
    deployment and frontend shell retained where practical.

-   Core Entity, Device, DeviceAssignment, DataSource, SourceEvent,
    Position, Measurement, DeviceState and Event models.

-   Connectivity abstraction implemented before provider-specific code.

-   OpenCollar Device Driver as the first comprehensive driver.

-   ChirpStack adapter as the technical reference implementation.

-   KPN and LORIOT adapters as the first production network
    integrations.

-   Traccar adapter or small proof-of-concept to validate that the
    architecture is not accidentally LoRaWAN-only.

-   Live map with entity positions/tracks and device drill-down.

-   Data Explorer with table + core time-series charts.

-   CSV and XLSX export from normalized data.

-   Initial rules: geofence enter/exit, speed limit, inactivity/no data,
    battery threshold.

-   Event and alert views.

-   EarthRanger realtime outbound connector with durable retry/delivery
    status.

-   AddaxAI Connect inbound connector for detections/observations,
    including source provenance and project mapping.

-   Basic device commands/downlinks through the abstract command path.

-   Provenance UI from normalized data back to SourceEvent, DataSource
    and external identity, including at least one working Open in source
    deep link.

-   Time-bounded Entity ↔ Device assignments validated by reassigning a
    device while preserving historical entity ownership of
    positions/measurements.

-   Capability-driven Device Control with at least RESET or
    REQUEST_STATUS for OpenCollar through two different LoRaWAN adapters
    (for example ChirpStack and KPN or LORIOT).

## 30.2 Explicitly defer from the first MVP

-   Full scientific statistics library and advanced behavioral modeling.

-   Complex dashboard builder comparable to Grafana.

-   Every LoRaWAN provider and every control-plane API.

-   Full gateway management for providers where this requires
    substantial separate work.

-   Large-scale AI anomaly detection.

-   Generic workflow engine beyond the rule/action patterns actually
    needed.

-   Binary media handling unless a use case requires it.

# 31. Development sequence / technical spikes

1.  Create the separate repository and identify reusable AddaxAI Connect
    modules versus camera-specific code to remove.

2.  Define canonical domain schemas and database migrations for Entity,
    Device, DataSource, SourceEvent, Position, Measurement and Event.

3.  Implement the generic connectivity adapter interfaces and a
    SourceEvent ingestion pipeline.

4.  Build ChirpStack + OpenCollar end-to-end: ingest → decode →
    normalize → map/table → raw drill-down.

5.  Implement Data Explorer and export early to validate time-series
    storage decisions.

6.  Add the Rules & Automation interfaces with 3--4 simple rules before
    attempting advanced scientific expressions.

7.  Add EarthRanger outbound delivery with retry/logging.

8.  Add KPN and LORIOT adapters and verify that no domain/UI code needs
    provider-specific changes.

9.  Add Traccar proof-of-concept to validate non-LoRaWAN extensibility.

10. Evaluate TimescaleDB using realistic Smart Parks telemetry volumes
    before committing to it as a required dependency.

11. Only after the core abstractions survive these integrations, expand
    gateway operations, dashboards and advanced scientific rules.

# 32. Architectural decisions to resolve during the first spike

| Decision \| Question to answer \|

| --- \| --- \|

| Fork vs code extraction \| How much AddaxAI Connect code can be
  cleanly reused without carrying camera/AI coupling? \|

| Database strategy \| Plain PostgreSQL/PostGIS initially or TimescaleDB
  from the first migration? \|

| Event bus \| Is Redis Streams/queues sufficient for durable domain
  events and retries at intended scale? \|

| Rule representation \| Visual JSON/DSL first, expression language, or
  combination? \|

| Raw payload retention \| Retention policy and database vs object-store
  placement for very large/raw events. \|

| Metric typing \| How to handle numeric, boolean, categorical and
  structured measurements consistently? \|

| Entity model \| Single Entity table with flexible types versus
  selected subtype tables. \|

| Integration delivery \| Queue/retry semantics, idempotency keys and
  backfill strategy. \|

| Adapter lifecycle \| Plugin registry/discovery model versus static
  Python modules. \|

| Multi-tenancy \| Project-level isolation only or stronger
  organization/tenant model. \|

| External deep links \| Which providers expose stable
  device/application/gateway URLs and how should provider-specific URL
  templates be configured? \|

| Assignment attribution \| Should normalized records persist entity_id
  at processing time in addition to the temporal DeviceAssignment
  reference for fast and immutable historical queries? \|

| Control action schema \| How are device-type action definitions
  versioned, parameterized and safely exposed to rules as well as the
  UI? \|

# 33. Definition of success for the first demonstrator

A convincing first demonstrator does not need every planned feature. It
should prove the architecture by showing the same internal platform
working across multiple sources and multiple user workflows.

    Suggested demonstration
    Receive live OpenCollar data from at least two different LoRaWAN backends, display the same entities on the live map, inspect raw and normalized traffic, analyze battery/RSSI/another sensor metric in a table and chart, export the selected data to CSV/XLSX, trigger a geofence or speed rule, create an Event, and forward that Event or Position to EarthRanger. Ideally add one Traccar-fed entity to prove that the platform is not LoRaWAN-specific.
    Also demonstrate an AddaxAI Connect detection (for example a wolf detection) entering Smart Parks Protect as a normalized Event, retaining a direct source link and optionally being forwarded by a rule to EarthRanger.

# 34. Working product definition

Smart Parks Protect is a self-hosted operational data platform that
connects heterogeneous field devices and IoT platforms to a unified
Smart Parks domain. It provides live monitoring, structured time-series
analysis, easy export, bidirectional device control, configurable rules
and automation, and reliable integrations with systems such as
EarthRanger. Application-level sources such as AddaxAI Connect should
integrate through the same provenance-aware event architecture as device
and IoT sources.

Its central architectural value is separation of concerns: connectivity
adapters understand external platforms, device drivers understand device
protocols and control actions, the normalized domain understands Smart
Parks entities and data, and rules/integrations operate on that
normalized domain. Data remains traceable to its external source and
management interface, while time-bounded DeviceAssignments preserve the
independent history of Entities and reusable Devices. This makes it
possible to start with OpenCollar and LoRaWAN while remaining ready for
vehicles, people, traps, gates, weather stations, Traccar, satellite
services and future Smart Parks technologies.

# 35. References / current starting point

Public sources reviewed for the current AddaxAI Connect baseline:

-   AddaxAI Connect public repository:
    https://github.com/PetervanLunteren/AddaxAI-Connect

-   AddaxAI Connect architecture documentation:
    https://connect.addaxai.com/architecture/

At the time this draft was prepared, the public repository described
AddaxAI Connect as a self-hosted camera-trap platform with independent
Docker processing services, Redis queues, PostgreSQL, MinIO,
multi-project RBAC, maps, charts, notifications and export. These
details should be revalidated against the code when the Smart Parks
Protect repository is actually created.

## 35.1 Additional references for satellite and multi-path connectivity:

-   Cloudloop API overview:
    https://knowledge.cloudloop.com/docs/api/overview

-   Cloudloop data and message delivery:
    https://knowledge.cloudloop.com/docs/data

-   Cloudloop outbound SBD/MT messages:
    https://knowledge.cloudloop.com/docs/api/send-message

-   Smart Parks public GitHub repositories:
    https://github.com/SmartParksOrg
