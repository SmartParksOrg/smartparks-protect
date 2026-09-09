import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ChartLine, Download, Map as MapIcon, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  Entity,
  EntityAssignment,
  Metric,
  Page as PageType,
  Position,
  RecordRow,
} from "@/api/types";
import { ExportDialog } from "@/components/analytics/ExportDialog";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { Callout } from "@/components/common/Callout";
import { EmptyState } from "@/components/common/EmptyState";
import { Field } from "@/components/common/FormField";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { MiniMap } from "@/components/map/MiniMap";
import { Sparkline, SparklineDialog } from "@/components/records/Sparkline";
import { VirtualTable } from "@/components/records/VirtualTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGroups } from "@/hooks/useGroups";
import { usePreference } from "@/hooks/usePreference";
import { useRecords } from "@/hooks/useRecords";
import { browserTimezone, RANGE_PRESETS, TIMEZONES } from "@/lib/analytics";
import {
  columnsOf,
  readRecordsState,
  type RecordColumn,
  type RecordsState,
  seriesOf,
  windowFor,
  writeRecordsState,
} from "@/lib/records";

/**
 * The records view of the explorer (phase 20, decisions D142 to D146): pick entities and
 * devices, a period and the columns, and get everything they produced, one row per moment,
 * loaded page after page with a progress bar, with a small chart per numeric column and the
 * track of the loaded rows on a map. The Analysis tab takes the selection over.
 */
