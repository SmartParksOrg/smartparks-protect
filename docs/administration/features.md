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
the live map's draw tool, "Propose" turns a click into candidates instead of a vertex: the
server reads OpenStreetMap's roads, paths, rivers, fences and railways in a box of 1.5 km
around the click, joins them into the faces they enclose, and answers the face that contains
the point together with every OpenStreetMap area that contains it (a protected area, a forest,
a lake, a landuse), smallest first, with its size. The candidates show as faint outlines;
"Use" puts one in the editor and brings it into view, where it is adjusted like any drawn shape, named and saved; an area OpenStreetMap names fills the name in.

What to expect:

- Where OpenStreetMap has the tracks and streams of the reserve, the enclosed face is the
  block you meant. Where it has one road through the whole park, the face is large and marked
  "cut by the edge of the search box", which means the box and not the landscape closed it;
  draw that one, or start from a smaller area OpenStreetMap already holds.
- The data is OpenStreetMap's, under the ODbL, and the attribution is shown under the list. A
  feature made from it is yours to edit; nothing links back.
- The server asks the public Overpass API by default (`OVERPASS_URL`); a server that clicks a
  lot can point that at its own instance. The public service refuses bursts, and the interface
  says so when it does.
- Nothing is proposed from satellite imagery. Where OpenStreetMap has nothing, the shape is
  drawn by hand.
