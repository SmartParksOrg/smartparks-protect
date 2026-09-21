import { describe, expect, it } from "vitest";

import {
  areaKm2,
  boxAround,
  boxOf,
  DEFAULT_REACH_M,
  MAX_READ_KM2,
  readVerdict,
  WARN_READ_KM2,
} from "@/components/map/proposeBox";

describe("the ground a proposal reads (decision D277)", () => {
  it("makes a box of the reach to each side of a click", () => {
    const box = boxAround(4.61, 52.53);
    expect(areaKm2(box)).toBeCloseTo(9, 0); // three kilometres by three
    expect((box.west + box.east) / 2).toBeCloseTo(4.61, 6);
    expect((box.south + box.north) / 2).toBeCloseTo(52.53, 6);
    expect(areaKm2(boxAround(4.61, 52.53, DEFAULT_REACH_M))).toBeCloseTo(
      areaKm2(box),
      6,
    );
  });

  it("takes a drag from any corner", () => {
    const one = boxOf([4.65, 52.56], [4.6, 52.52]);
    const other = boxOf([4.6, 52.52], [4.65, 52.56]);
    expect(one).toEqual(other);
    expect(one.west).toBe(4.6);
    expect(one.north).toBe(52.56);
  });

  it("warns above the warning size and refuses above the limit", () => {
    const small = readVerdict(boxAround(4.61, 52.53, 700));
    expect(small.warn).toBe(false);
    expect(small.tooLarge).toBe(false);

    const large = readVerdict(boxAround(4.61, 52.53, 2000));
    expect(large.km2).toBeGreaterThan(WARN_READ_KM2);
    expect(large.warn).toBe(true);
    expect(large.tooLarge).toBe(false);

    const refused = readVerdict(boxOf([4.4, 52.3], [4.75, 52.55]));
    expect(refused.km2).toBeGreaterThan(MAX_READ_KM2);
    expect(refused.tooLarge).toBe(true);
  });

  it("measures a box the same way near the equator and far from it", () => {
    // a degree of longitude is half as wide at 60 north as at the equator
    const atTheEquator = areaKm2(boxOf([0, 0], [0.1, 0.1]));
    const farNorth = areaKm2(boxOf([0, 60], [0.1, 60.1]));
    expect(farNorth).toBeLessThan(atTheEquator);
    expect(farNorth / atTheEquator).toBeCloseTo(0.5, 1);
  });
});
