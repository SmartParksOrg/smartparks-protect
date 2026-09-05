# Live verification

The order in which the platform is proven against real accounts, collars and partner sites,
once they exist. Every adapter and connector was built from published documentation and
tested against documented payloads; this runbook turns each into a recorded live check. Work
through the stages in order: each one reuses what the previous one set up, and the first
stage alone already retires most of the risk.

For every check, record three things: the plan's checkbox and session log entry, the raw
payloads as fixtures under `tests/fixtures/payloads/<provider>/` with a README that names
the device, the network and the date, and a screenshot under `docs/assets/` where the
runbook shows one. Raw payloads come from Network, Traffic (open the source event, copy the
payload) or from an export of the `source_events` dataset over the window of the test.

## Stage 0: the server and one collar

You need: the dev server (`https://dev-protect.smartparks.org`), a server admin login, and
one OpenCollar Edge with a known DevEUI, charged and outdoors or on a window sill.

1. `bash scripts/verify-server.sh` on the server: every check passes.
2. Server admin, Device types: an OpenCollar type exists (the demo bootstrap made one).
3. Create the device for the collar under Server admin, Devices, with its DevEUI as the name,
   and an entity in the project it will track; assign the device to the entity from now.

## Stage 1: the first real LoRaWAN network

Pick the network the collar is registered on. Each has a runbook with the exact portal steps:
[KPN LoRa](../integrations/kpn-thingpark/index.md), [LORIOT](../integrations/loriot/index.md),
[Netmore](../integrations/netmore/index.md), [akenza](../integrations/akenza/index.md),
[The Things Stack](../integrations/tts/index.md), [Actility](../integrations/actility/index.md),
[CRA IoT](../integrations/cra-iot/index.md).

1. Server admin, Data sources, New data source with the network's adapter. Copy the webhook
   URL and the bearer token shown once (LORIOT connects outward instead and needs the
   application's websocket token).
2. In the network's portal, point the application's HTTP output at the webhook URL with the
   `Authorization: Bearer <token>` header, as the runbook says.
3. Register the collar's DevEUI as an external identity on the data source, or wait for the
   first uplink and accept it from Server admin, Needs attention, linking it to the device.
4. Watch, in this order: Server admin, Data sources, Traffic on the new source (every message it receives, linked or not, refreshing every five seconds); Network, Traffic (the uplink with its hex frame and gateways);
   Network, Trace explorer (ingest to canonical rows, every step green); the entity on the
   Live map; Data explorer with battery voltage over the last hour.
5. Device page: "Open in <network>" opens the right page in the portal. Deep links were built
   from documentation and may need the template corrected on the data source.
6. Device page, Actions: Request status. The command timeline should reach queued, then
   transmitted when the network reports it, then confirmed when the collar answers on port 4.
   Note which stages the network reports; unknown stages are expected on some networks.
7. Record: the first five uplinks and the downlink events as fixtures, a screenshot of the
   trace, the command timeline outcome, and any deep link fix.

This closes the phase 7 box "real collars visible on the map" for that network and proves
the documentation-built adapter (the condition Tim set for phase 13's start).

## Stage 2: the second network

Repeat stage 1 on a second network with the same collar (re-registered) or a second collar.
Then run Request status through both; the phase 7 box "the same action over two networks"
is the pair of command timelines. Two networks feeding one map is also step 1 of the
[demonstration](../getting-started/demonstration.md).

## Stage 3: the collar next to you

With the collar in hand, in Chrome or Edge on HTTPS:

1. Device page, the Web Bluetooth card: connect, read status and settings, sync the flash
   log ([OpenCollar over Web Bluetooth](../devices/opencollar-webble.md)). Positions the
   network already delivered must appear once, with two deliveries in the provenance panel.
2. Upload the same log as a file under the device's Log files card
   ([raw log files](../devices/raw-log-files.md)): the third delivery of the same positions.
3. Record the notification frames and the log file as fixtures.

If the collar has an Iridium modem: the [Cloudloop](../integrations/cloudloop/index.md)
runbook, with the RockBLOCK IMEI as the identity; the satellite path becomes the fourth
delivery of the same records.

## Stage 4: outbound partners

1. EarthRanger: a test site (a sandbox from EarthRanger, or the WildlifeNL site) and either a
   Gundi connection ([EarthRanger via Gundi](../integrations/earthranger-gundi/index.md)) or
   the site's own token ([EarthRanger direct](../integrations/earthranger/index.md)). Send the
   test event, then forward positions; the subject moves on the EarthRanger map. Correct one
   position in Curation and resend the stale delivery: the direct connector updates the event
   in place, Gundi creates a new one.
2. [WildlifeNL](../integrations/wildlifenl/index.md): the API URL and a data-system account;
   Test connection, then forward positions and let a herd manager register the collar's
   DevEUI as its sensor deployment; the animal moves on the platform.
3. [FerusTracker](../integrations/ferustracker/index.md): the site value the flow uses; forward
   positions and confirm on ferustracker.nl that the fixes land with the right time. The
   runbook lists the three assumptions to confirm.
4. Movebank: export the `movebank_events` and `movebank_reference` datasets and import them
   into a Movebank study as a custom import; note any column Movebank rejects.

## Stage 5: other sources

1. [AddaxAI Connect](../integrations/addaxai-connect/index.md): a viewer account on a server
   with cameras; a detection becomes a `SPECIES_DETECTION` event at the camera with the
   deep link; a rule forwards it to EarthRanger (demonstration step 8).
2. [Traccar](../integrations/traccar/index.md): an instance with one tracker; the vehicle
   moves next to the collars (demonstration step 7).

## Stage 6: AI clients

Claude is verified. ChatGPT needs a Pro or Business account with developer mode: add the
connector as the [MCP page](../mcp/index.md) says, approve the consent page, and ask the
three questions from the Claude check. Then try one write: "acknowledge the open alert on
Rhino 14"; the client must ask for confirmation before the alert changes.

## Stage 7: the demonstration

With stages 1 to 5 in place, run the [demonstration script](../getting-started/demonstration.md)
end to end and record the result in the plan's session log with screenshots. That is the
plan's v1.0.0 milestone in its original sense: the architecture's definition of success
shown live.

## What to send back

For every stage: the raw payloads (fixtures), screenshots of the trace and the map, the
command timeline outcome, the deep link URL the portal shows for a device, and anything that
looked wrong. Each stage is an hour or two of work once its inputs exist.
