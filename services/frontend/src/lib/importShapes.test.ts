import { describe, expect, it } from "vitest";

import { shapesOfFile, shapesOfGeoJson } from "@/lib/importShapes";

describe("shapesOfGeoJson", () => {
  it("reads a collection, names shapes from their properties and types them by geometry", () => {
    const shapes = shapesOfGeoJson({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { NAME: "North block" },
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [4.6, 52.5],
                [4.61, 52.5],
                [4.61, 52.51],
                [4.6, 52.5],
              ],
            ],
          },
        },
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: [
              [4.6, 52.5, 12],
              [4.61, 52.51, 13],
            ],
          },
        },
        { type: "Feature", properties: null, geometry: null },
      ],
    });
    expect(shapes.map((s) => [s.name, s.featureType])).toEqual([
      ["North block", "zone"],
      ["Shape 2", "route"],
    ]);
    // the altitude is dropped
    expect((shapes[1].geometry as GeoJSON.LineString).coordinates[0]).toEqual([4.6, 52.5]);
  });

  it("splits a geometry collection into one shape per part", () => {
    const shapes = shapesOfGeoJson({
      type: "Feature",
      properties: { name: "Camp" },
      geometry: {
        type: "GeometryCollection",
        geometries: [
          { type: "Point", coordinates: [4.6, 52.5] },
          { type: "Point", coordinates: [4.7, 52.6] },
        ],
      },
    });
    expect(shapes.map((s) => s.name)).toEqual(["Camp (1)", "Camp (2)"]);
    expect(shapes.every((s) => s.featureType === "site")).toBe(true);
  });
});

describe("shapesOfFile", () => {
  it("reads a KML file with a placemark polygon", async () => {
    const text = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Waterhole</name>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
4.60,52.50,0 4.61,52.50,0 4.61,52.51,0 4.60,52.50,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>`;
    const shapes = await shapesOfFile(new File([text], "areas.kml"));
    expect(shapes).toHaveLength(1);
    expect(shapes[0].name).toBe("Waterhole");
    expect(shapes[0].geometry.type).toBe("Polygon");
    expect((shapes[0].geometry as GeoJSON.Polygon).coordinates[0][0]).toEqual([4.6, 52.5]);
  });

  it("reads a GPX track as a route", async () => {
    const text = `<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<trk><name>Patrol</name><trkseg><trkpt lat="52.5" lon="4.6"/><trkpt lat="52.51" lon="4.61"/></trkseg></trk></gpx>`;
    const shapes = await shapesOfFile(new File([text], "patrol.gpx"));
    expect(shapes.map((s) => [s.name, s.featureType, s.geometry.type])).toEqual([
      ["Patrol", "route", "LineString"],
    ]);
  });

  it("refuses a file type it does not know", async () => {
    await expect(shapesOfFile(new File(["x"], "areas.dxf"))).rejects.toThrow("Unknown file type");
  });
});
