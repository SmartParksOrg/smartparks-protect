import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Bookmark,
  ChartLine,
  ChevronDown,
  ChevronUp,
  Download,
  Map as MapIcon,
  Table2,
  Trash2,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  Entity,
  EntityAssignment,
  Feature,
  Metric,
  Page as PageType,
  RecordRow,
  SavedView,
  SeriesResponse,
  Track,
} from "@/api/types";
import { ExportDialog } from "@/components/analytics/ExportDialog";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { Callout } from "@/components/common/Callout";
import { EmptyState } from "@/components/common/EmptyState";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { Drawer } from "@/components/explore/Drawer";
import { drawerSpace } from "@/components/explore/drawer";
import { ExploreChart } from "@/components/explore/ExploreChart";
import { ExploreMap } from "@/components/explore/ExploreMap";
import { SelectionStrip } from "@/components/explore/SelectionStrip";
import type { TrackLayer } from "@/components/map/layers";
import { RecordDialog } from "@/components/records/RecordDialog";
import { VirtualTable } from "@/components/records/VirtualTable";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Field } from "@/components/common/FormField";
import { useGroups } from "@/hooks/useGroups";
import { useIsPhone } from "@/hooks/useMediaQuery";
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePreference } from "@/hooks/usePreference";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { useRecords } from "@/hooks/useRecords";
import {
  BUCKETS,
  bucketLabel,
  CHART_TYPES,
  type ChartType,
  formatInZone,
  RANGE_PRESETS,
} from "@/lib/analytics";
import {
  CANVAS_BOUND,
  chartableColumns,
  chartGroups,
  chartMetrics,
  type ExploreMode,
  type ExploreState,
  groupsFromSeries,
  nearestRowTime,
  paramsOfView,
  readExploreState,
  scatterGroup,
  tracksOf,
  viewOfParams,
  writeExploreState,
} from "@/lib/explore";
import { columnsOf, windowFor } from "@/lib/records";
import { useAuthStore } from "@/stores/auth";

const CHART_LABELS: Record<ChartType, string> = {
  line: "Line",
  scatter: "Scatter",
  bar: "Bar",
  histogram: "Histogram",
  state: "State timeline",
};

/**
 * Explore as one canvas (phase 21, decisions D150 to D155): one selection of entities and
 * devices over a period, looked at as a table, a chart or a map. The rows load page after page
 * into the drawer whatever the mode; the chart and the map draw from them up to the canvas
 * bound and from the aggregate and track reads above it. One marked moment links the views.
 */
