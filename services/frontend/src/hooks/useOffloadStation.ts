import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { OffloadStation } from "@/api/types";

/** The station card of a device (`GET /devices/{id}/offload`): what its SD cards brought, the
 * trackers it served and its own last report. One query key, so the live map's panel and its
 * rows share the read (decision D350). */
export function useOffloadStation(deviceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.offloadStation(deviceId ?? ""),
    queryFn: () => api.get<OffloadStation>(`/api/v1/devices/${deviceId}/offload`),
    enabled: Boolean(deviceId),
    staleTime: 30_000,
  });
}
