# Demonstration

The architecture's section 33 describes the demonstration that proves the platform end to end.
This page is the script. Steps marked *local* run on the compose stack with the simulator today;
steps marked *live* need accounts and hardware Smart Parks provides (a second LoRaWAN network
with collars, a Gundi connection to an EarthRanger site, an AddaxAI Connect server, a Traccar
instance). The result of every run is recorded in the plan's session log with screenshots under
`docs/assets/`.

## Preparation

1. *local* Start the stack with the ChirpStack profile, bootstrap the first admin and the demo
   project (`scripts/dev.sh chirpstack-bootstrap --demo`), start the simulator.
2. *live* Add the second network as a data source (KPN, LORIOT, Netmore or akenza runbook),
   register the collar's DevEUI, link it to a second entity.
3. *live* Add the Traccar data source, accept the tracker from Needs attention, assign it to a
   vehicle entity.
4. *live* Add the AddaxAI Connect data source with the viewer account, accept a camera, give it
   an infrastructure entity.
5. *live* Create the EarthRanger via Gundi integration, forward positions and events, Test.

## Script

| Step | Where | Expected |
| --- | --- | --- |
| 1. Two LoRaWAN backends deliver live OpenCollar data (*live*) | Live map | Both entities move; Network, Traffic shows uplinks from both data sources with their gateways |
| 2. Raw and normalized traffic | Traffic, Trace explorer | A frame's hex, its decoded position and measurements, and the trace from ingest to canonical rows |
| 3. Battery and RSSI analysed (*local*) | Data explorer | Battery voltage and RSSI per entity over the last day as a chart and a table |
| 4. Export (*local*) | Exports | The selected series as CSV and XLSX with reproducibility metadata |
| 5. A geofence rule fires (*local*) | Rules, Events | Draw a geofence the simulated rhino leaves; the `GEOFENCE_EXIT` event appears with an alert |
| 6. The event reaches EarthRanger (*live*) | Integrations, Deliveries | The delivery is sent with Gundi's object id; the event shows on the EarthRanger site |
| 7. A Traccar entity on the map (*live*) | Live map | The vehicle moves with the collars; its source is Traccar in the provenance panel |
| 8. A wolf detection from AddaxAI Connect (*live*) | Events, Live map | A `SPECIES_DETECTION` event at the camera with species and confidence, Open in AddaxAI Connect, forwarded by a rule to EarthRanger |
| 9. Acknowledge an alert (*local*) | Alerts | The alert moves to acknowledged with the note and the actor in the audit log |
| 10. Reassign a device (*local*) | Devices | Move the collar to another entity from now; older positions stay with the first entity, new ones go to the second |
| 11. A command over the abstract control path (*local*, *live* for a second network) | Device, Actions | Request status through ChirpStack; the command's timeline reaches transmitted and the device answers |

## Status

Steps 2 to 5, 9, 10 and the ChirpStack half of 11 pass on the local stack (phase 8 session).
Steps 1, 6, 7, 8 and the second-network half of 11 wait for the live accounts; the code paths
they exercise are covered by tests against documented payloads.
