import { useMutation } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Bounds } from "@/components/map/fit";
import type { ProposedAreas } from "@/components/map/propose";

/** What is being asked: where somebody clicked, or a name and the map they are looking at. */
export type AreaAsk =
  | { kind: "click"; at: [number, number] }
  | { kind: "name"; name: string; bounds: Bounds };

/** Asks the API what an area could be (phase 33): the enclosed face and the OpenStreetMap
 * areas containing a click (decision D270), or the areas of a name in the view (D273). One
 * request per ask; the answer is kept until the next. */
export function useProposeArea(projectId: string) {
  return useMutation({
    mutationFn: (ask: AreaAsk) =>
      ask.kind === "click"
        ? api.post<ProposedAreas>(
            `/api/v1/projects/${projectId}/features/propose`,
            { body: { lon: ask.at[0], lat: ask.at[1] } },
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
            },
          ),
  });
}
