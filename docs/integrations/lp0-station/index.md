# Offload station files (LP0)

The built-in data source that carries what an offload station's SD card holds (phase 42,
decisions D319 to D324). It is not an external platform: a RangerEdge offload station stores the
frames trackers offload to it over LP0, the OpenCollar Edge firmware's raw LoRa path, and a
person uploads the card's files on the station's device page. Every line of a file is a delivery
on this source, addressed by the tracker's LP0 address; every station is a gateway of it.
Nothing is configured on the source itself. The guide is
[Offload stations](../../devices/offload-stations.md).

Built from the firmware branch `fix/existing-lp0-implementation` of
`SmartParksOrg/smartparks-opencollar-edge-fw` (68 commits ahead of 8.0.3, read on 2026-10-15):
the LP0 module README, the station's SD writer (`lp0_offload.c`), the wire format of protocol
version 4 and the master plan's importer decision; the frame codec is checked against the
firmware's own replay fixture. No card had been read into Protect when this was written.

## What the station writes

`LOG_N/STATIONEUI_timestamp[_NNN].jsonl`, one JSON document per line in the Semtech `rxpk`
shape: `gatewayEui` (the station), `rxpk.time` and `rxpk.tmst` (the reception, `tmst` in Unix
seconds), `freq` (MHz), `datr` (`SF7BW250`), `codr`, `rssi` (dBm), `lsnr` (dB), `size` and `data`.
`data` is an ordinary LoRaWAN 1.0 uplink: MHDR `0x40`, the tracker's DevAddr, FCtrl, a 16-bit
counter (the upper half of the 32-bit counter is zero), port 29, the FRMPayload encrypted with
the tracker's AppSKey and a MIC under its NwkSKey. The payload is the flash record stream
(`port, msg_id, len, data, store time`, repeated), at most 228 bytes per frame.

## The model of firmware issue 772

Tim's issue 772 in the firmware repository (2026-10-15) separates the LP0 link's authentication
(a deployment master key, per-session keys derived from the discovery) from the payload's
encryption (each collar's own unique DevAddr, NwkSKey and AppSKey, under LoRaWAN counter and MIC
semantics), makes the station an opaque store that keeps routing metadata and no device key, and
has the backend decrypt per device. This source is built for that model: the keys per device, the
decryption in the pipeline, the station a gateway. Three of the issue's open points are met
halfway: a counter is read across a rollover from the device's last verified one (`last_f_cnt`
on the credentials, `f_cnt32` on the frame); a line that names a frame format (`frameFormat`,
`format`, `lp0Format`) is read only when the format is `lorawan`, so an envelope the firmware
may introduce is refused by name until Protect reads it; and a line that carries the tracker's
EUI (`devEui`) names the unknown identity on Needs attention with it, without linking by itself.

## Identities and keys

The tracker's LP0 address is its identity on this source (`identity_type` `dev_addr`, the
address as eight uppercase hex digits). It is written when the address and keys are set on the
device (`PUT /devices/{id}/lp0-credentials`); a frame from an address no device has makes an
unknown identity on Needs attention. The two keys are the device's, encrypted at rest with the
server's credentials key and returned to callers who may set them (device control in the project, or a server admin), so they can be read back and changed; a viewer sees only that they are set. There is no shared network key in Protect: a
network whose devices share one pair is every device holding the same pair.

## Stations

The first frame of a card makes the station a gateway of this source, named after the device
whose card it is and linked to it (`gateways.device_id`), with `kind: offload_station` in its
attributes; "Make an offload station" on the project's Offload page makes that row earlier,
with nothing seen yet, so the station is listed before its first card. Every frame is a reception of that gateway with the line's RSSI, SNR and frequency,
so the Gateways page, the coverage layer and the trackers' Connectivity tabs read it as they read
a LoRaWAN gateway. A station's place is set by hand on its device page; the gateway's location
can be set by hand too (Gateways page).

## Processing

The file worker splits the file, stores every line as a source event with the station as the
gateway and the reception metadata, and decodes it at once. The decryption is a step of the
decoder pipeline, not of the file worker: a channel `lp0` event without a decrypted frame is
unwrapped with the device's keys before the driver runs and the result kept in its metadata, so
a walk over retained frames after an identity is linked and "Decode again" use the same step. A
frame of a device without keys fails with `CREDENTIALS_MISSING`; one that does not verify with
`PAYLOAD_DECODE_FAILED`; a frame with the same address, counter and bytes as one of the last 30
days is a repeat and stored as a duplicate of the first. A reception time before
`LP0_EARLIEST_RECEPTION` or after the upload is not believed as the delivery time.

## Troubleshooting

| Seen | Meaning | What to do |
| --- | --- | --- |
| The upload answers "Not a station file" | The file is not one JSON document per line, nor a zip of `LOG_*` folders | Upload the `.jsonl` files or a zip of the card's folders; a raw log `.txt` goes through "Upload raw log" as before |
| A member "uploaded before" | The same bytes were uploaded for this station | Nothing; the earlier row holds the frames |
| Frames "of trackers not known yet" | Addresses no device has | Needs attention: link each address to its device, then set the keys on the device |
| Frames "of a tracker without keys" | The device is known, its keys are not | Set the keys on the device, then "Decode again" on the file |
| Frames "that did not verify" | A wrong key, or a frame of another device under this address | Check the keys against the device's provisioning; the frames stay failed, never guessed |
| Every record of a card invalid as "ahead of its delivery" | A station clock far behind | Should not happen: a time before 2024 is not believed; report it with the file's trace |
