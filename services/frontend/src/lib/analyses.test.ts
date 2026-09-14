import { describe, expect, it } from "vitest";

import {
  comparisonOf,
  documentOf,
  groupWithSubgroups,
  isActive,
  movementParameters,
  readFormState,
  subjectSummary,
  windowOf,
  writeFormState,
} from "./analyses";

describe("analysis form state", () => {
  it("round-trips through the URL and writes only what differs from the defaults", () => {
    const state = readFormState(
      new URLSearchParams("entity=a&entity=b&range=7d&compare=previous&run=r1"),
    );
    expect(state.entities).toEqual(["a", "b"]);
    expect(state.range).toBe("7d");
    expect(writeFormState(state).toString()).toBe(
      "entity=a&entity=b&range=7d&compare=previous&run=r1",
    );
    expect(
      writeFormState(readFormState(new URLSearchParams())).toString(),
    ).toBe("");
  });
  it("gives a window for a preset and a comparison right before it", () => {
    const now = new Date("2026-09-14T10:17:42Z");
    const window = windowOf(
      readFormState(new URLSearchParams("range=7d")),
      now,
    );
    expect(window).toEqual({
      time_from: "2026-09-07T10:17:00.000Z",
      time_to: "2026-09-14T10:17:00.000Z",
    });
    const before = comparisonOf(
      readFormState(new URLSearchParams("range=7d&compare=previous")),
      window,
    );
    expect(before).toEqual({
      time_from: "2026-08-31T10:17:00.000Z",
      time_to: "2026-09-07T10:17:00.000Z",
    });
    expect(
      windowOf(readFormState(new URLSearchParams("range=custom")), now),
    ).toBeNull();
  });
  it("reads a result document only at the version it knows", () => {
    expect(documentOf(undefined)).toBeNull();
    expect(documentOf({ result: { version: 2 } } as never)).toBeNull();
    expect(
      documentOf({ result: { version: 1, module: "movement" } } as never)
        ?.module,
    ).toBe("movement");
    expect(isActive("running")).toBe(true);
    expect(isActive("completed")).toBe(false);
  });
  it("carries the method options only when they differ from the defaults", () => {
    const state = readFormState(
      new URLSearchParams("entity=a&gap=6&methods=mcp&kde=250"),
    );
    expect(state.method).toEqual({
      gap: 6,
      speed_max: 15,
      cell: 100,
      methods: ["mcp"],
      kde_bandwidth: 250,
    });
    expect(writeFormState(state).toString()).toBe(
      "entity=a&gap=6&methods=mcp&kde=250",
    );
    expect(
      readFormState(new URLSearchParams("gap=abc&methods=nope")).method,
    ).toMatchObject({ gap: 4, methods: [] });
  });
  it("builds the module's parameters from the form", () => {
    const now = new Date("2026-09-14T10:17:42Z");
    expect(
      movementParameters(readFormState(new URLSearchParams("range=7d")), now),
    ).toBeNull();
    const parameters = movementParameters(
      readFormState(
        new URLSearchParams("entity=a&entity=b&range=7d&compare=previous&cell=50"),
      ),
      now,
    );
    expect(parameters).toMatchObject({
      entity_ids: ["a", "b"],
      time_from: "2026-09-07T10:17:00.000Z",
      time_to: "2026-09-14T10:17:00.000Z",
      comparison: {
        time_from: "2026-08-31T10:17:00.000Z",
        time_to: "2026-09-07T10:17:00.000Z",
      },
      gap_hours: 4,
      max_speed_mps: 15,
      cell_m: 50,
      methods: ["mcp", "kde", "clusters"],
    });
    expect(parameters).not.toHaveProperty("kde_bandwidth_m");
  });
  it("reads a subject's figures out of a nested summary", () => {
    const document = {
      summary: { main: { a: { distance_km: 3 } } },
    } as unknown as Parameters<typeof subjectSummary>[0];
    expect(subjectSummary(document, "main", "a")).toEqual({ distance_km: 3 });
    expect(subjectSummary(document, "comparison", "a")).toBeNull();
    expect(subjectSummary(document, "main", "b")).toBeNull();
  });
  it("collects a group with the groups under it", () => {
    const groups = [
      { id: "a", parent_id: null },
      { id: "b", parent_id: "a" },
      { id: "c", parent_id: "b" },
      { id: "d", parent_id: null },
    ] as Parameters<typeof groupWithSubgroups>[0];
    expect([...groupWithSubgroups(groups, "a")].sort()).toEqual(["a", "b", "c"]);
    expect([...groupWithSubgroups(groups, "d")]).toEqual(["d"]);
  });
});
