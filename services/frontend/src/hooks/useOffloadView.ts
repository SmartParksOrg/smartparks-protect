import type { ListOrMap } from "@/components/network/PlacesMap";
import { usePreference } from "@/hooks/usePreference";

/** A section of the Offload page, the stations or the trackers, as a list or a map, remembered
 * per person (Tim, 2026-10-18). */
export function useOffloadView(
  section: "stations" | "trackers",
): [ListOrMap, (view: ListOrMap) => void] {
  return usePreference<ListOrMap>(`offload_${section}_view`, "list");
}
