import { describe, expect, it } from "vitest";

import { bindEntityClicks, bindEventClicks } from "@/components/map/layers";

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
      bound.set(key, (bound.get(key) ?? []).filter((l) => l !== listener));
    },
  };
  const fire = (layer: string, e: unknown) =>
    (bound.get(`click:${layer}`) ?? []).forEach((l) => l(e));
  const count = () => [...bound.values()].reduce((n, l) => n + l.length, 0);
  return { map: map as unknown as Parameters<typeof bindEntityClicks>[0], fire, count };
}

describe("map click binding", () => {
  it("sends entity and cluster clicks to the current callbacks and unbinds them", () => {
    const { map, fire, count } = fakeMap();
    const seen: string[] = [];
    const unbind = bindEntityClicks(
      map,
      (props) => seen.push(`entity:${props.entity_id}`),
      (lngLat, clusterId) => seen.push(`cluster:${clusterId}@${lngLat.join(",")}`),
    );
    fire("entity-markers", { features: [{ properties: { entity_id: "e1" } }] });
    fire("entity-clusters", {
      features: [{ geometry: { type: "Point", coordinates: [1, 2] }, properties: { cluster_id: 7 } }],
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
    const first = bindEntityClicks(map, (p) => seen.push(`first:${p.entity_id}`), () => undefined);
    first();
    bindEntityClicks(map, (p) => seen.push(`second:${p.entity_id}`), () => undefined);
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
});
