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

Recorded events from Smart Parks' own KPN account replace the invented files when the live run
happens (phase 7 input).
