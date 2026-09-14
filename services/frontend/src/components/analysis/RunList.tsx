import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AnalysisRun, Page as PageType } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { usePermissions } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";
import { daysUntil, isActive } from "@/lib/analyses";
import { useAuthStore } from "@/stores/auth";

/** The status each run was last seen with, per page, so a run that finishes while the list
 * is open gets one notice; a module-level map, not a ref, so the effect stays pure. */
const lastSeen = new Map<string, string>();

/** The runs of one module a person may see (their own and the shared ones), newest first,
 * polled while any is active: saved and unsaved alike, with the status, the subjects, the
 * period, who ran it and whether it is saved and shared. A click opens the run; a run that
 * finishes while the list is open says so with a way to open it. */
export function RunList({
  projectId,
  module,
  selected,
  onSelect,
}: {
  projectId: string;
  module: string;
  selected: string | null;
  onSelect: (run: AnalysisRun) => void;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const me = useAuthStore((s) => s.user);
  const { can } = usePermissions(projectId);
  const [removing, setRemoving] = useState<AnalysisRun | null>(null);
  const key = queryKeys.analyses(projectId, { module, recent: true });
  const runs = useQuery({
    queryKey: key,
    queryFn: () =>
      api.get<PageType<AnalysisRun>>(`/api/v1/projects/${projectId}/analyses`, {
        query: { module, limit: 50 },
      }),
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => isActive(r.status)) ? 3000 : false,
  });
  const remove = useMutationToast({
    mutationFn: (run: AnalysisRun) =>
      api.delete(`/api/v1/projects/${projectId}/analyses/${run.id}`),
    invalidate: [key],
    success: t("Run deleted"),
    onSuccess: () => setRemoving(null),
  });
  const items = useMemo(() => runs.data?.items ?? [], [runs.data]);
  useEffect(() => {
    for (const run of items) {
      const before = lastSeen.get(run.id);
      lastSeen.set(run.id, run.status);
      if (before && isActive(before) && !isActive(run.status)) {
        const label = run.name ?? t("The unnamed run");
        if (run.status === "completed")
          toast.success(t("{{run}} is ready", { run: label }), {
            action: { label: t("Open"), onClick: () => onSelect(run) },
          });
        else if (run.status === "failed")
          toast.error(t("{{run}} failed", { run: label }), {
            action: { label: t("Open"), onClick: () => onSelect(run) },
          });
      }
    }
  }, [items, onSelect, t]);
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
  const mayDelete = (run: AnalysisRun) =>
    can("project:write") ||
    (can("analysis:run") && run.created_by_user_id === me?.id);
  const period = (run: AnalysisRun) => {
    const p = run.parameters as { time_from?: string; time_to?: string };
    return p.time_from && p.time_to
      ? `${formatTime(p.time_from).slice(0, 12)} – ${formatTime(p.time_to).slice(0, 12)}`
      : "";
  };
  return (
    <div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("Run")}</TableHead>
            <TableHead>{t("Status")}</TableHead>
            <TableHead className="hidden sm:table-cell">
              {t("Subjects")}
            </TableHead>
            <TableHead className="hidden md:table-cell">
              {t("Period")}
            </TableHead>
            <TableHead className="hidden md:table-cell">{t("By")}</TableHead>
            <TableHead>{t("Started")}</TableHead>
            <TableHead className="hidden sm:table-cell">{t("Saved")}</TableHead>
            <TableHead className="hidden sm:table-cell">
              {t("Shared")}
            </TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((run) => (
            <TableRow
              key={run.id}
              className={`cursor-pointer ${run.id === selected ? "bg-muted" : ""}`}
              aria-selected={run.id === selected}
              onClick={() => onSelect(run)}
            >
              <TableCell className="max-w-64 truncate font-medium">
                {run.name ?? (
                  <span className="font-normal text-muted-foreground">
                    {t("Unnamed")}
                  </span>
                )}
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    run.status === "completed"
                      ? "default"
                      : run.status === "failed"
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {run.status}
                </Badge>
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                {(run.parameters as { entity_ids?: string[] }).entity_ids
                  ?.length ?? 0}
              </TableCell>
              <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell">
                {period(run)}
              </TableCell>
              <TableCell className="hidden max-w-40 truncate text-muted-foreground md:table-cell">
                {run.created_by_user_id === me?.id
                  ? t("you")
                  : (run.created_by_name ?? "")}
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatAgo(run.created_at, now)}
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                {run.name
                  ? t("yes")
                  : run.expires_at
                    ? t("expires in {{count}} days", {
                        count: daysUntil(run.expires_at, now),
                      })
                    : t("no")}
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                {run.shared ? t("yes") : t("no")}
              </TableCell>
              <TableCell className="p-1 text-right">
                {mayDelete(run) && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={t("Delete run")}
                    title={t("Delete run")}
                    onClick={(e) => {
                      e.stopPropagation();
                      setRemoving(run);
                    }}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("Delete run")}
        description={t(
          "The run and its results go. The analysis can be run again from the same choices.",
        )}
        confirmLabel={t("Delete")}
        onConfirm={() => removing && remove.mutate(removing)}
        pending={remove.isPending}
      />
    </div>
  );
}
