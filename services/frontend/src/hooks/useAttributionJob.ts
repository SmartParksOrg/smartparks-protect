import { type QueryKey, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AttributionJob } from "@/api/types";

export function isActiveJob(job: AttributionJob): boolean {
  return job.status === "queued" || job.status === "running";
}

// The active job each device last showed, so the poll that finds it gone can say so once. A
// module-level map, because the React compiler refuses a ref read inside an effect.
const seen = new Map<string, string>();

/** The attribution jobs of a device (decision D206): after an assignment change the records
 * already inside the range get their project and entity in the background. Polls every 3 s
 * while a job is queued or running; when it finishes, toasts the outcome and invalidates the
 * queries the caller names, so the lists and the map show the records where they now belong. */
export function useAttributionJob(deviceId: string | null | undefined, invalidate: QueryKey[] = []) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const jobs = useQuery({
    queryKey: queryKeys.attributionJobs(deviceId ?? ""),
    queryFn: () => api.get<AttributionJob[]>(`/api/v1/devices/${deviceId}/attribution-jobs`),
    enabled: Boolean(deviceId),
    refetchInterval: (query) => (query.state.data?.some(isActiveJob) ? 3_000 : false),
  });
  const active = jobs.data?.find(isActiveJob) ?? null;
  const latest = jobs.data?.[0] ?? null;
  useEffect(() => {
    if (!deviceId || !jobs.data) return;
    if (active) {
      seen.set(deviceId, active.id);
      return;
    }
    const was = seen.get(deviceId);
    if (!was) return;
    seen.delete(deviceId);
    const finished = jobs.data.find((job) => job.id === was);
    if (finished?.status === "complete") {
      toast.success(t("{{count}} records now carry their project and entity", { count: finished.records_done }));
    } else if (finished?.status === "failed") {
      toast.error(t("Giving the records their project and entity failed: {{message}}", { message: finished.error_message ?? finished.error_code ?? "" }));
    }
    void Promise.all(invalidate.map((key) => client.invalidateQueries({ queryKey: key })));
  }, [deviceId, active, jobs.data, invalidate, client, t]);
  return { active, latest, failed: !active && latest?.status === "failed" ? latest : null };
}
