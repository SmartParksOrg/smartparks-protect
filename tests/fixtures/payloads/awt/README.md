# AWT tracker fixtures

`decoder.js`: the TS013 payload codec African Wildlife Tracking devices are decoded with on the
BPC ChirpStack, as Tim handed it over on 2026-09-17. It is the specification the driver in
`shared/device_drivers/awt/` follows, and the reference `scripts/awt_golden.py` runs with node.

`frames.jsonl`: one frame per line (`data_hex`, `note`). Until the first live uplink reaches
Protect, the frames are synthetic: built by `scripts/awt_golden.py` from the layout the codec
reads, with fixes in the south-east quadrant, where the codec's hemisphere test and the sign bits
agree (see the driver's module docstring). Recorded uplinks from the six devices of the BPC
application (L10966, L11478 to L11482) are added here with their origin as they come in.

`golden.json`: what the codec produces for every frame, written by the script; the test checks
the driver against it.
