import { usePreference } from "@/hooks/usePreference";

export type StationsView = "list" | "map";

/** The Offload page's Stations section, a list or a map, remembered per person (Tim, 2026-10-18). */
export function useStationsView(): [StationsView, (view: StationsView) => void] {
  return usePreference<StationsView>("offload_stations_view", "list");
}
