import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

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
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { useAuthStore } from "@/stores/auth";
import { formatTime } from "@/lib/format";
import { usePermissions } from "@/hooks/useProjects";
import {
  daysUntil,
  documentOf,
  fixesPreset,
  isActive,
  type ResultDocument,
  subjectPalette,
} from "@/lib/analyses";

/** One run on an analysis page: its status, the actions (save, share, export, cancel,
 * delete), its settings, and the result blocks the document holds. The module's page adds its own summary
 * and map through `render` and the labels of its metrics through `labels`; this view knows
 * nothing of the method. */
export function RunView({
  projectId,
  runId,
  labels: given,
  render,
  onEdit,
  printTo,
}: {
  projectId: string;
  runId: string;
  labels: Record<string, string>;
  /** The page's own blocks: a summary in place of the flat list, a map beside it, and
   * anything after the tables (the method's limitations, say). */
  render?: {
    summary?: (
      document: ResultDocument,
      run: AnalysisRun,
      colors: Record<string, string>,
    ) => React.ReactNode;
    map?: (
      document: ResultDocument,
      run: AnalysisRun,
      colors: Record<string, string>,
    ) => React.ReactNode;
    after?: (document: ResultDocument, run: AnalysisRun) => React.ReactNode;
  };
  /** Open the run's settings in the dialog, to change them and run again. */
  onEdit?: (run: AnalysisRun) => void;
  /** The print view of the run (decision D208), offered under Export as "Save as PDF". */
  printTo?: string;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const navigate = useNavigate();
  const { can } = usePermissions(projectId);
  const me = useAuthStore((s) => s.user);
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
        ? t("Saved as {{name}}", { name: r.name })
        : t("The run expires again"),
    onSuccess: () => setNaming(null),
  });
  const share = useMutationToast({
    mutationFn: (shared: boolean) =>
      api.patch<AnalysisRun>(base, { body: { shared } }),
    invalidate,
    success: (r) =>
      r.shared ? t("Shared with the project") : t("Only you see it now"),
  });
  const cancel = useMutationToast({
    mutationFn: () => api.post<AnalysisRun>(`${base}/cancel`),
    invalidate,
    success: t("Cancelled"),
  });
  const remove = useMutationToast({
    mutationFn: () => api.delete(base),
    invalidate,
    success: t("Run deleted"),
    onSuccess: () => setDeleting(false),
  });
  const document = documentOf(run.data);
  const colors = document ? subjectPalette(document) : {};
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
          {mayRun && onEdit && !isActive(r.status) && (
            <Button variant="outline" size="sm" onClick={() => onEdit(r)}>
              {t("Edit and run again")}
            </Button>
          )}
          {mayRun && r.status === "completed" && naming === null && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setNaming(r.name ?? "")}
            >
              {r.name ? t("Rename") : t("Save…")}
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
                {printTo && (
                  <DropdownMenuItem onClick={() => navigate(printTo)}>
                    {t("Save as PDF (print view)…")}
                  </DropdownMenuItem>
                )}
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
            placeholder={t("A name saves the run")}
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
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
        {r.name && naming === null && (
          <span>
            {t("Saved as {{name}}; it does not expire.", { name: r.name })}
          </span>
        )}
        {!r.name && r.expires_at && (
          <span>
            {t("Not saved: it expires in {{count}} days.", {
              count: daysUntil(r.expires_at, now),
            })}
          </span>
        )}
        {(r.created_by_user_id === me?.id || can("project:write")) && (
          <label className="flex items-center gap-2">
            <Switch
              checked={r.shared}
              onCheckedChange={(v) => share.mutate(v)}
              disabled={share.isPending}
              aria-label={t("Shared with the project")}
            />
            {t("Shared with the project")}
          </label>
        )}
      </p>
      <RunSettings run={r} document={document} />
      {document && (
        <>
          <WarningsCallout document={document} />
          {render?.summary ? (
            render.summary(document, r, colors)
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
          {render?.map?.(document, r, colors)}
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
                    colorOf={(s) =>
                      s.subject ? (colors[s.subject] ?? null) : null
                    }
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

/** What the run was asked: its subjects, period, comparison and every option, from the
 * stored parameters, so a result is never read without its settings. */
export function RunSettings({
  run,
  document,
}: {
  run: AnalysisRun;
  document: ResultDocument | null;
}) {
  const { t } = useTranslation();
  const p = run.parameters as Record<string, unknown>;
  const names = new Map<string, string>();
  for (const s of document?.subjects ?? []) names.set(s.id, s.name);
  const areas =
    (document?.summary.areas as { id: string; name: string }[] | undefined) ??
    [];
  for (const a of areas) names.set(a.id, a.name);
  const fmt = (iso: unknown) =>
    typeof iso === "string" ? formatTime(iso) : "";
  const listOf = (key: string) =>
    Array.isArray(p[key])
      ? (p[key] as unknown[])
          .map((id) => names.get(String(id)) ?? String(id))
          .join(", ")
      : null;
  const rows: [string, string][] = [];
  const subjects = listOf("entity_ids");
  if (subjects) rows.push([t("Subjects"), subjects]);
  const herdB = listOf("herd_b_entity_ids");
  if (herdB) rows.push([t("Second herd"), herdB]);
  const chosen = listOf("feature_ids");
  if (chosen) rows.push([t("Areas"), chosen]);
  rows.push([t("Period"), `${fmt(p.time_from)} – ${fmt(p.time_to)}`]);
  const comparison = p.comparison as
    { time_from?: string; time_to?: string } | undefined;
  if (comparison)
    rows.push([
      t("Compared with"),
      `${fmt(comparison.time_from)} – ${fmt(comparison.time_to)}`,
    ]);
  if (p.seasons === true) rows.push([t("Seasons"), t("rows per season")]);
  const options: [string, string][] = [
    ["gap_hours", t("Gap threshold (hours)")],
    ["max_speed_mps", t("Maximum plausible speed (m/s)")],
    ["cell_m", t("Grid cell (m)")],
    ["revisit_hours", t("Revisit after (hours)")],
    ["methods", t("Home range methods")],
    ["kde_bandwidth_m", t("KDE bandwidth (m)")],
    ["weighting", t("Weighting")],
    ["weight_key", t("Attribute key")],
    ["min_absence_hours", t("New visit after (hours away)")],
    ["rest_threshold_hours", t("Rest day at or below (animal-hours)")],
  ];
  for (const [key, label] of options) {
    const v = p[key];
    if (v === undefined || v === null) continue;
    rows.push([
      label,
      Array.isArray(v) ? v.map(String).join(", ").toUpperCase() : String(v),
    ]);
  }
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        {t("Settings of this run")}
      </summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
