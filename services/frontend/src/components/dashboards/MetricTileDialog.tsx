import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  Entity,
  MetricWithData,
  Page as PageType,
} from "@/api/types";
import { MultiSelect, type Option } from "@/components/analytics/MultiSelect";
import { Field } from "@/components/common/FormField";
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
import { useMetricsByKey } from "@/hooks/useMetrics";
import {
  type Aggregate,
  RANGE_PRESETS,
  type RangePreset,
  rangeFor,
} from "@/lib/analytics";
import {
  AGGREGATE_LABELS,
  MAX_TILE_METRICS,
  MAX_TILE_SUBJECTS,
  METRIC_DISPLAY_LABELS,
  METRIC_DISPLAYS,
  type MetricDisplay,
  type MetricTileOptions,
  TILE_AGGREGATES,
} from "@/lib/dashboards";
import { scaledUnit } from "@/lib/format";
import { CATEGORY_LABELS, groupMetrics } from "@/lib/metricGroups";

export interface MetricTileDraft {
  title: string;
  options: MetricTileOptions;
}

/** The settings of a metric tile (decision D309): which metrics, of which entities or
 * devices, over which period, and how they are drawn. The metrics offered are the ones the
 * project has values of in the last year; one that stopped reporting stays in the list while
 * the tile names it. */
