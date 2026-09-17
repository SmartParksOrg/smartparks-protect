import { t } from "@/lib/i18nMark";
import { useTranslation } from "react-i18next";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  AnalysisEstimate,
  AnalysisRun,
  Device,
  DeviceType,
  Entity,
  EntityType,
  Page as PageType,
} from "@/api/types";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useGroups } from "@/hooks/useGroups";
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePermissions } from "@/hooks/useProjects";
import {
  devicePerformanceParameters,
  deviceSelection,
  type FormState,
} from "@/lib/analyses";
import { typePath } from "@/lib/entityTypes";
import { inputValue } from "@/lib/records";

const MAX_DEVICES = 100;
const RANGES: [string, string][] = [
  ["7d", t("Last 7 days")],
  ["30d", t("Last 30 days")],
  ["90d", t("Last 90 days")],
  ["1y", t("Last year")],
];

/**
 * The question form of the device performance page (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md,
 * section 7): which devices, chosen by name, through the entities they track, through entity
 * groups or entity types ("every device on a pangolin", Tim, 2026-09-16), or every device of
 * the project; a device type filter narrows a mixed selection to one type. Then the period
 * and the comparison. The estimate under it says how much the run will read; Run queues it.
 */
export function DevicePerformanceForm({
  projectId,
  state,
  onChange,
  onRun,
  editing = null,
}: {
  projectId: string;
  state: FormState;
  onChange: (patch: Partial<FormState>) => void;
  onRun: (run: AnalysisRun, replaced: boolean) => void;
  editing?: { name: string | null; shared: boolean } | null;
}) {
  const { t } = useTranslation();
  const { can } = usePermissions(projectId);
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, forAnalysis: true }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
  });
  const entities = useQuery({
    queryKey: queryKeys.entities(projectId),
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
  });
  const deviceTypes = useQuery({
    queryKey: queryKeys.deviceTypes,
    queryFn: () =>
      api.get<PageType<DeviceType>>("/api/v1/device-types", {
        query: { limit: 500 },
      }),
  });
  const entityTypes = useQuery({
    queryKey: queryKeys.entityTypes,
    queryFn: () =>
      api.get<PageType<EntityType>>("/api/v1/entity-types", {
        query: { limit: 500 },
      }),
  });
  const groups = useGroups(projectId);
  const items = devices.data?.items ?? [];
  const animals = entities.data?.items ?? [];
  const allEntityTypes = entityTypes.data?.items ?? [];
  // the entity types in use in the project, with their parents, so "Wildlife" picks every
  // subtype under it
  const usedEntityTypes = new Set(animals.map((e) => e.entity_type_id));
  for (const row of allEntityTypes)
    if (usedEntityTypes.has(row.id) && row.parent_id)
      usedEntityTypes.add(row.parent_id);
  const entityTypeOptions = allEntityTypes.filter((x) =>
    usedEntityTypes.has(x.id),
  );
  const usedDeviceTypes = new Set(items.map((d) => d.device_type_id));
  const deviceTypeOptions = (deviceTypes.data?.items ?? []).filter((x) =>
    usedDeviceTypes.has(x.id),
  );
  const selection = deviceSelection(
    state,
    items,
    animals,
    groups.data,
    allEntityTypes,
    MAX_DEVICES,
  );
  const parameters = devicePerformanceParameters(state, new Date(), selection);
  const estimate = useQuery({
    queryKey: queryKeys.analysisEstimate(projectId, parameters ?? {}),
    queryFn: () =>
      api.get<AnalysisEstimate>(
        `/api/v1/projects/${projectId}/analyses/estimate`,
        {
          query: {
            module: "device_performance",
            parameters: JSON.stringify(parameters),
          },
        },
      ),
    enabled: parameters !== null && can("analysis:run"),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const run = useMutationToast({
    mutationFn: async (replace: boolean) => {
      const created = await api.post<AnalysisRun>(
        `/api/v1/projects/${projectId}/analyses`,
        { body: { module: "device_performance", parameters } },
      );
      if (replace && editing && (editing.name || editing.shared))
        return api.patch<AnalysisRun>(
          `/api/v1/projects/${projectId}/analyses/${created.id}`,
          { body: { name: editing.name, shared: editing.shared } },
        );
      return created;
    },
    invalidate: [
      queryKeys.analyses(projectId, {
        module: "device_performance",
        recent: true,
      }),
    ],
    success: t("Analysis queued"),
    onSuccess: (r, replace) => onRun(r, replace),
  });
  // a source chosen switches "every device" off; "every device" clears the sources
  const source = (patch: Partial<FormState>) =>
    onChange({ ...patch, allDevices: false });
  const chooseAll = (on: boolean) =>
    onChange({
      allDevices: on,
      ...(on ? { devices: [], entities: [], groups: [], entityTypes: [] } : {}),
    });
  const e = estimate.data;
  const mayRun = can("analysis:run");
  const nothing = parameters === null;
  const emptied =
    !nothing || (selection.hasSources && selection.ids.length === 0);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label className="text-xs">{t("Devices")}</Label>
          <MultiSelect
            options={items.map((x) => ({
              value: x.id,
              label: x.entity_name ? `${x.name} (${x.entity_name})` : x.name,
            }))}
            value={state.devices}
            onChange={(v) => source({ devices: v.slice(0, MAX_DEVICES) })}
            placeholder={t("Choose devices")}
            label={t("devices")}
            className="h-8 w-52"
            maxSelected={MAX_DEVICES}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">{t("Tracking these entities")}</Label>
          <MultiSelect
            options={animals.map((x) => ({ value: x.id, label: x.name }))}
            value={state.entities}
            onChange={(v) => source({ entities: v })}
            placeholder={t("Choose entities")}
            label={t("entities")}
            className="h-8 w-48"
          />
        </div>
        {(groups.data?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <Label className="text-xs">{t("Groups")}</Label>
            <MultiSelect
              options={(groups.data ?? []).map((g) => ({
                value: g.id,
                label: g.name,
              }))}
              value={state.groups}
              onChange={(v) => source({ groups: v })}
              placeholder={t("Add groups")}
              label={t("groups")}
              className="h-8 w-40"
            />
          </div>
        )}
        {entityTypeOptions.length > 0 && (
          <div className="space-y-1">
            <Label className="text-xs">{t("Entity types")}</Label>
            <MultiSelect
              options={entityTypeOptions.map((x) => ({
                value: x.id,
                label: typePath(allEntityTypes, x.id),
              }))}
              value={state.entityTypes}
              onChange={(v) => source({ entityTypes: v })}
              placeholder={t("Add entity types")}
              label={t("entity types")}
              className="h-8 w-44"
            />
          </div>
        )}
        <label className="flex h-8 items-center gap-2 text-sm">
          <Switch
            checked={state.allDevices}
            onCheckedChange={chooseAll}
            aria-label={t("Every device")}
          />
          {t("Every device")}
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {deviceTypeOptions.length > 0 && (
          <div className="space-y-1">
            <Label className="text-xs">{t("Only this device type")}</Label>
            <Select
              value={state.deviceType ?? "any"}
              onValueChange={(v) =>
                onChange({ deviceType: v === "any" ? null : v })
              }
            >
              <SelectTrigger
                className="h-8 w-44"
                aria-label={t("Only this device type")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="any">{t("Any device type")}</SelectItem>
                {deviceTypeOptions.map((x) => (
                  <SelectItem key={x.id} value={x.id}>
                    {x.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="space-y-1">
          <Label className="text-xs">{t("Period")}</Label>
          <Select
            value={state.range}
            onValueChange={(v) => onChange({ range: v })}
          >
            <SelectTrigger className="h-8 w-36" aria-label={t("Period")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGES.map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {t(label)}
                </SelectItem>
              ))}
              <SelectItem value="custom">{t("Custom")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {state.range === "custom" && (
          <>
            <Input
              type="datetime-local"
              className="h-8 w-48"
              aria-label={t("From")}
              value={inputValue(state.from)}
              onChange={(ev) =>
                onChange({
                  from: ev.target.value
                    ? new Date(ev.target.value).toISOString()
                    : null,
                })
              }
            />
            <Input
              type="datetime-local"
              className="h-8 w-48"
              aria-label={t("To")}
              value={inputValue(state.to)}
              onChange={(ev) =>
                onChange({
                  to: ev.target.value
                    ? new Date(ev.target.value).toISOString()
                    : null,
                })
              }
            />
          </>
        )}
        <label className="flex h-8 items-center gap-2 text-sm">
          <Switch
            checked={state.compare === "previous"}
            onCheckedChange={(v) =>
              onChange({ compare: v ? "previous" : null })
            }
            aria-label={t("Compare with the period before")}
          />
          {t("Compare with the period before")}
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {selection.hasSources &&
          selection.ids.length === 0 &&
          !state.allDevices
            ? t("No device of this type among the chosen ones.")
            : nothing
              ? t(
                  "Choose devices, entities, groups or entity types, or every device, and a period.",
                )
              : e
                ? e.ok
                  ? t(
                      "{{subjects}} devices over {{days}} days, {{fixes}} fixes to read.",
                      {
                        subjects: e.subjects,
                        days: Math.round(e.days),
                        fixes: e.fixes,
                      },
                    )
                  : (e.reasons ?? []).join(" ")
                : estimate.isError
                  ? estimate.error.message
                  : t("Estimating…")}
          {emptied && selection.excludedByType > 0 && (
            <span className="ml-1">
              {t("{{count}} devices of another type are left out.", {
                count: selection.excludedByType,
              })}
            </span>
          )}
        </p>
        <div className="flex gap-2">
          {editing && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!mayRun || !e?.ok || run.isPending}
              onClick={() => run.mutate(true)}
            >
              {t("Run and replace")}
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            disabled={!mayRun || !e?.ok || run.isPending}
            onClick={() => run.mutate(false)}
          >
            <Play className="size-4" /> {editing ? t("Run as new") : t("Run")}
          </Button>
        </div>
      </div>
    </div>
  );
}
