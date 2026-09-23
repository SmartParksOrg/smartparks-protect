import { describe, expect, it } from "vitest";

import {
  cardiacParameters,
  comparisonOf,
  documentOf,
  fixesPreset,
  formStateOfRun,
  grazingParameters,
  groupWithSubgroups,
  withGroupMembers,
  deviceSelection,
  devicePerformanceParameters,
  eventInside,
  farFromZero,
  intensityFeatures,
  isActive,
  isManagementUnit,
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
      strategy: true,
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
        new URLSearchParams(
          "entity=a&entity=b&range=7d&compare=previous&cell=50",
        ),
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
      methods: ["mcp", "kde", "akde_like", "clusters"],
      strategy: true,
    });
    expect(parameters).not.toHaveProperty("kde_bandwidth_m");
  });
  it("carries the cardiac method only when it differs from the defaults", () => {
    const plain = readFormState(new URLSearchParams("entity=a"));
    expect(writeFormState(plain).toString()).toBe("entity=a");
    const changed = readFormState(
      new URLSearchParams("entity=a&quiet_from=22&quiet_to=4&quantile=0.05"),
    );
    expect(changed.cardiac).toEqual({
      quietFrom: 22,
      quietTo: 4,
      quantile: 0.05,
      event: null,
      restless: 100,
    });
    // midnight is hour 0, which must survive the round trip as a real answer
    const midnight = readFormState(new URLSearchParams("entity=a&quiet_to=0"));
    expect(midnight.cardiac.quietTo).toBe(0);
  });
  it("builds the cardiac parameters from the form", () => {
    const now = new Date("2026-09-22T10:00:00Z");
    const state = readFormState(
      new URLSearchParams(
        "entity=a&entity=b&range=7d&quiet_from=22&quiet_to=4",
      ),
    );
    expect(cardiacParameters(state, now)).toMatchObject({
      entity_ids: ["a", "b"],
      quiet_from_hour: 22,
      quiet_to_hour: 4,
      resting_quantile: 0.1,
    });
    // no subject, no run
    expect(
      cardiacParameters(readFormState(new URLSearchParams("range=7d")), now),
    ).toBeNull();
  });
  it("carries the event and the restless threshold, and knows an event outside the period", () => {
    const now = new Date("2026-09-22T10:00:00Z");
    const inside = readFormState(
      new URLSearchParams(
        "entity=a&range=7d&event=2026-09-20T08:00:00Z&restless=120",
      ),
    );
    expect(cardiacParameters(inside, now)).toMatchObject({
      event_at: "2026-09-20T08:00:00.000Z",
      restless_activity: 120,
    });
    expect(eventInside(inside, now)).toBe(true);
    expect(writeFormState(inside).get("restless")).toBe("120");
    const before = readFormState(
      new URLSearchParams("entity=a&range=7d&event=2026-08-01T08:00:00Z"),
    );
    expect(eventInside(before, now)).toBe(false);
    // no event: nothing to be outside of, and no event in the parameters
    const none = readFormState(new URLSearchParams("entity=a&range=7d"));
    expect(eventInside(none, now)).toBe(true);
    expect(cardiacParameters(none, now)).not.toHaveProperty("event_at");
  });
  it("lets a line far above zero read its own range", () => {
    const line = (values: number[]) => ({
      key: "rhythm_temperature",
      kind: "line" as const,
      series: [{ data: values.map((v, i) => [i, v] as [number, number]) }],
    });
    expect(farFromZero(line([36.5, 37.2, 38.1]))).toBe(true);
    expect(farFromZero(line([2, 8, 30]))).toBe(false);
    expect(farFromZero({ ...line([36, 37]), kind: "bar" })).toBe(false);
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
    expect([...groupWithSubgroups(groups, "a")].sort()).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect([...groupWithSubgroups(groups, "d")]).toEqual(["d"]);
  });
  it("presets the fixes export to the subjects over the main period", () => {
    const document = {
      subjects: [
        { id: "a", name: "A" },
        { id: "b", name: "B" },
      ],
      periods: [
        {
          key: "comparison",
          time_from: "2026-08-01T00:00:00Z",
          time_to: "2026-08-31T00:00:00Z",
        },
        {
          key: "main",
          time_from: "2026-08-31T00:00:00Z",
          time_to: "2026-09-30T00:00:00Z",
        },
      ],
    } as unknown as Parameters<typeof fixesPreset>[0];
    expect(fixesPreset(document)).toEqual({
      dataset: "positions",
      format: "geojson",
      entityIds: ["a", "b"],
      from: "2026-08-31T00:00:00Z",
      to: "2026-09-30T00:00:00Z",
    });
  });
  it("keeps the grazing choices in the URL and builds the module's parameters", () => {
    const state = readFormState(
      new URLSearchParams(
        "entity=a&area=z1&area=z2&weighting=attribute&weight_key=lsu&compare=herd&herd_b=g2&absence=12",
      ),
    );
    expect(state.grazing).toEqual({
      areas: ["z1", "z2"],
      weighting: "attribute",
      weight_key: "lsu",
      herd_b: "g2",
      seasons: false,
      landscape: true,
      absence: 12,
      rest: 0,
    });
    expect(writeFormState(state).toString()).toBe(
      "entity=a&compare=herd&area=z1&area=z2&weighting=attribute&weight_key=lsu&herd_b=g2&absence=12",
    );
    const now = new Date("2026-09-14T10:17:42Z");
    expect(grazingParameters(state, ["b", "c"], now)).toMatchObject({
      entity_ids: ["a"],
      feature_ids: ["z1", "z2"],
      weighting: "attribute",
      weight_key: "lsu",
      herd_b_entity_ids: ["b", "c"],
      min_absence_hours: 12,
      rest_threshold_hours: 0,
      max_speed_mps: 15,
    });
    expect(
      grazingParameters(
        readFormState(new URLSearchParams("entity=a")),
        [],
        now,
      ),
    ).toBeNull();
  });
  it("recognises the management unit convention", () => {
    const feature = (attributes: unknown) =>
      ({ attributes }) as unknown as Parameters<typeof isManagementUnit>[0];
    expect(isManagementUnit(feature({ management: { unit: true } }))).toBe(
      true,
    );
    expect(isManagementUnit(feature({ management: { unit: "yes" } }))).toBe(
      false,
    );
    expect(isManagementUnit(feature({}))).toBe(false);
  });
  it("draws the intensity grid as squares with a share of the busiest cell", () => {
    const document = {
      summary: {
        intensity: {
          origin_lat: -19,
          origin_lon: 23.5,
          cell_m: 100,
          m_per_deg_lon: 105_000,
          areas: {
            z1: [
              [0, 0, 4],
              [1, 0, 2],
            ],
            z2: [],
          },
        },
      },
    } as unknown as Parameters<typeof intensityFeatures>[0];
    const features = intensityFeatures(document);
    expect(features).toHaveLength(2);
    expect(features[0].properties).toMatchObject({
      kind: "intensity",
      area_id: "z1",
      hours: 4,
      share: 1,
    });
    expect(features[1].properties?.share).toBe(0.5);
    const ring = (features[1].geometry as GeoJSON.Polygon).coordinates[0];
    expect(ring[0][0]).toBeCloseTo(23.5 + 100 / 105_000, 8);
    expect(ring[2][1]).toBeCloseTo(-19 + 100 / 111_320, 8);
    expect(
      intensityFeatures({ summary: {} } as unknown as Parameters<
        typeof intensityFeatures
      >[0]),
    ).toEqual([]);
  });
  it("fills the form from a run's parameters", () => {
    const base = readFormState(new URLSearchParams());
    const run = {
      parameters: {
        entity_ids: ["a", "b"],
        time_from: "2026-08-15T00:00:00Z",
        time_to: "2026-09-14T00:00:00Z",
        comparison: {
          time_from: "2026-07-16T00:00:00Z",
          time_to: "2026-08-15T00:00:00Z",
        },
        gap_hours: 6,
        cell_m: 105,
        methods: ["mcp"],
        feature_ids: ["z1"],
        weighting: "attribute",
        weight_key: "lsu",
        min_absence_hours: 12,
      },
    } as unknown as Parameters<typeof formStateOfRun>[0];
    const state = formStateOfRun(run, base);
    expect(state).toMatchObject({
      entities: ["a", "b"],
      range: "custom",
      from: "2026-08-15T00:00:00Z",
      to: "2026-09-14T00:00:00Z",
      compare: "previous",
      method: { gap: 6, cell: 105, methods: ["mcp"], speed_max: 15 },
      grazing: {
        areas: ["z1"],
        weighting: "attribute",
        weight_key: "lsu",
        absence: 12,
      },
    });
    expect(windowOf(state)).toEqual({
      time_from: "2026-08-15T00:00:00.000Z",
      time_to: "2026-09-14T00:00:00.000Z",
    });
  });
});

