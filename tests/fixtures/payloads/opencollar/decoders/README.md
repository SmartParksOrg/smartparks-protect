# Reference decoders

The firmware's own decoders as published in `SmartParksOrg/raw_logs_decoder` (MIT, see
`LICENSE`), commit 9b10e024397ca85488a14e0175732c64ca7ac6ee of 2026-07-08 (app v1.43):
`ttn_decoder-v7.2.0.js` (firmware 7.1.0 to 7.3.0), `ttn_decoder-v6.15.1.js` (6.15.0 to
6.16.3) and `ttn_decoder-v6.11.2.js` (6.9.0 to 6.14.3). They are the oracle of the golden
test: `scripts/opencollar_golden.py` runs every recorded frame through each decoder (node) and
writes `../golden.json`; `tests/shared/test_opencollar_golden.py` checks our driver, with the
layout of the matching firmware, against those outputs. Regenerate the golden file when a
frame is added or a decoder is updated; the test itself needs no node.

`ttn_decoder-lp0-7bae042.js` is `scripts/ttn_decoder.js` of the firmware repository
`SmartParksOrg/smartparks-opencollar-edge-fw` at commit 7bae042 (branch
`fix/existing-lp0-implementation`, 2026-10-20, unreleased firmware 8.1): the decoder of the
offload station's port 23 report (phase 42, decision D323) in its versions 1 (99 bytes), 2
(104 bytes, the card's capacity and free share) and 3 (the same 104 bytes with the
`sd_card_missing` and `sdfs_error` status bits, decision D345). It replaced the copy of commit
5ff74907 (2026-10-15, version 1 alone). `tests/shared/test_opencollar_lp0_statistics.py` runs
it with node, when node is on the path, over constructed reports of every version and compares
our driver's reading; no recorded port 23 frame exists yet. It is not part of `golden.json`.
