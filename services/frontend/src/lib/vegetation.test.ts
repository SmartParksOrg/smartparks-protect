import { describe, expect, it } from "vitest";

import { vegetationBreaks, vegetationFeatures } from "@/lib/analyses";
import type { ResultDocument } from "@/lib/analyses";

/** A document holding only what the vegetation mosaic reads. */
function documentWith(values: number[]): ResultDocument {
  return {
    summary: {
      vegetation: {
        origin_lat: 52.35,
        origin_lon: 5.5,
        cell_m: 200,
        m_per_deg_lon: 68_000,
        areas: { a: values.map((v, i) => [i, 0, v]) },
      },
    },
    periods: [],
    subjects: [],
    tables: [],
    charts: [],
    warnings: [],
    geometries: {},
  } as unknown as ResultDocument;
}

describe("the vegetation mosaic", () => {
  it("gives every colour a fifth of the cells, whatever the spread", () => {
    // the shape of the Horsterwold run of 2026-09-18: a long green plateau and a few low
    // outliers, which a plain low-to-high scale drew as one green
    const values = [
      0.4, 0.52, 0.61, 0.72, 0.79,
      ...Array.from({ length: 95 }, (_, i) => 0.85 + i * 0.0005),
    ];
    const features = vegetationFeatures(documentWith(values));
    expect(features).toHaveLength(100);
    const levels = features.map((f) => Number(f.properties?.level));
    // five classes at 0.2, 0.4, 0.6, 0.8, and each holds about a fifth
    const classOf = (level: number) => Math.min(4, Math.floor(level * 5));
    const counts = [0, 0, 0, 0, 0];
    for (const level of levels) counts[classOf(level)] += 1;
    for (const count of counts) expect(count).toBeGreaterThanOrEqual(15);
    expect(Math.max(...counts) - Math.min(...counts)).toBeLessThanOrEqual(10);
  });

  it("keeps the lowest cell lowest and the highest highest", () => {
    const features = vegetationFeatures(documentWith([0.9, 0.4, 0.7]));
    const byNdvi = features
      .map((f) => ({
        ndvi: Number(f.properties?.ndvi_mean),
        level: Number(f.properties?.level),
      }))
      .sort((a, b) => a.ndvi - b.ndvi);
    expect(byNdvi.map((c) => c.level)).toEqual([0, 0.5, 1]);
  });

  it("names the index each colour starts at", () => {
    const breaks = vegetationBreaks(documentWith([0.4, 0.5, 0.6, 0.7, 0.8]));
    expect(breaks).toEqual([0.4, 0.5, 0.6, 0.7, 0.8]);
  });

  it("holds one colour when every cell reads the same", () => {
    const features = vegetationFeatures(documentWith([0.8, 0.8, 0.8]));
    expect(features.map((f) => Number(f.properties?.level))).toEqual([0, 0, 0]);
  });

  it("draws nothing without a mosaic", () => {
    expect(vegetationFeatures({ summary: {} } as ResultDocument)).toEqual([]);
    expect(vegetationBreaks({ summary: {} } as ResultDocument)).toBeNull();
  });
});