describe("groups on the forms", () => {
  it("joins the members of the chosen groups to the picks, once each, capped", () => {
    const groups = [
      { id: "a", parent_id: null },
      { id: "b", parent_id: "a" },
      { id: "c", parent_id: null },
    ] as Parameters<typeof withGroupMembers>[2];
    const items = [
      { id: "e1", group_id: "a" },
      { id: "e2", group_id: "b" },
      { id: "e3", group_id: "c" },
      { id: "e4", group_id: null },
    ];
    expect(withGroupMembers(["e4", "e2"], items, groups, ["a"], 25)).toEqual([
      "e4",
      "e2",
      "e1",
    ]);
    expect(withGroupMembers([], items, groups, ["c"], 25)).toEqual(["e3"]);
    expect(withGroupMembers([], items, groups, ["a", "c"], 2)).toEqual([
      "e1",
      "e2",
    ]);
    expect(withGroupMembers(["e4"], items, undefined, [], 25)).toEqual(["e4"]);
  });
  it("keeps the groups in the URL and counts them as input", () => {
    const state = readFormState(new URLSearchParams("group=a&group=b"));
    expect(state.groups).toEqual(["a", "b"]);
    expect(writeFormState(state).toString()).toBe("group=a&group=b");
  });
});

describe("the devices a performance form chooses", () => {
  const devices = [
    { id: "d1", device_type_id: "device", entity_id: "e1", group_id: "g1" },
    { id: "d2", device_type_id: "device", entity_id: "e2", group_id: null },
    { id: "d3", device_type_id: "tag", entity_id: "e3", group_id: "g1" },
    { id: "d4", device_type_id: "device", entity_id: null, group_id: null },
  ];
  const entities = [
    { id: "e1", entity_type_id: "pangolin" },
    { id: "e2", entity_type_id: "pangolin" },
    { id: "e3", entity_type_id: "rhino" },
  ];
  const types = [
    { id: "wildlife", parent_id: null },
    { id: "pangolin", parent_id: "wildlife" },
    { id: "rhino", parent_id: "wildlife" },
  ];
  const base = readFormState(new URLSearchParams());
  it("takes the devices tracking the chosen entity types, with the subtypes", () => {
    const pangolins = deviceSelection(
      { ...base, entityTypes: ["pangolin"] },
      devices,
      entities,
      undefined,
      types,
      100,
    );
    expect(pangolins.ids).toEqual(["d1", "d2"]);
    expect(pangolins.hasSources).toBe(true);
    const wildlife = deviceSelection(
      { ...base, entityTypes: ["wildlife"] },
      devices,
      entities,
      undefined,
      types,
      100,
    );
    expect(wildlife.ids).toEqual(["d1", "d2", "d3"]);
  });
  it("narrows a mixed selection to one device type and says what it left out", () => {
    const groups = [{ id: "g1", parent_id: null }] as Parameters<
      typeof deviceSelection
    >[3];
    const mixed = deviceSelection(
      { ...base, groups: ["g1"] },
      devices,
      entities,
      groups,
      types,
      100,
    );
    expect(mixed.ids).toEqual(["d1", "d3"]);
    const narrowed = deviceSelection(
      { ...base, groups: ["g1"], deviceType: "device" },
      devices,
      entities,
      groups,
      types,
      100,
    );
    expect(narrowed.ids).toEqual(["d1"]);
    expect(narrowed.excludedByType).toBe(1);
    const none = deviceSelection(
      { ...base, entities: ["e3"], deviceType: "device" },
      devices,
      entities,
      groups,
      types,
      100,
    );
    expect(none.ids).toEqual([]);
    expect(none.hasSources).toBe(true);
    const now = new Date("2026-09-16T10:00:00Z");
    expect(
      devicePerformanceParameters(
        { ...base, entities: ["e3"], deviceType: "device" },
        now,
        none,
      ),
    ).toBeNull();
    expect(
      devicePerformanceParameters({ ...base, groups: ["g1"] }, now, mixed)
        ?.device_ids,
    ).toEqual(["d1", "d3"]);
    // every device of one type stays the server's to resolve
    const all = deviceSelection(
      { ...base, allDevices: true, deviceType: "tag" },
      devices,
      entities,
      groups,
      types,
      100,
    );
    expect(
      devicePerformanceParameters(
        { ...base, allDevices: true, deviceType: "tag" },
        now,
        all,
      ),
    ).toMatchObject({ device_type_id: "tag" });
  });
});
