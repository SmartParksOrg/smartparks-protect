import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, downloadFile } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AnalysisRun } from "@/api/types";
import { ExportDialog } from "@/components/analytics/ExportDialog";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { RunStatus } from "@/components/analysis/RunStatus";
import { ResultChart } from "@/components/analysis/ResultChart";
import { ResultTable } from "@/components/analysis/ResultTable";
import { WarningsCallout } from "@/components/analysis/WarningsCallout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { usePermissions } from "@/hooks/useProjects";
import {
  documentOf,
  fixesPreset,
  isActive,
  type ResultDocument,
  subjectColor,
} from "@/lib/analyses";

/** One run on an analysis page: its status, the actions (keep, export, run again, cancel,
 * delete), and the result blocks the document holds. The module's page adds its own summary
 * and map through `render` and the labels of its metrics through `labels`; this view knows
 * nothing of the method. */
export function RunView({
  projectId,
  runId,
  labels: given,
  render,
  onRerun,
}: {
  projectId: string;
  runId: string;
  labels: Record<string, string>;
  /** The page's own blocks: a summary in place of the flat list, a map beside it, and
   * anything after the tables (the method's limitations, say). */
  render?: {
    summary?: (document: ResultDocument, run: AnalysisRun) => React.ReactNode;
    map?: (document: ResultDocument, run: AnalysisRun) => React.ReactNode;
    after?: (document: ResultDocument, run: AnalysisRun) => React.ReactNode;
  };
  onRerun?: (run: AnalysisRun) => void;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const { can } = usePermissions(projectId);
  const base = `/api/v1/projects/${projectId}/analyses/${runId}`;
  const run = useQuery({
    queryKey: queryKeys.analysis(projectId, runId),
    queryFn: () => api.get<AnalysisRun>(base),
    refetchInterval: (query) =>
      query.state.data && isActive(query.state.data.status) ? 3000 : false,
  });
  const invalidate = [
    queryKeys.analysis(projectId, runId),
    queryKeys.analyses(projectId, {
      module: run.data?.module ?? "",
      recent: true,
    }),
  ];
  const [naming, setNaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [exportingFixes, setExportingFixes] = useState(false);
  const keep = useMutationToast({
    mutationFn: (name: string | null) =>
      api.patch<AnalysisRun>(base, { body: { name } }),
    invalidate,
    success: (r) =>
      r.name
        ? t("Kept as {{name}}", { name: r.name })
        : t("The run expires again"),
    onSuccess: () => setNaming(null),
  });
  const cancel = useMutationToast({
    mutationFn: () => api.post<AnalysisRun>(`${base}/cancel`),
    invalidate,
    success: t("Cancelled"),
  });
  const rerun = useMutationToast({
    mutationFn: () => api.post<AnalysisRun>(`${base}/rerun`),
    invalidate,
    success: t("Run again"),
    onSuccess: (r) => onRerun?.(r),
  });
  const remove = useMutationToast({
    mutationFn: () => api.delete(base),
    invalidate,
    success: t("Run deleted"),
    onSuccess: () => setDeleting(false),
  });
  const document = documentOf(run.data);
  // the subjects' names label their series and rows
  const labels: Record<string, string> = {
    ...given,
    ...Object.fromEntries(
      (document?.subjects ?? []).map((s) => [s.id, s.name]),
    ),
  };
  if (run.isPending)
    return <p className="text-sm text-muted-foreground">{t("Loading…")}</p>;
  if (run.isError || !run.data)
    return (
      <p className="text-sm text-destructive">
        {run.error?.message ?? t("The run is gone.")}
      </p>
    );
  const r = run.data;
  const mayRun = can("analysis:run");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <RunStatus run={r} now={now} />
        <div className="flex flex-wrap gap-2">
          {mayRun && isActive(r.status) && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              {t("Cancel")}
            </Button>
          )}
          {mayRun && !isActive(r.status) && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => rerun.mutate()}
              disabled={rerun.isPending}
            >
              {t("Run again")}
            </Button>
          )}
          {mayRun && r.status === "completed" && naming === null && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setNaming(r.name ?? "")}
            >
              {r.name ? t("Rename") : t("Keep")}
            </Button>
          )}
          {document && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  {t("Export")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {document.tables.map((table) => (
                  <DropdownMenuItem
                    key={table.key}
                    onClick={() =>
                      void downloadFile(`${base}/export`, `${table.key}.csv`, {
                        what: table.key,
                        format: "csv",
                      })
                    }
                  >
                    {t("{{table}} as CSV", {
                      table: labels[table.key] ?? table.key,
                    })}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem
                  onClick={() =>
                    void downloadFile(`${base}/export`, "geometries.geojson", {
                      what: "geometries",
                      format: "geojson",
                    })
                  }
                >
                  {t("Geometries as GeoJSON")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    void downloadFile(`${base}/export`, "analysis.json", {
                      what: "document",
                      format: "json",
                    })
                  }
                >
                  {t("Everything as JSON")}
                </DropdownMenuItem>
                {can("exports:create") && (
                  <DropdownMenuItem onClick={() => setExportingFixes(true)}>
                    {t("The fixes behind it…")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {mayRun && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => setDeleting(true)}
            >
              {t("Delete")}
            </Button>
          )}
        </div>
      </div>
      {naming !== null && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            keep.mutate(naming.trim() || null);
          }}
        >
          <Input
            value={naming}
            onChange={(e) => setNaming(e.target.value)}
            placeholder={t("A name keeps the run")}
            className="w-64"
            aria-label={t("Name")}
          />
          <Button type="submit" size="sm" disabled={keep.isPending}>
            {t("Save")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setNaming(null)}
          >
            {t("Cancel")}
          </Button>
        </form>
      )}
      {r.name && naming === null && (
        <p className="text-sm text-muted-foreground">
          {t("Kept as {{name}}; it does not expire.", { name: r.name })}
        </p>
      )}
      {document && (
        <>
          <WarningsCallout document={document} />
          {render?.summary ? (
            render.summary(document, r)
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>{t("Summary")}</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  {Object.entries(document.summary).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-muted-foreground">
                        {labels[k] ?? k}
                      </dt>
                      <dd>
                        {typeof v === "number"
                          ? Number.isInteger(v)
                            ? v
                            : v.toFixed(2)
                          : String(v ?? "")}
                      </dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
          )}
          {render?.map?.(document, r)}
          <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
            {document.charts.map((chart) => (
              <Card key={chart.key}>
                <CardHeader>
                  <CardTitle>{labels[chart.key] ?? chart.key}</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResultChart
                    chart={chart}
                    labels={labels}
                    colorOf={(s) => (s.subject ? subjectColor(s.subject) : null)}
                  />
                </CardContent>
              </Card>
            ))}
          </div>
          {document.tables.map((table) => (
            <div key={table.key} className="space-y-2">
              <h2 className="text-base font-medium">
                {labels[table.key] ?? table.key}
              </h2>
              <ResultTable table={table} labels={labels} />
            </div>
          ))}
          {render?.after?.(document, r)}
        </>
      )}
      {document && exportingFixes && (
        <ExportDialog
          projectId={projectId}
          open={exportingFixes}
          onOpenChange={setExportingFixes}
          preset={fixesPreset(document)}
        />
      )}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t("Delete run")}
        description={t(
          "The run and its results go. The analysis can be run again from the same choices.",
        )}
        confirmLabel={t("Delete")}
        onConfirm={() => remove.mutate()}
        pending={remove.isPending}
      />
    </div>
  );
}
