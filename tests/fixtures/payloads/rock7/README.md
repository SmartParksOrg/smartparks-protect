# Rock7 RockBLOCK fixtures

Deliveries of a RockBLOCK delivery group's HTTP_POST address (form fields, stored as the
object the ingest route made of the form). Keep the origin of every file here.

- `delivery_live_sp051890.json`: the first live delivery to the dev server on 2026-09-10 at
  10:44 UTC, from the OpenCollar Edge SP051890 (RockBLOCK serial 204514, IMEI 300434065263440,
  session 4753) in the delivery group "dev-protect"; source event 37945. The fields beyond the
  documentation: `device_type` (`ROCKBLOCK`) and `iridium_session_status` (`2`), and
  `transmit_time` in the documented `YY-MM-DD HH:MM:SS` form. The 168 byte payload holds a
  status message (firmware 7.2, hardware 1.6) and a GNSS fix as stacked stored records.
