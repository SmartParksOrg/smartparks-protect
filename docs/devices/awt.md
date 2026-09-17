# AWT tracker

African Wildlife Tracking (AWT) LoRaWAN trackers, decoded by the `awt` driver
(`shared/device_drivers/awt/`, decision D241). The first ones reach Protect through the
African Wildlife Tracking application on the BPC ChirpStack; the six devices of that
application (L10966, L11478 to L11482) are known identities on the source and become devices
of the type AWT tracker from Needs attention.

## The frame

One message per uplink, on any port, laid out as AWT's own ChirpStack codec reads it
(`tests/fixtures/payloads/awt/decoder.js`, handed over by Tim on 2026-09-17): a header with a
message counter, an encrypted flag and an XOR checksum; the payload type (minimal, standard,
with altitude, with light); master tag and tag ids; two bytes of alarm and acknowledgement
flags; the software version; the reporting interval code; the battery voltage; the fix's unix
time; the latitude and longitude as packed degrees and minutes with the HDOP and three flags
in their spare bits; ground speed; the accelerometer's three axes; the temperature; the
altitude and the light level when the payload type carries them; and a payload checksum.

Two readings the driver takes from the layout rather than the codec, until a real fix outside
the south-east quadrant or AWT's document says otherwise: the hemisphere comes from the sign
bits of the two words (the codec's test puts every fix south and east, which is right in
southern Africa), and the HDOP from bits 27 to 30 of the latitude word (the codec reads them
from one byte, which has no bit 27).

## What the driver produces

| Record | From |
| --- | --- |
| Position (`gnss`) with the fix time, altitude when sent, HDOP, raw ground speed and the movement flag as attributes | the packed words, the epoch |
| `battery_voltage` (V), `device_temperature` (°C), `gnss_hdop` | bytes 14-15, 36, the latitude word |
| `status` state: the problem flags as `errors` (low battery, tamper foil, service coverage, memory full, self test, humidity), firmware, reporting interval, payload type, counters, the accelerometer's raw axes, the light level, whether the checksums matched | bytes 10-13, 29-35, 39-40 |
| `settings` state with `fix_interval` in seconds | the reporting interval code (decision D242: the expected-interval rules read it, so the Reporting card and the device performance analysis know the interval without learning it) |
| `device_error` event with the problem flags that are on, explained in the feed | bytes 10 and 11 |

A frame whose coordinates are zero gives no position; a fix time before 2015 is the device's
clock unset and the network's time stands in, with a note on the trace. A checksum that does
not match is noted, not refused. The ground speed, the accelerometer and the light level are
kept raw: their units are not in the codec.

## Health

Battery, temperature (warn at 50 °C, critical at 60), the error flags, the firmware and the
HDOP of the last fix (warn above 5). AWT does not publish battery thresholds; none are set.

## Control

None yet: the codec covers uplinks only.

## Testing

`scripts/awt_golden.py` builds the fixture frames and runs them through the codec with node;
`tests/shared/test_awt_driver.py` checks the driver against that output field by field and the
records it produces. The frames are synthetic until recorded uplinks arrive; the fixture README
says which is which.
