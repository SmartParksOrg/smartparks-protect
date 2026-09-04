# FerusTracker

[FerusTracker](https://ferustracker.nl) receives Smart Parks collar data for Dutch sites.
It publishes no API documentation; the contract is the Node-RED flow that feeds it today,
which the connector reproduces from canonical positions and measurements (decision D89).

## What the flow sends

For every uplink of a known payload type the flow decodes the frame with the collar's own
JavaScript decoder and posts, without authentication, to
`https://ferustracker.nl/api/smartparks`:

```json
{
  "devEUI": "70B3D57ED0001234",
  "fPort": 2,
  "tags": {"payloadType": "opencollar_edge_6", "subType": ""},
  "deviceName": "70B3D57ED0001234",
  "objectJSON": "{\"latitude\":51.2,\"longitude\":5.7,\"altitude\":34.5}",
  "provider": "kpn",
  "site": "Kempen-Broek"
}
```

`objectJSON` is the decoded fields as a JSON string under the decoder's own names. Payload
types in the flow: `opencollar_v2`, `opencollar_edge_2`, `opencollar_edge_4`,
`opencollar_edge_6`, and without a decoder `dragino_lgt92_v1`, `ideetron_hp_gps_v1`,
`opencollar_edge_cat_1_6`.

## Setup

1. Under Integrate, Integrations: New integration, connector FerusTracker. Config: `url`
   (the endpoint above by default), `site` (the site name FerusTracker files the data
   under), `provider` (`kpn` by default), `payload_types` (Smart Parks device type key to the
   payload type its decoder had in the flow) and `default_payload_type` for unmapped devices.
   No credentials: the endpoint takes the documents as they are and recognises collars by
   DevEUI.
2. Test the connection: the connector only checks that the endpoint answers, since every
   document is data.
3. Enable positions and measurements; events have no counterpart and are skipped.

## Mapping

| Smart Parks Protect | FerusTracker document |
| --- | --- |
| position, OpenCollar Edge types | `fPort` 2, `objectJSON` with `latitude`, `longitude`, `altitude`, `fix_timestamp` (epoch seconds), `SIV` (satellites), `h_acc_est` (accuracy) |
| position, `opencollar_v2` | `fPort` 1, `objectJSON` with `latitude`, `longitude`, `alt`, `satellites`, `gps_time` |
| `battery_voltage` measurement | `fPort` 4 with `bat` in millivolts (Edge) or `fPort` 12 with `battery` (v2) |
| `device_temperature` or `temperature` measurement | `fPort` 4 with `temp` (Edge) or `fPort` 12 with `temperature` (v2) |
| other measurements, events | skipped |

`devEUI` and `deviceName` are the device's primary identity (the flow sends the DevEUI for
both). One field beyond the flow: a top-level `time` (ISO 8601) with the record's time, since
the flow left the time to the receiver and backfilled deliveries would otherwise lose it.

## Assumptions to confirm live

- FerusTracker reads `objectJSON` by `payloadType` with the decoder's field names, so a
  canonical position rendered under those names lands as a fix.
- The `site` value the flow sets upstream (Tim knows the names in use).
- Whether an unknown `time` field or a partial status message (battery without the other
  status fields) is accepted; if not, the connector narrows to what the platform takes.

## Troubleshooting

- `ferustracker answered 4xx`: the platform rejected the document; the message is in the
  delivery log. Check the payload type and the DevEUI is known there.
- Positions arrive under the wrong time: FerusTracker ignores `time` and `fix_timestamp`;
  deliveries then carry the receive time, and backfills are not useful.
