import { useMutation } from "@tanstack/react-query";
import { useRef } from "react";

import { api } from "@/api/client";
import type { Bounds } from "@/components/map/fit";
import type { ProposedAreas } from "@/components/map/propose";
import type { ReadBox } from "@/components/map/proposeBox";

/** What is being asked: the ground to read, or a name and the map being looked at. */
export type AreaAsk =
  | { kind: "box"; box: ReadBox }
  | { kind: "name"; name: string; bounds: Bounds };

/**
 * Asks the API what an area could be (phase 33): the enclosed face and the OpenStreetMap areas
 * inside a box (decisions D270 and D277), or the areas of a name in the view (D273).
 *
 * One read at a time (Tim, 2026-09-21): a read takes seconds, and a person who clicks again
 * while it runs used to start a second one, which is how the public Overpass ends up refusing
 * a burst. A gesture made while a read is in flight is ignored — `busy` says so and the map
 * shows a spinner — and `cancel()` is the way out, so waiting is never forced on anybody.
 */
export function useProposeArea(projectId: string) {
  const running = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: (ask: AreaAsk) => {
      const controller = new AbortController();
      running.current = controller;
      // whatever the answer is — candidates, a refusal or an abort — the next gesture may ask
      const done = () => {
        if (running.current === controller) running.current = null;
      };
      const request =
        ask.kind === "box"
          ? api.post<ProposedAreas>(
              `/api/v1/projects/${projectId}/features/propose`,
              { body: ask.box, signal: controller.signal },
            )
          : api.post<ProposedAreas>(
              `/api/v1/projects/${projectId}/features/search-areas`,
              {
                body: {
                  name: ask.name,
                  west: ask.bounds[0][0],
                  south: ask.bounds[0][1],
                  east: ask.bounds[1][0],
                  north: ask.bounds[1][1],
                },
                signal: controller.signal,
              },
            );
      return request.finally(done);
    },
  });
  const cancel = () => {
    running.current?.abort();
    running.current = null;
    mutation.reset();
  };
  /** Ask, unless a read is already running: the second click of an impatient hand is what
   * makes a public Overpass refuse the first. */
  const ask = (next: AreaAsk) => {
    if (running.current) return false;
    mutation.mutate(next);
    return true;
  };
  return { ...mutation, ask, cancel };
}
