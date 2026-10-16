import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudOff, RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { useAvailabilityStore } from "@/stores/availability";

/**
 * A line that says the server is being updated or does not answer (decision D329; Tim,
 * 2026-10-16: a deploy on dev showed every user a bare 502). The API client marks the moment
 * an answer is a gateway error or a connection fails; this bar then asks the health endpoint
 * every five seconds and, when it answers again, refreshes every query on the page and says
 * so. Nothing a person typed is touched, since the queries are re-read and not the page.
 */
export function ServerUnavailableBar() {
  const { t } = useTranslation();
  const unavailable = useAvailabilityStore((s) => s.unavailable);
  const markAvailable = useAvailabilityStore((s) => s.markAvailable);
  const client = useQueryClient();
  const probe = useQuery({
    queryKey: ["system", "reachable"],
    queryFn: () => api.get<{ status?: string }>("/api/health", { anonymous: true }),
    enabled: unavailable !== null,
    refetchInterval: unavailable ? 5_000 : false,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
  // whichever answer ends the outage, the probe's or any other call's, the page's data is
  // read again once: a tab that sat through a deploy may hold anything
  const wasDown = useRef(false);
  useEffect(() => {
    if (wasDown.current && unavailable === null) {
      void client.invalidateQueries();
      toast.success(t("Protect is back; the page has refreshed its data."));
    }
    wasDown.current = unavailable !== null;
  }, [unavailable, client, t]);
  useEffect(() => {
    if (unavailable && probe.isSuccess && probe.dataUpdatedAt > Date.parse(unavailable.since))
      markAvailable();
  }, [unavailable, probe.isSuccess, probe.dataUpdatedAt, markAvailable]);
  if (!unavailable) return null;
  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b bg-brand-sand/20 px-2 py-1 text-sm sm:px-3"
    >
      {unavailable.reason === "updating" ? (
        <RefreshCw className="size-4 shrink-0 animate-spin text-primary" />
      ) : (
        <CloudOff className="size-4 shrink-0 text-primary" />
      )}
      <span className="min-w-0 flex-1 truncate">
        {unavailable.reason === "updating"
          ? t("Protect is being updated; back in a moment. The page checks every few seconds.")
          : t("The server does not answer at the moment. The page checks every few seconds.")}
      </span>
    </div>
  );
}
