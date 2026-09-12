# 0026. One drawing engine for draw and measure, and a circle as a polygon that remembers its centre and radius

Date: 2026-09-12

Status: accepted

## Context

The live map had a Draw tool for project admins and a Measure tool for everyone (decisions D139 and D141), both on terra-draw. On a phone the first tap showed no marker, the distance appeared only when the shape was finished, a closed shape could not be adjusted before saving, and there was no circle, which is the natural shape for a geofence around a water point. The controls around them had grown by accretion: MapLibre's zoom and locate buttons in another size above our strip, terrain away from the base map, buttons for tracks and heatmaps standing with nothing to show.

## Decision

Draw and Measure stay two buttons on one engine (decision D171): terra-draw's line and polygon modes run with coordinate markers and editable vertices, the session reports the shape in progress on every change so the bar measures it live, and a circle mode joins point, line and polygon. Measure ends with Done and keeps nothing; Draw ends with Save as feature. A circle is a polygon that remembers its centre and radius (decision D172): it is saved as a 64-point polygon feature with `shape: circle`, `centre` and `radius_m` in the feature's attributes, so the rules' geofence and proximity checks, the exports and every integration keep reading a polygon, and the panel names the radius. The map's controls are our own (decisions D173 and D174): a second strip at the bottom right holds zoom in, zoom out, reset north and a Locate toggle that follows the browser's position until a pan or a second press; MapLibre's navigation and geolocate controls are gone, so every button on the map has one size and style; the Layers button is the one filled button, top left, terrain sits under the base map, and the Tracks and Heatmaps buttons exist only while a track or a heatmap is on.

## Alternatives considered

- One tool with a "keep it" switch instead of two buttons: the intent (a measurement nobody keeps versus a feature the project keeps) is clearer as two buttons, and the permission differs.
- A circle feature type with its own geometry (centre and radius): every reader of features, the rules, the exports and the integrations would learn a second geometry; a polygon with two attributes changes nothing downstream.
- Keeping MapLibre's controls and restyling them: their size and placement are the library's, and the Locate control's states could not carry our labels.

## Consequences

A ranger sees a marker at the first tap and the running length while the finger moves; a circle drawn from a water point becomes a geofence with its radius named. A circle edited vertex by vertex stops being a circle: the attributes stay, the panel keeps naming the radius until the polygon is saved again by hand, which is acceptable for now. The control strip is the one place for map tools; a new tool joins it as a `StripItem`.
