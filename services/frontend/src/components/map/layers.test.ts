import { describe, expect, it } from "vitest";

import {
  BASEMAP_SOURCE_IDS,
  SOURCES,
  assignTrackColors,
  bindEntityClicks,
  bindEventClicks,
  bindFeatureClicks,
  bindGatewayClicks,
  bindTrackPointClicks,
  trackColor,
  trackPointKey,
} from "@/components/map/layers";

type Listener = (e: unknown) => void;

/** A map that records layer listeners and answers what lies under a click, enough to prove
 * binding and unbinding pair up and that a handler yields to what is drawn over it. */
function fakeMap(under: string[] = []) {
  const bound = new Map<string, Listener[]>();
  const map = {
    on: (type: string, layer: string, listener: Listener) => {
      const key = `${type}:${layer}`;
      bound.set(key, [...(bound.get(key) ?? []), listener]);
    },
    off: (type: string, layer: string, listener: Listener) => {
      const key = `${type}:${layer}`;
      bound.set(
        key,
        (bound.get(key) ?? []).filter((l) => l !== listener),
      );
    },
    // every layer the style knows: the ones bound plus whatever is said to be under the click
    getLayer: (id: string) =>
      under.includes(id) || [...bound.keys()].some((k) => k.endsWith(`:${id}`))
        ? { id }
        : undefined,
    queryRenderedFeatures: (_point: unknown, options?: { layers?: string[] }) =>
      (options?.layers ?? []).filter((id) => under.includes(id)).map((id) => ({ layer: { id } })),
  };
  const fire = (layer: string, e: unknown) =>
    (bound.get(`click:${layer}`) ?? []).forEach((l) => l(e));
  const count = () => [...bound.values()].reduce((n, l) => n + l.length, 0);
  return {
    map: map as unknown as Parameters<typeof bindEntityClicks>[0],
    fire,
    count,
  };
}

