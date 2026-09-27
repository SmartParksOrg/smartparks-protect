import { useMutation } from "@tanstack/react-query";
import { useRef } from "react";

import { api } from "@/api/client";
import type { ReadBox } from "@/components/map/proposeBox";

/** One road as the API answers it (phase 38, decision D300). */
export interface ProposedRoad {
  osm_id: number;
  name: string;
  highway: string;
  geometry: GeoJSON.Geometry;
}

export interface ProposedRoads {
  roads: ProposedRoad[];
  attribution: string;
}

/**
 * Asks the API for the roads and tracks OpenStreetMap knows in a box (phase 38): the route
 * type's counterpart of the area proposal, with the same one-read-at-a-time rule, since a
 * second read while one runs is what makes a public Overpass refuse the first.
 */
export function useProposeRoads(projectId: string) {
  const running = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: (box: ReadBox) => {
      const controller = new AbortController();
      running.current = controller;
      const done = () => {
        if (running.current === controller) running.current = null;
      };
      return api
        .post<ProposedRoads>(`/api/v1/projects/${projectId}/features/roads`, {
          body: box,
          signal: controller.signal,
        })
        .finally(done);
    },
  });
  const cancel = () => {
    running.current?.abort();
    running.current = null;
    mutation.reset();
  };
  const ask = (box: ReadBox) => {
    if (running.current) return false;
    mutation.mutate(box);
    return true;
  };
  return { ...mutation, ask, cancel };
}
