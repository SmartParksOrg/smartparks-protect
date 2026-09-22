# OpenCollar Edge fixtures

`uplinks.jsonl`: one uplink per line with `f_port`, `data_hex` and the values the public decoder produces. Source: Smart Parks wiki, https://wiki.smartparks.org/devices/opencollar/lorawan_messages (fetched 2026-09-03), recorded on a RangerEdge hardware 1.4 with firmware 4.4 near Utrecht on 2023-11-30. The flash log example is the same page's port 29 example. Recorded uplinks from live devices are added here with a note of their origin as they come in.

The last two lines, ports 11 and 7, are **built, not recorded**: the wiki has no Bluetooth scan
example and no live collar in this project had scanning switched on when the driver was written
(2026-09-18, phase 30). They are composed to the layout of research sections 3.9 and 3.7 and are
worth exactly what the reference decoders say about them, which is what the golden test checks.
Replace them with recorded frames as soon as a collar reports a real scan; that is the gate C5
of the phase.

The port 15 line, the cardiac tag (CMDQ), is **built, not recorded** as well (2026-09-22, phase
34): no port 15 uplink has ever reached this project. It is composed to the layout of research
section 3.13 with 15 byte records, which is what every vendored decoder assumes, and holds three
sightings: two with a cardiac reading and one where the tag was heard and the heart was not. The
firmware's own two examples (`bt_cmdq/README.md`) are 13 byte records of firmware 6.1 to 6.8,
whose reference decoder lives in `smartparks-toolset` and is not vendored here, so those are
checked in `tests/shared/test_opencollar_cmdq.py` against the values that README prints. The
wiki's port 15 example cannot be used as it stands: its length byte counts the two header bytes,
which the wiki does throughout, so the frame declares 28 bytes and carries 26.

`docs/devices/opencollar-protocol-research.md` holds the full protocol study these fixtures come from.
