import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Metric, Page } from "@/api/types";

/** The metric registry by key, read once and kept for a while: the status panels use it to
 * decide which values can unfold a trend (Tim, 2026-09-15). */
export function useMetricsByKey(): Map<string, Metric> {
  const metrics = useQuery({
    queryKey: queryKeys.metrics,
    queryFn: () => api.get<Page<Metric>>("/api/v1/metrics", { query: { limit: 500 } }),
    staleTime: 5 * 60_000,
  });
  return useMemo(
    () => new Map((metrics.data?.items ?? []).map((m) => [m.key, m])),
    [metrics.data],
  );
}
