import { describe, expect, it } from "vitest";

import { circleRing, distanceMetres, formatArea, formatLength, lengthMetres, measure, polygonCentre, ringAreaSquareMetres } from "@/lib/geodesy";

describe("geodesy", () => {
  it("measures distances against known values", () => {
    // one degree of longitude at the equator, about 111.2 km
    expect(distanceMetres([0, 0], [1, 0])).toBeCloseTo(111_195, -1);
    // Amsterdam Centraal to Utrecht Centraal, about 35 km
    expect(distanceMetres([4.9003, 52.3791], [5.1101, 52.0894])).toBeCloseTo(
      35_100,
      -3,
    );
    expect(
      lengthMetres([
        [0, 0],
        [1, 0],
        [1, 1],
      ]),
    ).toBeCloseTo(111_195 * 2, -3);
  });

  it("measures the area of a square near the equator and closes an open ring", () => {
    // a 1 by 1 degree square at the equator is about 12,364 km²
    const open: [number, number][] = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];
    const closed: [number, number][] = [...open, [0, 0]];
    expect(ringAreaSquareMetres(open) / 1e6).toBeCloseTo(12_364, -1);
    expect(ringAreaSquareMetres(closed)).toBe(ringAreaSquareMetres(open));
    expect(
      ringAreaSquareMetres([
        [0, 0],
        [1, 0],
      ]),
    ).toBe(0);
    // a 100 m by 100 m square in the Netherlands is a hectare
    const lat = 52;
    const dLat = 100 / 110_574;
    const dLon = 100 / (111_320 * Math.cos((lat * Math.PI) / 180));
    const hectare: [number, number][] = [
      [5, lat],
      [5 + dLon, lat],
      [5 + dLon, lat + dLat],
      [5, lat + dLat],
    ];
    expect(ringAreaSquareMetres(hectare)).toBeCloseTo(10_000, -2);
  });

  it("reads lengths and areas the way a person says them", () => {
    expect(formatLength(842.4)).toBe("842 m");
    expect(formatLength(1234)).toBe("1.23 km");
    expect(formatLength(12_345)).toBe("12.3 km");
    expect(formatArea(950)).toBe("950 m²");
    expect(formatArea(25_000)).toBe("2.50 ha");
    expect(formatArea(3_400_000)).toBe("3.40 km²");
  });

  it("measures a geometry by its type", () => {
    expect(measure(null)).toEqual({});
    expect(measure({ type: "Point", coordinates: [0, 0] })).toEqual({});
    expect(
      measure({
        type: "LineString",
        coordinates: [
          [0, 0],
          [1, 0],
        ],
      }).length_m,
    ).toBeCloseTo(111_195, -1);
    const polygon = measure({
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 1],
          [0, 0],
        ],
      ],
    });
    expect(polygon.area_m2! / 1e6).toBeCloseTo(12_364, -1);
    expect(polygon.length_m).toBeCloseTo(111_195 * 4, -3);
  });
});

describe("circleRing", () => {
  it("draws a closed ring at the radius around the centre", () => {
    const centre: [number, number] = [31.5, -24.9];
    const ring = circleRing(centre, 500, 32);
    expect(ring).toHaveLength(33);
    expect(ring[0]).toEqual(ring[32]);
    for (const point of ring) expect(distanceMetres(centre, point)).toBeCloseTo(500, 0);
    const [lon, lat] = polygonCentre(ring);
    expect(lon).toBeCloseTo(31.5, 4);
    expect(lat).toBeCloseTo(-24.9, 4);
  });
});

