# Features: sites, zones, geofences, routes and fence lines

A feature is a shape a project keeps on its map: a site (a point), a zone or a geofence (an
area), a route (a line) or a fence line (a line with a status, see [fences and
traps](../devices/fences-and-traps.md)). Rules use them: a geofence starts an exit rule, a site
or a zone a proximity rule, and the grazing analysis reads zones and geofences as its areas.
Project admins manage them under Project admin, Features, and on the live map with the draw
tool. There are three ways to make one.

## Draw

"New feature" on the Features page opens a map over what the project already has; the draw
tool on the live map does the same in place. A site is one click, a route or a fence line a
sequence of clicks, an area a closed sequence, and a circle is dragged from its centre. A
finished shape stays editable until it is saved: drag a vertex to move it, drag a midpoint to
add one, Delete removes one. The bar shows the length, area or radius while you draw.

## Import a file

"Import" on the Features page reads a file people already have: a shapefile (the `.shp`,
`.shx`, `.dbf` and `.prj` files zipped together), KML, KMZ, GPX or GeoJSON. The file is read in
the browser and never uploaded; every shape it holds is shown on a map and listed with a
checkbox, a name taken from the file where it has one, and a type: a polygon becomes a zone
(or a geofence), a line a route (or a fence line), a point a site. Keep the shapes you want and
import them; each becomes a feature of the project with the file's name kept in its
attributes. A file holds at most 200 shapes at once; altitudes are dropped, and a shape made
of several parts is imported as one feature per part. A shapefile in a projection other than
WGS 84 is reprojected when its `.prj` file is in the zip.

## Propose an area from the map

Most areas are already marked on the ground: a block between two roads and a river, a fenced
camp, a forest or a lake the map knows. Under "New feature" for a zone or a geofence, and in
the live map's draw tool, "Propose" turns a gesture into candidates instead of a vertex.

**A click** reads a box of 1.5 km around the point; **dragging** reads the box you draw. Either
way the box is on the map before it is read and its size is named in square kilometres, so
what is being asked for is never a guess. The server joins OpenStreetMap's roads, tracks,
rivers, fences and railways inside it into the faces they enclose, and answers the face that
contains the middle of the box together with every OpenStreetMap area that contains it (a
protected area, a forest, a lake, a landuse), smallest first, with its size. The ways people
walk on — footpaths, paths, steps, cycleways and bridleways — do not cut the face: a dune
reserve is threaded with them, and a block cut by every one of them is a fragment of a few
hectares rather than a zone.

The candidates show as faint outlines; "Use" puts one in the editor and brings it into view,
where it is adjusted like any drawn shape, named and saved; an area OpenStreetMap names fills
the name in.

A read takes seconds, so while one is running the bar shows a spinner with **Cancel**, and
another click or drag is ignored rather than starting a second read — a second read is what
makes the public server refuse the first. The map keeps panning and zooming throughout.

A box larger than **25 km²** is refused before anything is sent, and one over 9 km² says it may
take a while. Those are not arbitrary: a box of 9 km² over the Kennemer dunes answers in about
3 seconds with a megabyte, one of 100 km² takes 11 seconds and 14 megabytes, and the same box
over a Namibian reserve comes back as a refusal. For a whole reserve, find it by name instead —
that reads only the named areas and stays fast whatever the size.

### Or find it by name

Under the same Propose, a box takes a name: type "Kraansvlak" and the OpenStreetMap areas whose
name holds that text, in the part of the map on screen, come back as the same candidates, best
match first. It is the way in when you know what the area is called and not exactly where its
edge runs — and it does not depend on clicking the right spot. Only areas answer, never a
street or a building of the same name. Move the map over the reserve first; if the view is
wider than about 150 km, its middle is searched and the list says so.

What to expect:

- Where OpenStreetMap has the tracks and streams of the reserve, the enclosed face is the
  block you meant. Where it has one road through the whole park, the face is large and marked
  "cut by the edge of the search box", which means the box and not the landscape closed it;
  draw that one, or start from a smaller area OpenStreetMap already holds.
- The data is OpenStreetMap's, under the ODbL, and the attribution is shown under the list. A
  feature made from it is yours to edit; nothing links back.
- The server asks the public Overpass API by default (`OVERPASS_URL`); a server that clicks a
  lot can point that at its own instance. The public service refuses bursts: a refused call is
  made once more after a couple of seconds, and if that is refused too the interface says so.
  Click again, or try a smaller radius.
- Nothing is proposed from satellite imagery. Where OpenStreetMap has nothing, the shape is
  drawn by hand.

## Several areas as one zone

A zone a reserve works with is often several areas on the map: Zuid-Kennemerland, Duin en
Kruidberg, Midden-Herenduin and Heerenduinen are one dune area to the people who patrol them.
They are combined into one feature, which rules, the grazing analysis and the map then read as
a single zone.

- **While proposing.** Tick as many candidates as you want in the Propose list — after a name
  search or a click — and "Use N areas as one zone" puts their union in the editor, ready to be
  named and saved.
- **From the features you already have.** Tick the rows on the Features page and "Combine N
  into one zone" shows the union over its parts with its size, takes a name and a type, and
  saves it. The parts stay unless you ask for them to be removed with it.

Ground that two parts share is counted once, so the combined zone's hectares are the ground it
covers, not the sum of its parts. If you keep the parts as zones of their own **and** the
combined zone, the grazing analysis reports both, and the same ground appears in both rows.

A zone whose parts do not touch is kept as one feature in several pieces, and a zone with an
enclave inside it keeps its hole; both work everywhere, but the drawing editor holds one ring
at a time, so it cannot correct them vertex by vertex. The interface says so when it happens.
