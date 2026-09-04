# Integrations

- [Adapter interface](adapter-interface.md): how an external platform is connected.
- [ChirpStack](chirpstack/index.md): the reference LoRaWAN network server, local setup, bootstrap and simulator.
- [KPN LoRa (ThingPark)](kpn-thingpark/index.md): HTTP push events and the ThingPark downlink API.
- [LORIOT](loriot/index.md): websocket output with downlinks on the same connection.
- [Netmore](netmore/index.md): export format over HTTP push or MQTT, downlinks through the LoRaWAN Portal or Netmore Connect API.
- [akenza.io](akenza/index.md): webhook samples, downlinks through the akenza REST API.
- [The Things Stack](tts/index.md): webhook events, downlinks through the application API, gateways from the gateway API.
- [Actility ThingPark](actility/index.md): the ThingPark adapter of KPN under its own name for public and private deployments.
- [Traccar](traccar/index.md): the non-LoRaWAN tracking source over its websocket, with the command proof of concept.
- [AddaxAI Connect](addaxai-connect/index.md): camera trap detections as `SPECIES_DETECTION` events, polled with a cursor.
- [Cloudloop (Iridium)](cloudloop/index.md): RockBLOCK satellite messages over a webhook, commands as SBD messages.
- [Gateways and connectivity](gateways.md): the gateway registry and the coverage analysis per device.
- [Outbound integrations](outbound.md): durable deliveries with retries, backfill and a delivery log; webhook and MQTT targets.
- [EarthRanger via Gundi](earthranger-gundi/index.md): positions as observations and events as EarthRanger events.
- [EarthRanger direct API](earthranger/index.md): the same, straight to a site with its token; corrected events are updated in place.
- Generic HTTP and generic MQTT sources exist as well, and two built-in sources carry what a browser reads over Web Bluetooth and what a person uploads as a raw log file (see [devices](../devices/index.md)).
