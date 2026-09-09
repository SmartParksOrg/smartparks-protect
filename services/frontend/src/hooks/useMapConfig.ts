import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { MapConfig } from "@/api/types";

/** What the map needs from the server (decision D141): the MapTiler key, or none. Read once
 * per session; a server without a key keeps the free base maps and no terrain. */
export function useMapConfig(): {
  maptilerKey: string | null;
  loaded: boolean;
} {
  const config = useQuery({
    queryKey: queryKeys.mapConfig,
    queryFn: () => api.get<MapConfig>("/api/v1/map/config"),
    staleTime: Infinity,
  });
  return {
    maptilerKey: config.data?.maptiler_key ?? null,
    loaded: !config.isPending,
  };
}
