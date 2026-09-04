import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CurationSummary, RecordHistory } from "@/api/types";
import type { CurationTarget } from "@/lib/curation";

export function useCurationSummary(projectId: string, enabled = true) {
  return useQuery({ queryKey: queryKeys.curationSummary(projectId), queryFn: () => api.get<CurationSummary>(`/api/v1/projects/${projectId}/curation/summary`), enabled: Boolean(projectId) && enabled });
}

export function useRecordHistory(projectId: string, target: CurationTarget | null) {
  return useQuery({
    queryKey: queryKeys.recordHistory(projectId, target?.target_type ?? "", target?.target_id ?? 0, target?.target_time ?? ""),
    queryFn: () => api.get<RecordHistory>(`/api/v1/projects/${projectId}/curation/history`, { query: { target_type: target?.target_type, target_id: target?.target_id, target_time: target?.target_time } }),
    enabled: target !== null && Boolean(projectId),
  });
}

/** Invalidate what shows canonical values, so a correction is visible everywhere at once. */
export function invalidateRecords(client: ReturnType<typeof useQueryClient>, projectId: string) {
  void client.invalidateQueries({ queryKey: ["projects", projectId] });
  void client.invalidateQueries({ queryKey: ["devices"] });
}