describe("map click binding", () => {
  it("sends entity and cluster clicks to the current callbacks and unbinds them", () => {
    const { map, fire, count } = fakeMap();
    const seen: string[] = [];
    const unbind = bindEntityClicks(
      map,
      (props) => seen.push(`entity:${props.entity_id}`),
      (lngLat, clusterId) =>
        seen.push(`cluster:${clusterId}@${lngLat.join(",")}`),
    );
    fire("entity-markers", { features: [{ properties: { entity_id: "e1" } }] });
    fire("entity-clusters", {
      features: [
        {
          geometry: { type: "Point", coordinates: [1, 2] },
          properties: { cluster_id: 7 },
        },
      ],
    });
    fire("entity-markers", { features: [] });
    expect(seen).toEqual(["entity:e1", "cluster:7@1,2"]);
    expect(count()).toBe(2);
    unbind();
    expect(count()).toBe(0);
    fire("entity-markers", { features: [{ properties: { entity_id: "e2" } }] });
    expect(seen).toHaveLength(2);
  });

  it("rebinding replaces the old callback instead of stacking a second one", () => {
    // the bug: after switching project on the map page, a click still used the first project's
    // callback; an effect that unbinds on cleanup must leave exactly one, current, listener
    const { map, fire, count } = fakeMap();
    const seen: string[] = [];
    const first = bindEntityClicks(
      map,
      (p) => seen.push(`first:${p.entity_id}`),
      () => undefined,
    );
    first();
    bindEntityClicks(
      map,
      (p) => seen.push(`second:${p.entity_id}`),
      () => undefined,
    );
    fire("entity-markers", { features: [{ properties: { entity_id: "e1" } }] });
    expect(seen).toEqual(["second:e1"]);
    expect(count()).toBe(2);
  });

  it("binds and unbinds the event marker click", () => {
    const { map, fire, count } = fakeMap();
    const seen: string[] = [];
    const unbind = bindEventClicks(map, (props) => seen.push(props.event_id));
    fire("event-markers", { features: [{ properties: { event_id: "ev1" } }] });
    expect(seen).toEqual(["ev1"]);
    unbind();
    expect(count()).toBe(0);
  });

  it("binds and unbinds the gateway and track point clicks (phase 19)", () => {
    const { map, fire, count } = fakeMap();
    const seen: string[] = [];
    const unbindGateways = bindGatewayClicks(map, (props) =>
      seen.push(`gateway:${props.gateway_id}`),
    );
    const unbindPoints = bindTrackPointClicks(map, (props) =>
      seen.push(`point:${props.key}`),
    );
    fire("gateway-markers", {
      features: [{ properties: { gateway_id: "g1", name: "GW" } }],
    });
    const key = trackPointKey("e1", "2026-04-01T12:00:00+00:00");
    fire("track-points", {
      features: [{ properties: { owner_id: "e1", kind: "entity", key } }],
    });
    fire("track-point-selected", {
      features: [{ properties: { owner_id: "e1", kind: "entity", key } }],
    });
    expect(seen).toEqual(["gateway:g1", `point:${key}`, `point:${key}`]);
    expect(count()).toBe(3);
    unbindGateways();
    unbindPoints();
    expect(count()).toBe(0);
  });

  it("binds the feature click on the fill, line and point layers and unbinds it", () => {
    const { map, fire, count } = fakeMap();
    const seen: string[] = [];
    const unbind = bindFeatureClicks(map, (props) => seen.push(props.id));
    fire("features-fill", {
      features: [
        { properties: { id: "f1", name: "Fence", feature_type: "geofence" } },
      ],
    });
    fire("features-point", {
      features: [
        { properties: { id: "f2", name: "Camp", feature_type: "site" } },
      ],
    });
    expect(seen).toEqual(["f1", "f2"]);
    expect(count()).toBe(3);
    unbind();
    expect(count()).toBe(0);
  });

  it("lets an area give way to a marker standing on it (Tim, 2026-09-18)", () => {
    // an animal inside a geofence: MapLibre calls both handlers, and the area's is bound last
    const { map, fire } = fakeMap(["entity-markers"]);
    const seen: string[] = [];
    bindFeatureClicks(map, (props) => seen.push(props.id));
    fire("features-fill", {
      point: { x: 10, y: 10 },
      features: [
        { properties: { id: "f1", name: "Fence", feature_type: "geofence" } },
      ],
    });
    expect(seen).toEqual([]);
  });

  it("still opens the area where nothing is drawn on top of it", () => {
    const { map, fire } = fakeMap([]);
    const seen: string[] = [];
    bindFeatureClicks(map, (props) => seen.push(props.id));
    fire("features-fill", {
      point: { x: 10, y: 10 },
      features: [
        { properties: { id: "f1", name: "Fence", feature_type: "geofence" } },
      ],
    });
    expect(seen).toEqual(["f1"]);
  });

  it.each([
    "device-markers",
    "event-markers",
    "gateway-markers",
    "track-points",
    "entity-clusters",
  ])("gives way to %s as well", (layer) => {
    const { map, fire } = fakeMap([layer]);
    const seen: string[] = [];
    bindFeatureClicks(map, (props) => seen.push(props.id));
    fire("features-fill", {
      point: { x: 1, y: 1 },
      features: [{ properties: { id: "f1", name: "F", feature_type: "zone" } }],
    });
    expect(seen).toEqual([]);
  });
});

describe("source ids", () => {
  it("never collide with a base map style's sources", () => {
    for (const id of Object.values(SOURCES)) expect(BASEMAP_SOURCE_IDS, id).not.toContain(id);
  });
});

describe("assignTrackColors", () => {
  // ids whose hashed colours collide, found by trying: the palette has eight entries
  const ids = Array.from({ length: 40 }, (_, i) => `entity-${i}`);
  const colliding = ids.filter((id) => trackColor(id) === trackColor(ids[0]));

  it("gives tracks shown together colours of their own even when their hashes collide", () => {
    expect(colliding.length).toBeGreaterThan(1);
    const colors = assignTrackColors(colliding.map((entityId) => ({ entityId })));
    expect(new Set(colors.values()).size).toBe(colliding.length);
    expect(colors.get(colliding[0])).toBe(trackColor(colliding[0]));
  });

  it("keeps a track's colour while others come and go", () => {
    const first = assignTrackColors([{ entityId: "keep-me" }]).get("keep-me");
    const withOthers = assignTrackColors(
      ["a", "b", "c", "keep-me", "d"].map((entityId) => ({ entityId })),
    );
    expect(withOthers.get("keep-me")).toBe(first);
    expect(new Set(withOthers.values()).size).toBe(5);
  });

  it("goes past the palette with colours that still differ", () => {
    const colors = assignTrackColors(
      Array.from({ length: 12 }, (_, i) => ({ entityId: `many-${i}` })),
    );
    expect(new Set(colors.values()).size).toBe(12);
  });

  it("leaves a colour the caller chose alone", () => {
    const colors = assignTrackColors([
      { entityId: "x", color: "#123456" },
      { entityId: "y" },
    ]);
    expect(colors.get("x")).toBe("#123456");
    expect(colors.get("y")).not.toBe("#123456");
  });
});