export function MetricTileDialog({
  projectId,
  initial,
  adding,
  onSave,
  onClose,
}: {
  projectId: string;
  initial: MetricTileDraft;
  /** A new tile, as opposed to one being changed. */
  adding: boolean;
  onSave: (draft: MetricTileDraft) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(initial.title);
  const [options, setOptions] = useState<MetricTileOptions>(initial.options);
  const set = (patch: Partial<MetricTileOptions>) =>
    setOptions((current) => ({ ...current, ...patch }));
  const registry = useMetricsByKey();
  const withData = useQuery({
    queryKey: queryKeys.analyticsMetrics(projectId, { range: "1y" }),
    queryFn: () =>
      api.get<MetricWithData[]>(
        `/api/v1/projects/${projectId}/analytics/metrics`,
        { query: rangeFor("1y") },
      ),
  });
  const entities = useQuery({
    queryKey: queryKeys.entities(projectId),
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
  });
  const devices = useQuery({
    queryKey: queryKeys.devices({ project: projectId, tile: true }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
    enabled: options.group_by === "device",
  });
  const metricOptions = useMemo<Option[]>(() => {
    // what can be aggregated can be drawn: numbers, and yes or no as a share
    const offered = (withData.data ?? [])
      .filter((m) => m.value_type === "numeric" || m.value_type === "boolean")
      .map((m) => ({
        metric_key: m.key,
        label: t(m.label),
        unit: m.unit,
        category: m.category,
        hint: m.count.toLocaleString(),
      }));
    // a chosen metric without values this year is still the tile's
    for (const key of options.metrics)
      if (!offered.some((m) => m.metric_key === key))
        offered.push({
          metric_key: key,
          label: t(registry.get(key)?.label ?? key),
          unit: registry.get(key)?.unit ?? null,
          category: registry.get(key)?.category ?? "uncategorized",
          hint: "0",
        });
    return groupMetrics(
      offered,
      (key) => offered.find((m) => m.metric_key === key)?.category,
    ).flatMap(([category, items]) =>
      items.map((m) => ({
        value: m.metric_key,
        label: m.unit ? `${m.label} (${scaledUnit(m.unit).unit})` : m.label,
        hint: m.hint,
        group: CATEGORY_LABELS[category]
          ? t(CATEGORY_LABELS[category])
          : category,
      })),
    );
  }, [withData.data, registry, options.metrics, t]);
  const subjectOptions = useMemo<Option[]>(
    () =>
      (options.group_by === "entity"
        ? (entities.data?.items ?? [])
        : (devices.data?.items ?? [])
      )
        .map((o) => ({ value: o.id, label: o.name }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [options.group_by, entities.data, devices.data],
  );
  const subjects =
    options.group_by === "entity" ? options.entity_ids : options.device_ids;
  const one = options.display === "number";
  const graph = options.display === "line" || options.display === "bar";
  const ready =
    options.metrics.length > 0 && (!one || options.metrics.length === 1);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {adding ? t("Add a metric tile") : t("Change the metric tile")}
          </DialogTitle>
          <DialogDescription>
            {t(
              "A graph, a table or a number of any metric the project measures. The tile follows the clock: its period ends now.",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label={t("Show as")} htmlFor="tile-display">
            <Select
              value={options.display}
              onValueChange={(v) => {
                const display = v as MetricDisplay;
                set({
                  display,
                  metrics:
                    display === "number"
                      ? options.metrics.slice(0, 1)
                      : options.metrics,
                });
              }}
            >
              <SelectTrigger id="tile-display">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {METRIC_DISPLAYS.map((d) => (
                  <SelectItem key={d} value={d}>
                    {t(METRIC_DISPLAY_LABELS[d])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field
            label={one ? t("Metric") : t("Metrics")}
            htmlFor="tile-metrics"
            hint={
              one
                ? t("A number shows one metric.")
                : t("Up to {{max}}; metrics of one unit read best together.", {
                    max: MAX_TILE_METRICS,
                  })
            }
          >
            <MultiSelect
              options={metricOptions}
              value={options.metrics}
              onChange={(metrics) => set({ metrics })}
              placeholder={
                withData.isLoading ? t("Loading…") : t("Choose a metric")
              }
              label={t("metrics")}
              maxSelected={one ? 1 : MAX_TILE_METRICS}
              className="w-full"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("A line or a row per")} htmlFor="tile-group">
              <Select
                value={options.group_by}
                onValueChange={(v) =>
                  set({ group_by: v as MetricTileOptions["group_by"] })
                }
              >
                <SelectTrigger id="tile-group">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="entity">{t("Entity")}</SelectItem>
                  <SelectItem value="device">{t("Device")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label={t("Period")} htmlFor="tile-range">
              <Select
                value={options.range}
                onValueChange={(v) => set({ range: v as RangePreset })}
              >
                <SelectTrigger id="tile-range">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(RANGE_PRESETS) as RangePreset[]).map((r) => (
                    <SelectItem key={r} value={r}>
                      {t(RANGE_PRESETS[r].label)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field
            label={options.group_by === "entity" ? t("Entities") : t("Devices")}
            htmlFor="tile-subjects"
            hint={t(
              "Leave empty for the first of the project by name that fit the tile.",
            )}
          >
            <MultiSelect
              options={subjectOptions}
              value={subjects}
              onChange={(ids) =>
                set(
                  options.group_by === "entity"
                    ? { entity_ids: ids }
                    : { device_ids: ids },
                )
              }
              placeholder={t("All that fit")}
              label={
                options.group_by === "entity" ? t("entities") : t("devices")
              }
              maxSelected={MAX_TILE_SUBJECTS}
              className="w-full"
            />
          </Field>
          {graph && (
            <Field
              label={t("Value per step of time")}
              htmlFor="tile-aggregate"
              hint={t(
                "The step follows the period, so the graph never holds more points than it can draw.",
              )}
            >
              <Select
                value={options.aggregate}
                onValueChange={(v) => set({ aggregate: v as Aggregate })}
              >
                <SelectTrigger id="tile-aggregate">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TILE_AGGREGATES.map((a) => (
                    <SelectItem key={a} value={a}>
                      {t(AGGREGATE_LABELS[a])}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field
            label={t("Title")}
            htmlFor="tile-title"
            hint={t("Empty names the tile after its metric.")}
          >
            <Input
              id="tile-title"
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("Cancel")}
          </Button>
          <Button
            disabled={!ready}
            onClick={() => onSave({ title: title.trim(), options })}
          >
            {adding ? t("Add tile") : t("Apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
