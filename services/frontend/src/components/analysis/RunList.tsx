import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AnalysisRun, Page as PageType } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useNow } from "@/hooks/useNow";
import { formatAgo } from "@/lib/format";
import { isActive } from "@/lib/analyses";

/** The recent runs of one module in the project, newest first, polled while any is active;
 * a click opens the run on the page. */
export function RunList({
  projectId,
  module,
  selected,
  onSelect,
}: {
  projectId: string;
  module: string;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const runs = useQuery({
    queryKey: queryKeys.analyses(projectId, { module, recent: true }),
    queryFn: () =>
      api.get<PageType<AnalysisRun>>(`/api/v1/projects/${projectId}/analyses`, {
        query: { module, limit: 20 },
      }),
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => isActive(r.status)) ? 3000 : false,
  });
  const items = runs.data?.items ?? [];
  if (runs.isPending)
    return (
      <p className="text-xs text-muted-foreground">{t("Loading runs…")}</p>
    );
  if (items.length === 0)
    return (
      <p className="text-xs text-muted-foreground">
        {t("No runs yet. Choose subjects and a period, then run.")}
      </p>
    );
  return (
    <ul className="divide-y rounded-md border">
      {items.map((run) => (
        <li key={run.id}>
          <Button
            variant="ghost"
            className={`h-auto w-full justify-between gap-2 overflow-hidden rounded-none px-3 py-2 text-left ${run.id === selected ? "bg-muted" : ""}`}
            onClick={() => onSelect(run.id)}
          >
            <span className="min-w-0 flex-1 truncate">
              {run.name ??
                t("{{count}} subjects", {
                  count:
                    (run.parameters as { entity_ids?: string[] }).entity_ids
                      ?.length ?? 0,
                })}
            </span>
            <Badge
              variant={
                run.status === "completed"
                  ? "default"
                  : run.status === "failed"
                    ? "destructive"
                    : "secondary"
              }
              className="shrink-0"
            >
              {run.status}
            </Badge>
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatAgo(run.created_at, now)}
            </span>
          </Button>
        </li>
      ))}
    </ul>
  );
}
