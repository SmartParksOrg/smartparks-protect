import { describe, expect, it } from "vitest";

import {
  axisOf,
  isoToWall,
  layOut,
  sharedBoundaries,
  wallToIso,
} from "@/lib/assignments";

const JOINED = "2026-07-16T12:53:20.000Z";
const TRANSFER = "2026-10-26T15:21:13.517Z";
const now = new Date("2026-10-26T17:00:00.000Z");

const projects = [
  { id: "sp", valid_from: JOINED, valid_to: TRANSFER },
  { id: "lp0", valid_from: TRANSFER, valid_to: null },
];
const entities = [
  { id: "tim", valid_from: JOINED, valid_to: TRANSFER },
  { id: "sp051307", valid_from: TRANSFER, valid_to: null },
];

describe("the timeline's lanes", () => {
  it("lays both lanes on one axis from the first start to now", () => {
    const axis = axisOf([...projects, ...entities], now);
    expect(axis).not.toBeNull();
    const laid = layOut(projects, axis!, now);
    expect(laid[0].left).toBe(0);
    expect(laid[1].left).toBeCloseTo(laid[0].width, 5);
    // the second row is a few hours of three months: a sliver of the minimum width
    expect(laid[1].width).toBe(0.5);
    expect(laid[0].width).toBeGreaterThan(99);
    expect(laid[1].current).toBe(true);
    expect(laid[0].current).toBe(false);
  });

  it("has no axis without rows and gives a momentary row a sliver", () => {
    expect(axisOf([], now)).toBeNull();
    const moment = [{ id: "x", valid_from: TRANSFER, valid_to: TRANSFER }];
    const axis = axisOf(moment, now)!;
    expect(layOut(moment, axis, now)[0].width).toBe(0.5);
  });
});

describe("shared boundaries", () => {
  it("finds the transfer where a project edge and an entity edge meet, never the first start", () => {
    const shared = sharedBoundaries(projects, entities);
    expect(shared).toEqual([
      {
        instant: TRANSFER,
        projectAssignmentId: "lp0",
        projectEdge: "start",
        entityAssignmentId: "sp051307",
        entityEdge: "start",
      },
    ]);
  });

  it("takes the ending row when nothing starts at the instant", () => {
    const ended = [{ id: "sp", valid_from: JOINED, valid_to: TRANSFER }];
    const released = [{ id: "tim", valid_from: JOINED, valid_to: TRANSFER }];
    expect(sharedBoundaries(ended, released)).toEqual([
      {
        instant: TRANSFER,
        projectAssignmentId: "sp",
        projectEdge: "end",
        entityAssignmentId: "tim",
        entityEdge: "end",
      },
    ]);
  });

  it("finds nothing when the edges differ", () => {
    const later = [{ id: "e", valid_from: "2026-10-26T16:00:00.000Z", valid_to: null }];
    expect(sharedBoundaries(projects, later)).toEqual([]);
  });
});

describe("wall-clock text in a timezone", () => {
  it("round-trips an instant through Amsterdam and Windhoek", () => {
    // summer time in Amsterdam (it ends on the 25th, when 14:13Z reads 15:13), always +2 in Windhoek
    const iso = "2026-10-20T14:13:52.000Z";
    expect(isoToWall(iso, "Europe/Amsterdam")).toBe("2026-10-20T16:13:52");
    expect(wallToIso("2026-10-20T16:13:52", "Europe/Amsterdam")).toBe(iso);
    expect(isoToWall("2026-10-25T14:13:52.000Z", "Europe/Amsterdam")).toBe("2026-10-25T15:13:52");
    expect(wallToIso("2026-10-25T15:13:52", "Europe/Amsterdam")).toBe("2026-10-25T14:13:52.000Z");
    expect(isoToWall(iso, "Africa/Windhoek")).toBe("2026-10-20T16:13:52");
    expect(wallToIso("2026-10-20T16:13:52", "UTC")).toBe("2026-10-20T16:13:52.000Z");
  });

  it("takes a text without seconds and refuses one that is not a date", () => {
    expect(wallToIso("2026-10-25T16:13", "UTC")).toBe("2026-10-25T16:13:00.000Z");
    expect(wallToIso("yesterday", "UTC")).toBeNull();
    expect(wallToIso("", "UTC")).toBeNull();
  });
});