export function RecordsView({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => readRecordsState(params), [params]);
  const update = (patch: Partial<RecordsState>) =>
    setParams(writeRecordsState({ ...readRecordsState(params), ...patch }));

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
        {
          query: { entity_id: oneEntity, limit: 500 },
        },
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
  const records = useRecords(projectId, selection);

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
  const columns = useMemo(
    () => columnsOf(records.rows, metricLabels),
    [records.rows, metricLabels],
  );
  const [hiddenColumns, setHiddenColumns] = usePreference<string[]>(
    "records_hidden_columns",
    [],
  );
  const shown = columns.filter((c) => !hiddenColumns.includes(c.key));
  const chartColumns = columns.filter(
    (c) => c.numeric && !["lat", "lon", "accuracy_m"].includes(c.key),
  );
  const [enlarged, setEnlarged] = useState<RecordColumn | null>(null);
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(
    null,
  );
  const [exportOpen, setExportOpen] = useState(false);
  // the charts and the map are off in the first look (Tim, 2026-09-09: the table alone is clearer)
  const [chartsOpen, setChartsOpen] = useState(false);

  const total = records.total;
  const loaded = records.rows.length;
  const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
  const mapPositions = useMemo(
    () =>
      records.rows
        .filter((r) => r.position)
        .slice(0, 500)
        .map((r) => ({
          id: r.position!.id,
          time: r.time,
          geometry: {
            type: "Point",
            coordinates: [r.position!.lon, r.position!.lat],
          },
        })) as unknown as Position[],
    [records.rows],
  );
  const analysisParams = useMemo(() => {
    const q = new URLSearchParams();
    q.set("mode", "analysis");
    for (const e of state.entities) q.append("entity", e);
    for (const c of columns
      .filter((c) => c.kind === "metric" && c.numeric)
      .slice(0, 20))
      q.append("metric", c.key.slice(2));
    q.set(
      "range",
      state.range === "custom" || state.range === "assignment"
        ? "30d"
        : state.range,
    );
    q.set("tz", state.timezone);
    return q.toString();
  }, [columns, state]);

  const groupEntities = (groupId: string) =>
    (entities.data?.items ?? [])
      .filter((e) => e.group_id === groupId)
      .map((e) => e.id);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Field label={t("Entities")} htmlFor="rec-entities">
          <MultiSelect
            options={(entities.data?.items ?? []).map((e) => ({
              value: e.id,
              label: e.name,
            }))}
            value={state.entities}
            onChange={(v) => update({ entities: v })}
            placeholder={t("Choose entities")}
            label={t("entities")}
            className="w-full"
            maxSelected={500}
          />
        </Field>
        <Field label={t("Devices")} htmlFor="rec-devices">
          <MultiSelect
            options={(devices.data?.items ?? []).map((d) => ({
              value: d.id,
              label: d.name,
            }))}
            value={state.devices}
            onChange={(v) => update({ devices: v })}
            placeholder={t("Choose devices")}
            label={t("devices")}
            className="w-full"
            maxSelected={500}
          />
        </Field>
        <Field
          label={t("Group")}
          htmlFor="rec-group"
          hint={t("Adds every entity of the group")}
        >
          <Select
            value="none"
            onValueChange={(id) =>
              update({
                entities: [
                  ...new Set([...state.entities, ...groupEntities(id)]),
                ],
              })
            }
          >
            <SelectTrigger id="rec-group">
              <SelectValue placeholder={t("Add a group")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>
                {t("Add a group")}
              </SelectItem>
              {(groups.data ?? []).map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("Period")} htmlFor="rec-range">
          <Select
            value={state.range}
            onValueChange={(v) => update({ range: v as RecordsState["range"] })}
          >
            <SelectTrigger id="rec-range">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(RANGE_PRESETS).map(([k, p]) => (
                <SelectItem key={k} value={k}>
                  {p.label}
                </SelectItem>
              ))}
              <SelectItem value="custom">{t("Custom range")}</SelectItem>
              {oneEntity && (
                <SelectItem value="assignment">
                  {t("Since the device was assigned")}
                </SelectItem>
              )}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("Timezone")} htmlFor="rec-tz">
          <Select
            value={state.timezone}
            onValueChange={(v) => update({ timezone: v })}
          >
            <SelectTrigger id="rec-tz">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[...new Set([browserTimezone(), ...TIMEZONES])].map((z) => (
                <SelectItem key={z} value={z}>
                  {z}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {state.range === "custom" && (
          <>
            <Field label={t("From")} htmlFor="rec-from">
              <Input
                id="rec-from"
                type="datetime-local"
                value={state.from ?? ""}
                onChange={(e) => update({ from: e.target.value })}
              />
            </Field>
            <Field label={t("To")} htmlFor="rec-to">
              <Input
                id="rec-to"
                type="datetime-local"
                value={state.to ?? ""}
                onChange={(e) => update({ to: e.target.value })}
              />
            </Field>
          </>
        )}
      </div>

      {!selection ? (
        <EmptyState
          icon={ChartLine}
          title={t("Choose an entity or a device to start")}
          description={t(
            "Every record they produced in the period follows, one row per moment with the position and the values of that moment.",
          )}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <div className="h-2 min-w-40 flex-1 overflow-hidden rounded bg-muted">
              <div
                className="h-2 bg-primary transition-[width]"
                style={{
                  width: `${records.status === "done" ? 100 : percent}%`,
                }}
              />
            </div>
            <span className="text-muted-foreground">
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
                className="h-7"
                onClick={records.stop}
              >
                <Square className="size-3" /> {t("Stop")}
              </Button>
            )}
            {(records.status === "stopped" || records.status === "error") && (
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                onClick={records.restart}
              >
                {t("Load again")}
              </Button>
            )}
            <MultiSelect
              options={columns.map((c) => ({ value: c.key, label: c.label }))}
              value={shown.map((c) => c.key)}
              onChange={(visible) =>
                setHiddenColumns(
                  columns
                    .filter((c) => !visible.includes(c.key))
                    .map((c) => c.key),
                )
              }
              placeholder={t("Columns")}
              label={t("columns")}
              className="ml-auto w-44"
            />
            <Button
              variant={chartsOpen ? "default" : "outline"}
              size="sm"
              className="h-7"
              aria-pressed={chartsOpen}
              onClick={() => setChartsOpen((o) => !o)}
            >
              <MapIcon className="size-3" />{" "}
              {chartsOpen ? t("Hide charts") : t("Charts and map")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7"
              onClick={() => setExportOpen(true)}
            >
              <Download className="size-3" /> {t("Export")}
            </Button>
            <Button asChild variant="outline" size="sm" className="h-7">
              <Link to={`?${analysisParams}`}>
                <ChartLine className="size-3" /> {t("Analyse these")}
              </Link>
            </Button>
          </div>
          {records.error && <Callout kind="error">{records.error}</Callout>}
          {total !== null && total > 50_000 && records.status === "loading" && (
            <Callout kind="info">
              {t(
                "A large selection: the rows keep loading, and an export gives them as one file.",
              )}
            </Callout>
          )}
          {chartsOpen && (
            <div className="grid gap-3 lg:grid-cols-[1fr_16rem]">
              <div className="flex flex-wrap gap-2">
                {chartColumns
                  .filter((c) => seriesOf(records.rows, c).length > 1)
                  .map((c) => (
                    <button
                      key={c.key}
                      type="button"
                      className="rounded-md border bg-card p-2 text-left hover:bg-muted/50"
                      onClick={() => setEnlarged(c)}
                      title={t("Enlarge")}
                    >
                      <div className="text-xs text-muted-foreground">
                        {c.label}
                        {c.unit ? ` (${c.unit})` : ""}
                      </div>
                      <Sparkline points={seriesOf(records.rows, c)} />
                    </button>
                  ))}
              </div>
              {mapPositions.length > 0 && (
                <div className="h-40 lg:h-auto">
                  <MiniMap
                    positions={mapPositions}
                    to={`/projects/${projectId}/map${state.entities[0] ? `?entity=${state.entities[0]}` : ""}`}
                  />
                </div>
              )}
            </div>
          )}
          <VirtualTable
            rows={records.rows}
            columns={shown}
            timezone={state.timezone}
            onRowClick={(row: RecordRow) => {
              if (row.source_event_id != null && row.source_event_ingested_at)
                setEvent({
                  id: row.source_event_id,
                  ingestedAt: row.source_event_ingested_at,
                });
            }}
          />
        </>
      )}
      <SparklineDialog
        title={enlarged?.label ?? null}
        unit={enlarged?.unit}
        points={enlarged ? seriesOf(records.rows, enlarged) : []}
        timezone={state.timezone}
        onClose={() => setEnlarged(null)}
      />
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
      <SourceEventDialog
        id={event?.id ?? null}
        ingestedAt={event?.ingestedAt ?? null}
        onClose={() => setEvent(null)}
      />
    </div>
  );
}
