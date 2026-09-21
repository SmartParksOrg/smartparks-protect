import { useMutation } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ProposedAreas } from "@/components/map/propose";

/** Asks the API what a click could mean (phase 33): the enclosed face and the OpenStreetMap
 * areas containing the point. One request per click; the answer is kept until the next. */
export function useProposeArea(projectId: string) {
  return useMutation({
    mutationFn: ([lon, lat]: [number, number]) =>
      api.post<ProposedAreas>(
        `/api/v1/projects/${projectId}/features/propose`,
        {
          body: { lon, lat },
        },
      ),
  });
}
