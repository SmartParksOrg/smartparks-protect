# KPN / ThingPark fixtures

Shapes follow the ThingPark tunnel interface documentation (`DevEUI_uplink`,
`DevEUI_downlink_Sent`). Keep the origin of every file here.

- `uplink.json`, `downlink_sent.json`: invented from the documentation on 2026-09-04. The DevEUI
  is the local simulator's, the payload an OpenCollar port 2 frame, the CorrelationID a UUID
  (a real one is 64 bits of hex).
- `actility_uplink_with_token.json`: Actility's published example of a push with its query
  parameters, body and tunnel interface authentication key
  (github.com/actility/thingpark-integrations, `verify_token_in_uplink.py`). The golden test
  for the push Token: the adapter must recompute exactly that token.
- `kpn_uplink_hookbin_2016.json`: a real KPN LoRa push captured by IoT Academy with hookbin in
  2016 and published with its LRC-AS key (github.com/iotacademy/LoRaPayloadSimulator). The
  Dutch time offset (`+02:00`) in the query is why the webhook parses the raw query string.

- `kpn_live_uplink_port13.json`, `kpn_live_uplink_port4.json`: the first live pushes from Smart
  Parks' KPN application server (`kpn-lora.com`, subscriber Wireless Logic Benelux, AS ID
  `ASIDsmartparkseu`) to the dev server on 2026-09-06, stored bodies of an OpenCollar GNSS fix
  (port 13) and a status message (port 4). KPN's ThingPark sends numbers, not strings. The URL
  query with the Token is not stored, so these test parsing and decoding, not the token.

The invented files stay until every report type has a recorded example.