export function ExplorerPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const role = useProjectRole(projectId);
  const user = useAuthStore((s) => s.user);
  const phone = useIsPhone();
  const [params, setParams] = useSearchParams();

  const views = useQuery({
    queryKey: queryKeys.savedViews(projectId),
    queryFn: () =>
      api.get<PageType<SavedView>>(
        `/api/v1/projects/${projectId}/analytics/saved-views`,
        { query: { limit: 200 } },
      ),
  });
  const viewId = params.get("view");
  const currentView = views.data?.items.find((v) => v.id === viewId);
  // a dashboard tile links with the view id alone: its parameters are the state then
  const effective = useMemo(
    () =>
      currentView && !params.has("mode")
        ? paramsOfView(currentView.view as Record<string, string[]>)
        : params,
    [currentView, params],
  );
  const state = useMemo(() => readExploreState(effective), [effective]);
  const update = useCallback(
    (patch: Partial<ExploreState>, replace = false) =>
      setParams(
        writeExploreState({ ...readExploreState(effective), ...patch }),
        {
          replace,
        },
      ),
    [effective, setParams],
  );

  const entities = useQuery({
    queryKey: queryKeys.entities(projectId),
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
  });
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, records: true }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
  });
  const groups = useGroups(projectId);
  const metrics = useQuery({
    queryKey: queryKeys.metrics,
    queryFn: () =>
      api.get<PageType<Metric>>("/api/v1/metrics", { query: { limit: 500 } }),
  });
  const features = useQuery({
    queryKey: queryKeys.features(projectId),
    queryFn: () =>
      api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, {
        query: { limit: 500 },
      }),
    enabled: state.mode === "map",
  });
  const oneEntity =
    state.entities.length === 1 && state.devices.length === 0
      ? state.entities[0]
      : null;
  const assignments = useQuery({
    queryKey: queryKeys.entityAssignments(projectId, {
      entityId: oneEntity,
      records: true,
    }),
    queryFn: () =>
      api.get<PageType<EntityAssignment>>(
        `/api/v1/projects/${projectId}/entity-assignments`,
        { query: { entity_id: oneEntity, limit: 500 } },
      ),
    enabled: oneEntity !== null,
  });
  const assignedSince = useMemo(() => {
    const starts = (assignments.data?.items ?? [])
      .map((a) => a.valid_from)
      .sort();
    return starts.length ? starts[0] : null;
  }, [assignments.data]);
  const window = useMemo(
    () => windowFor(state, assignedSince),
    [state, assignedSince],
  );
  const selection = useMemo(
    () =>
      state.entities.length + state.devices.length > 0
        ? {
            entities: state.entities,
            devices: state.devices,
            from: window.from,
            to: window.to,
          }
        : null,
    [state.entities, state.devices, window],
  );
  const selectionKey = JSON.stringify(selection);
  const records = useRecords(projectId, selection);

  const names = useMemo(
    () =>
      new Map([
        ...(entities.data?.items ?? []).map((e) => [e.id, e.name] as const),
        ...(devices.data?.items ?? []).map((d) => [d.id, d.name] as const),
      ]),
    [entities.data, devices.data],
  );
  const metricLabels = useMemo(
    () =>
      new Map(
        (metrics.data?.items ?? []).map((m) => [
          m.key,
          { label: m.label, unit: m.unit ?? null },
        ]),
      ),
    [metrics.data],
  );
  const labelsOnly = useMemo(
    () => new Map([...metricLabels].map(([k, v]) => [k, v.label])),
    [metricLabels],
  );
  const columns = useMemo(
    () => columnsOf(records.rows, metricLabels),
    [records.rows, metricLabels],
  );
  const [hiddenColumns, setHiddenColumns] = usePreference<string[]>(
    "records_hidden_columns",
    [],
  );
  const shown = columns.filter((c) => !hiddenColumns.includes(c.key));

  // the marked moment (decision D154): a hover is transient, a click pins it into the URL
  // the selection strip folds once a selection exists, first on a phone; a choice sticks
  const [stripChoice, setStripChoice] = useState<boolean | null>(null);
  const [hovered, setHovered] = useState<{
    ms: number;
    source: "chart" | "map" | "table";
  } | null>(null);
  const hover = hovered?.ms ?? null;
  const pinned = state.at ? Date.parse(state.at) : null;
  const marked = hover ?? pinned;
  const markedRowTime = useMemo(
    () => (marked === null ? null : nearestRowTime(records.rows, marked)),
    [records.rows, marked],
  );
  const pick = useCallback(
    (ms: number) => update({ at: new Date(ms).toISOString() }, true),
    [update],
  );
  const onHover = useCallback(
    (ms: number | null) =>
      setHovered(
        ms === null
          ? null
          : { ms, source: state.mode === "map" ? "map" : "chart" },
      ),
    [state.mode],
  );

  // above the canvas bound the chart takes the aggregate read and the map the track read
  const total = records.total;
  const aggregated = total !== null && total > CANVAS_BOUND;
  const metricsOnChart = useMemo(
    () => chartMetrics(state.metrics, columns),
    [state.metrics, columns],
  );
  const seriesQuery = useMemo(() => {
    if (!aggregated || state.mode !== "chart") return null;
    const q = new URLSearchParams();
    const keys = state.metrics.length ? state.metrics : metricsOnChart;
    for (const m of keys) q.append("metric", m);
    if (state.entities.length)
      for (const e of state.entities) q.append("entity_id", e);
    else {
      for (const d of state.devices) q.append("device_id", d);
      q.set("group_by", "device");
    }
    q.set("from", window.from);
    q.set("to", window.to);
    if (state.bucket !== "auto") q.set("bucket", state.bucket);
    for (const a of state.aggregates) q.append("agg", a);
    q.set("layout", "series");
    return keys.length ? q.toString() : null;
  }, [aggregated, state, metricsOnChart, window]);
  const series = useQuery({
    queryKey: queryKeys.analyticsSeries(projectId, { q: seriesQuery }),
    queryFn: () =>
      api.get<SeriesResponse>(
        `/api/v1/projects/${projectId}/analytics/series?${seriesQuery}`,
      ),
    enabled: seriesQuery !== null,
    placeholderData: (previous) => previous,
  });
  const owners = useMemo(
    () => [
      ...state.entities.map((id) => ({ entity_id: id })),
      ...state.devices.map((id) => ({ device_id: id })),
    ],
    [state.entities, state.devices],
  );
  const trackReads = useQuery({
    queryKey: queryKeys.track(projectId, {
      owners,
      from: window.from,
      to: window.to,
      explore: true,
    }),
    queryFn: () =>
      Promise.all(
        owners.map((owner) =>
          api.get<Track>(`/api/v1/projects/${projectId}/tracks`, {
            query: {
              ...owner,
              from: window.from,
              to: window.to,
              max_points: 5000,
            },
          }),
        ),
      ),
    enabled: aggregated && state.mode === "map" && owners.length > 0,
  });

  const groupsOnChart = useMemo(() => {
    if (state.chart === "scatter") {
      const y = metricsOnChart[0];
      const x = state.xMetric ?? metricsOnChart[1] ?? y;
      const group = x && y ? scatterGroup(records.rows, x, y, columns) : null;
      return group ? [group] : [];
    }
    if (aggregated)
      return series.data
        ? groupsFromSeries(
            series.data,
            names,
            labelsOnly,
            state.aggregates[0] ?? "mean",
          )
        : [];
    return chartGroups(records.rows, metricsOnChart, columns);
  }, [
    state.chart,
    state.xMetric,
    state.aggregates,
    aggregated,
    series.data,
    names,
    labelsOnly,
    records.rows,
    metricsOnChart,
    columns,
  ]);
  const tracks = useMemo<TrackLayer[]>(() => {
    if (aggregated)
      return (trackReads.data ?? []).map((track, i) => ({
        entityId: track.entity_id ?? track.device_id ?? String(i),
        kind: track.entity_id ? "entity" : "device",
        geometry: track.geometry as unknown as GeoJSON.Geometry,
        times: track.times,
      }));
    return tracksOf(records.rows);
  }, [aggregated, trackReads.data, records.rows]);

  const [drawerHeight, setDrawerHeight] = usePreference<number>(
    "explore_drawer_height",
    280,
  );
  const [drawerOpen, setDrawerOpen] = usePreference<boolean>(
    "explore_drawer_open",
    true,
  );
  const [picked, setPicked] = useState<RecordRow | null>(null);
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(
    null,
  );
  const [exportOpen, setExportOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);

  const saveView = useMutationToast({
    mutationFn: (name: string) =>
      api.post<SavedView>(
        `/api/v1/projects/${projectId}/analytics/saved-views`,
        {
          body: {
            name,
            view: viewOfParams(writeExploreState(state)),
            schema_version: 2,
          },
        },
      ),
    invalidate: [queryKeys.savedViews(projectId)],
    success: t("View saved"),
    onSuccess: (view) => {
      setSaveOpen(false);
      setParams((p) => {
        p.set("view", view.id);
        return p;
      });
    },
  });
  const deleteView = useMutationToast({
    mutationFn: (id: string) =>
      api.delete<void>(
        `/api/v1/projects/${projectId}/analytics/saved-views/${id}`,
      ),
    invalidate: [queryKeys.savedViews(projectId)],
    success: t("View deleted"),
    onSuccess: () =>
      setParams((p) => {
        p.delete("view");
        return p;
      }),
  });
  function applyView(view: SavedView) {
    const next = paramsOfView(view.view as Record<string, string[]>);
    next.set("view", view.id);
    setParams(next);
  }

  const stripOpen = stripChoice ?? !(phone && selection !== null);
  const summary = useMemo(() => {
    const chosen = [
      ...state.entities.map((id) => names.get(id) ?? id.slice(0, 8)),
      ...state.devices.map((id) => names.get(id) ?? id.slice(0, 8)),
    ];
    const who =
      chosen.length === 0
        ? t("Nothing selected")
        : chosen.length <= 2
          ? chosen.join(", ")
          : `${chosen.slice(0, 2).join(", ")} +${chosen.length - 2}`;
    const period =
      state.range === "custom"
        ? t("Custom range")
        : state.range === "assignment"
          ? t("Since the device was assigned")
          : RANGE_PRESETS[state.range].label;
    return `${who} · ${period} · ${state.timezone}`;
  }, [state, names, t]);
  const loaded = records.rows.length;
  const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
  const progress = (
    <>
      <div className="h-2 w-32 shrink-0 overflow-hidden rounded bg-muted sm:w-48">
        <div
          className="h-2 bg-primary transition-[width]"
          style={{ width: `${records.status === "done" ? 100 : percent}%` }}
        />
      </div>
      <span className="truncate text-muted-foreground">
        {total === null
          ? t("Counting…")
          : records.status === "done"
            ? t("{{count}} records", { count: loaded })
            : t("{{loaded}} of {{total}} records", { loaded, total })}
      </span>
      {records.status === "loading" && (
        <Button
          variant="outline"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            records.stop();
          }}
        >
          {t("Stop")}
        </Button>
      )}
      {(records.status === "stopped" || records.status === "error") && (
        <Button
          variant="outline"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            records.restart();
          }}
        >
          {t("Load again")}
        </Button>
      )}
      {markedRowTime && (
        <span className="hidden truncate text-xs text-muted-foreground md:inline">
          {formatInZone(markedRowTime, state.timezone)}
          {state.at && hover === null ? ` · ${t("pinned")}` : ""}
        </span>
      )}
    </>
  );

  const table = (
    <VirtualTable
      rows={records.rows}
      columns={shown}
      timezone={state.timezone}
      height="100%"
      highlightTime={markedRowTime}
      follow={hovered?.source !== "table"}
      onRowHover={(row) =>
        setHovered(row ? { ms: Date.parse(row.time), source: "table" } : null)
      }
      onRowClick={(row: RecordRow) => {
        // a click pins the moment in every view and shows the record plainly
        pick(Date.parse(row.time));
        setPicked(row);
      }}
    />
  );
  const chartOptions = chartableColumns(columns).map((c) => ({
    value: c.key.slice(2),
    label: c.label,
  }));

  const tools = (
    <>
      {state.mode === "table" && (
        <MultiSelect
          options={columns.map((c) => ({ value: c.key, label: c.label }))}
          value={shown.map((c) => c.key)}
          onChange={(visible) =>
            setHiddenColumns(
              columns.filter((c) => !visible.includes(c.key)).map((c) => c.key),
            )
          }
          placeholder={t("Columns")}
          label={t("columns")}
          className="h-8 w-36"
        />
      )}
      {state.mode === "chart" && (
        <>
          <MultiSelect
            options={chartOptions}
            value={metricsOnChart}
            onChange={(v) => update({ metrics: v })}
            placeholder={t("Metrics")}
            label={t("metrics")}
            className="h-8 w-40"
            maxSelected={
              state.chart === "scatter" || state.chart === "histogram" ? 1 : 8
            }
          />
          {state.chart === "scatter" && (
            <Select
              value={state.xMetric ?? metricsOnChart[1] ?? ""}
              onValueChange={(v) => update({ xMetric: v })}
            >
              <SelectTrigger className="h-8 w-40" aria-label={t("X axis")}>
                <SelectValue placeholder={t("X axis")} />
              </SelectTrigger>
              <SelectContent>
                {chartOptions.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Select
            value={state.chart}
            onValueChange={(v) => update({ chart: v as ChartType })}
          >
            <SelectTrigger className="h-8 w-36" aria-label={t("Chart kind")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHART_TYPES.map((k) => (
                <SelectItem key={k} value={k}>
                  {t(CHART_LABELS[k])}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {aggregated && (
            <Select
              value={state.bucket}
              onValueChange={(v) => update({ bucket: v })}
            >
              <SelectTrigger className="h-8 w-28" aria-label={t("Bucket")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BUCKETS.map((b) => (
                  <SelectItem key={b} value={b}>
                    {b === "auto"
                      ? t("Automatic")
                      : b === "all"
                        ? t("Whole range")
                        : b}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Select
            value={currentView?.id ?? "none"}
            onValueChange={(id) => {
              const v = views.data?.items.find((x) => x.id === id);
              if (v) applyView(v);
            }}
          >
            <SelectTrigger className="h-8 w-36" aria-label={t("Saved views")}>
              <SelectValue placeholder={t("Saved views")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>
                {views.data?.items.length
                  ? t("Saved views")
                  : t("No saved views yet")}
              </SelectItem>
              {views.data?.items.map((v) => (
                <SelectItem key={v.id} value={v.id}>
                  {v.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => setSaveOpen(true)}
            disabled={!selection}
            aria-label={t("Save view")}
          >
            <Bookmark className="size-4" />
          </Button>
          {currentView &&
            (currentView.created_by === user?.id || canAdmin(role)) && (
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                aria-label={t("Delete saved view")}
                onClick={() => deleteView.mutate(currentView.id)}
              >
                <Trash2 className="size-4" />
              </Button>
            )}
        </>
      )}
    </>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b bg-card px-3 py-2 text-sm">
        {/* the header row stays; the selection and the tools fold away once a selection is
            made, so the table, the chart and the map get the room (folded first on a phone) */}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8 shrink-0"
            aria-expanded={stripOpen}
            aria-label={
              stripOpen ? t("Fold the selection") : t("Unfold the selection")
            }
            onClick={() => setStripChoice(!stripOpen)}
          >
            {stripOpen ? (
              <ChevronUp className="size-4" />
            ) : (
              <ChevronDown className="size-4" />
            )}
          </Button>
          {!stripOpen && (
            <button
              type="button"
              className="min-w-0 truncate text-left"
              title={summary}
              onClick={() => setStripChoice(true)}
            >
              {summary}
            </button>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <Tabs
              value={state.mode}
              onValueChange={(v) => update({ mode: v as ExploreMode })}
            >
              <TabsList className="h-8">
                <TabsTrigger value="table" className="h-7 gap-1 px-2">
                  <Table2 className="size-4" />
                  <span className="hidden sm:inline">{t("Table")}</span>
                </TabsTrigger>
                <TabsTrigger value="chart" className="h-7 gap-1 px-2">
                  <ChartLine className="size-4" />
                  <span className="hidden sm:inline">{t("Chart")}</span>
                </TabsTrigger>
                <TabsTrigger value="map" className="h-7 gap-1 px-2">
                  <MapIcon className="size-4" />
                  <span className="hidden sm:inline">{t("Map")}</span>
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => setExportOpen(true)}
              disabled={!selection}
              aria-label={t("Export")}
            >
              <Download className="size-4" />
              <span className="hidden sm:inline">{t("Export")}</span>
            </Button>
          </div>
        </div>
        {stripOpen && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <SelectionStrip
              state={state}
              entities={entities.data?.items ?? []}
              devices={devices.data?.items ?? []}
              groups={groups.data ?? []}
              oneEntity={oneEntity !== null}
              onChange={(patch) => update({ ...patch, at: null })}
            />
            {tools}
          </div>
        )}
      </div>

      <div className="relative min-h-0 flex-1">
        {!selection ? (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <EmptyState
              icon={ChartLine}
              title={t("Choose an entity or a device to start")}
              description={t(
                "Every record they produced in the period follows: as a table, on a chart, or on the map, one row per moment.",
              )}
            />
          </div>
        ) : (
          <>
            {state.mode === "table" && (
              <div className="absolute inset-0 flex flex-col gap-2 p-2">
                {records.error && (
                  <Callout kind="error">{records.error}</Callout>
                )}
                <div className="flex shrink-0 items-center gap-3 text-sm">
                  {progress}
                </div>
                <div className="relative min-h-0 flex-1">{table}</div>
              </div>
            )}
            {/* the chart or the map, ending where the drawer starts; nothing here in table
                mode, so the table gets every touch */}
            {state.mode !== "table" && (
              <div
                className="absolute inset-x-0 top-0"
                style={{
                  bottom: drawerSpace(drawerOpen, drawerHeight, phone),
                }}
              >
                {state.mode === "chart" &&
                  (groupsOnChart.length === 0 ? (
                    <div className="absolute inset-0 flex items-center justify-center p-6">
                      <EmptyState
                        icon={ChartLine}
                        title={
                          records.status === "loading" && loaded === 0
                            ? t("Loading…")
                            : t("Nothing to chart yet")
                        }
                        description={t(
                          "The chart draws the numeric metrics of the loaded rows; pick metrics in the strip once rows are here.",
                        )}
                      />
                    </div>
                  ) : (
                    <ExploreChart
                      groups={groupsOnChart}
                      kind={state.chart}
                      xLabel={
                        state.chart === "scatter"
                          ? (chartOptions.find(
                              (o) =>
                                o.value ===
                                (state.xMetric ?? metricsOnChart[1] ?? ""),
                            )?.label ?? null)
                          : null
                      }
                      phone={phone}
                      timezone={state.timezone}
                      marked={hover === null ? null : marked}
                      pinned={pinned}
                      onHover={onHover}
                      onPick={pick}
                    />
                  ))}
                {state.mode === "map" && (
                  <ExploreMap
                    tracks={tracks}
                    features={features.data?.items ?? []}
                    window={window}
                    timezone={state.timezone}
                    marked={marked}
                    fitKey={selectionKey}
                    onHover={onHover}
                    onPick={pick}
                  />
                )}
              </div>
            )}
            {state.mode !== "table" && aggregated && (
              <div className="pointer-events-none absolute top-3 right-14 left-3 z-10 flex justify-end">
                <span className="pointer-events-auto rounded-md border bg-card/95 px-2 py-1 text-xs text-muted-foreground">
                  {state.mode === "chart"
                    ? series.data
                      ? t(
                          "Above {{bound}} records: buckets of {{bucket}}; the drawer keeps loading the rows.",
                          {
                            bound: CANVAS_BOUND.toLocaleString(),
                            bucket: bucketLabel(series.data.bucket_seconds),
                          },
                        )
                      : t("Above {{bound}} records: the chart reads buckets.", {
                          bound: CANVAS_BOUND.toLocaleString(),
                        })
                    : t(
                        "Above {{bound}} records: the tracks are decimated to 5,000 points each.",
                        { bound: CANVAS_BOUND.toLocaleString() },
                      )}
                </span>
              </div>
            )}
            {state.mode !== "table" && (
              <Drawer
                height={drawerHeight}
                onHeight={setDrawerHeight}
                open={drawerOpen}
                onOpen={setDrawerOpen}
                phone={phone}
                bar={progress}
              >
                <div className="absolute inset-0 p-2">{table}</div>
              </Drawer>
            )}
          </>
        )}
      </div>

      <ExportDialog
        projectId={projectId}
        open={exportOpen}
        onOpenChange={setExportOpen}
        preset={{
          dataset: "records",
          entityIds: state.entities,
          deviceIds: state.devices,
          from: window.from,
          to: window.to,
          timezone: state.timezone,
          layout: "wide",
        }}
      />
      <RecordDialog
        row={picked}
        columns={columns}
        timezone={state.timezone}
        onClose={() => setPicked(null)}
        onSourceEvent={(id, ingestedAt) => {
          setPicked(null);
          setEvent({ id, ingestedAt });
        }}
      />
      <SourceEventDialog
        id={event?.id ?? null}
        ingestedAt={event?.ingestedAt ?? null}
        onClose={() => setEvent(null)}
      />
      <SaveViewDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        onSave={(name) => saveView.mutate(name)}
        pending={saveView.isPending}
      />
    </div>
  );
}

function SaveViewDialog({
  open,
  onOpenChange,
  onSave,
  pending,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onSave: (name: string) => void;
  pending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("Save this view")}</DialogTitle>
          <DialogDescription>
            {t(
              "The selection, the period, the mode and the chart, shared with the project.",
            )}
          </DialogDescription>
        </DialogHeader>
        <Field label={t("Name")} htmlFor="view-name">
          <Input
            id="view-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("Battery, last 30 days")}
          />
        </Field>
        <DialogFooter>
          <Button
            onClick={() => onSave(name.trim())}
            disabled={!name.trim() || pending}
          >
            {t("Save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
