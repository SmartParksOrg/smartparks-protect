# Overpass fixtures

`pwn_dunes.json` is a real answer of the public Overpass API (overpass-api.de, Overpass API
0.7.62, OpenStreetMap data of 2026-09-21, ODbL) to the query `shared.domain.areas.overpass_query`
builds, over the box 52.5280 to 52.5330 north and 4.6060 to 4.6150 east: the PWN dunes near
Castricum, where the project's Bluetooth scanners stand. Captured on 2026-09-21 with curl and
trimmed by hand the same day: relations with more than 1,500 points were dropped, the `nodes`
lists and member `ref`s removed, coordinates rounded to six decimals. Thirteen elements remain:
three cycleways and paths, three landuse and three natural ways, one boundary way, and three
natural multipolygon relations.

`kraansvlak_name.json` is a real answer of the same server to the query
`shared.domain.areas.name_query` builds for "Kraansvlak" over the Kennemer dunes
(52.30 to 52.55 north, 4.40 to 4.75 east), captured on 2026-09-21 and trimmed the same
way: one element, way 1018618514 `leisure=nature_reserve` "Het Kraansvlak", 285 points,
the tags cut to the five that matter. It is the area Tim looked for on openstreetmap.org
and could not find by clicking (decision D273).
