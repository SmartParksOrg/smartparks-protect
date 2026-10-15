# 0040. An offload station's card is read by Protect, frame by frame, with keys held per device

Date: 2026-10-15

Status: accepted

## Context

The OpenCollar Edge firmware is gaining LP0, a raw LoRa path by which a tracker offloads its
flash log to a nearby offload station, a RangerEdge with an SD card. The station writes every
frame it receives as one JSON line in the shape a LoRaWAN gateway forwards, with the frame rebuilt
as an ordinary LoRaWAN 1.0 uplink on port 29 addressed by the tracker's LP0 DevAddr and encrypted
under the tracker's own session keys. The station holds no keys; the tracker's EUI is not on the
card; the firmware deduplicates nothing. The records inside are the flash stream Protect already
decodes from raw log files and port 29 uplinks. Tim's decision of 2026-10-15: the address and the
keys are provisioned per device, unique like the DevEUI, and the stations do not decrypt.

Two ways existed to get a card into Protect: replay its lines into a network server through the
public replay app, so the frames arrive through the ChirpStack adapter as any uplink; or read the
card directly.

## Decision

Protect reads the card itself. A card's files are raw log files of the station (channel `lp0`),
decoded through the one file worker and pipeline; each line is a delivery on a built-in source
"Offload station files", addressed by the LP0 address, with the station as the gateway that
received it and the reception as metadata. The address and the two keys live on the device, in a
table of their own with the keys encrypted at rest, and the address doubles as the device's
identity on the source. The decryption is a pipeline step that runs with the device's keys when
the frame is decoded, so a frame retained for an unknown address is decoded after the link without
a second upload and a device without keys fails plainly. A frame with the same address, counter and
bytes as one of the last 30 days is a repeat; records repeated across paths fold by their
canonical key as everywhere. The station is both an Offload station entity with its device and a
gateway of the source linked to that device. A reception time the station cannot have had is not
believed as the delivery time.

## Alternatives considered

- Replaying the card into a ChirpStack: a network server enforces frame counters and refuses
  frames behind the one it last accepted, which a replayed card is full of; the keys would live
  there with every tracker registered twice; nothing in Protect would know a card was read.
- Keys per LP0 network on a data source: the first proposal, corrected the same day, since the
  keys are unique per device.
- Decrypting in the file worker: a frame whose device is unknown at upload time could not be
  decrypted later without storing it twice; one pipeline step serves the upload, the walk and the
  re-decode alike.

## Consequences

Any LoRaWAN-framed file can enter this way later (a station that uploads its own files, a
different medium with the same record stream). The keys are a secret Protect now holds for each
tracker, under the server's credentials key, and a server admin or an operator of the project sets
them. The firmware's on-air DATA is encrypted under session keys derived from the discovery and
wrapped in an LP0 header; a card can only be read because the station rebuilds the ordinary frame.
If the station is to hold no keys at all, the tracker must send that ordinary frame itself, which
is the one requirement this design puts on the firmware. Firmware issue 772 (2026-10-15) takes
that direction: link authentication by a deployment master key, payload encryption per device,
the station opaque; its open points (an envelope or a PHYPayload on the card, the counter width,
which credentials) are met by reading a counter across a rollover from the device's last verified
one, refusing a named frame format Protect does not read, and keeping a station-given EUI as the
identity's name on Needs attention. The research document's section 3.17 on LP0 is superseded.
