# 0021 Firmware-aware device driver layouts

Date: 2026-09-06. Status: accepted. Decision D100 in the project plan.

## Context

OpenCollar collars in the field run firmware from 4.x to 7.3. The frames are the same across versions, but the set of messages differs: the RF scanner (port 8) and open sky detection (port 17) exist up to 6.16, the timestamp and external switch messages (ports 18 to 20) from 6.15, air quality (port 21) from 7.2, and one status feature bit meant the RF scanner before 7.1. The firmware publishes one reference decoder per range. The driver decoded everything with the newest layout and treated older messages as unknown ports.

## Decision

The driver keeps one layout per firmware range, named after the reference decoder of that range, and picks it from the firmware version the device last reported in its status message (stored on the device by the decoder) or, inside a raw log stream, from the status records in the stream itself. The layout used is recorded as the decoder version on every record. A port a layout lacks is a note on the trace that names where the message comes from, never a failure. Golden tests run every recorded frame through the vendored reference decoders and compare our records with their output.

## Consequences

Older collars decode their own messages; a new firmware means one more layout and a regenerated golden file. The firmware version must reach the driver: `SourceEventData.firmware_version`, filled from the device. When a device has never sent a status, the newest layout applies, which is right for every port the versions share.
