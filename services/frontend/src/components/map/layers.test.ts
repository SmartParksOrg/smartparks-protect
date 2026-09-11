import { describe, expect, it } from "vitest";

import {
  BASEMAP_SOURCE_IDS,
  SOURCES,
  bindEntityClicks,
  bindEventClicks,
  bindFeatureClicks,
  bindGatewayClicks,
  bindTrackPointClicks,
  trackPointKey,
} from "@/components/map/layers";

type Listener = (e: unknown) => void;

/** A map that only records layer listeners, enough to prove binding and unbinding pair up. */
function fakeMap() {
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
});

describe("source ids", () => {
  it("never collide with a base map style's sources", () => {
    for (const id of Object.values(SOURCES)) expect(BASEMAP_SOURCE_IDS, id).not.toContain(id);
  });
});
