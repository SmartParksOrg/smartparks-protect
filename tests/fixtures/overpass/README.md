# Overpass fixtures

`pwn_dunes.json` is a real answer of the public Overpass API (overpass-api.de, Overpass API
0.7.62, OpenStreetMap data of 2026-09-21, ODbL) to the query `shared.domain.areas.overpass_query`
builds, over the box 52.5280 to 52.5330 north and 4.6060 to 4.6150 east: the PWN dunes near
Castricum, where the project's Bluetooth scanners stand. Captured on 2026-09-21 with curl and
trimmed by hand the same day: relations with more than 1,500 points were dropped, the `nodes`
lists and member `ref`s removed, coordinates rounded to six decimals. Thirteen elements remain:
three cycleways and paths, three landuse and three natural ways, one boundary way, and three
natural multipolygon relations.
