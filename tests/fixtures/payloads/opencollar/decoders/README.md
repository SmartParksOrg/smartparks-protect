# Reference decoders

The firmware's own decoders as published in `SmartParksOrg/raw_logs_decoder` (MIT, see
`LICENSE`), commit 9b10e024397ca85488a14e0175732c64ca7ac6ee of 2026-07-08 (app v1.43):
`ttn_decoder-v7.2.0.js` (firmware 7.1.0 to 7.3.0), `ttn_decoder-v6.15.1.js` (6.15.0 to
6.16.3) and `ttn_decoder-v6.11.2.js` (6.9.0 to 6.14.3). They are the oracle of the golden
test: `scripts/opencollar_golden.py` runs every recorded frame through each decoder (node) and
writes `../golden.json`; `tests/shared/test_opencollar_golden.py` checks our driver, with the
layout of the matching firmware, against those outputs. Regenerate the golden file when a
frame is added or a decoder is updated; the test itself needs no node.
