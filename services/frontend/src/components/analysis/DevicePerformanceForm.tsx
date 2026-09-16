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
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePermissions } from "@/hooks/useProjects";
import { devicePerformanceParameters, type FormState } from "@/lib/analyses";
import { inputValue } from "@/lib/records";

const MAX_DEVICES = 100;
const RANGES: [string, string][] = [
  ["7d", "Last 7 days"],
  ["30d", "Last 30 days"],
  ["90d", "Last 90 days"],
  ["1y", "Last year"],
];

/**
 * The question form of the device performance page (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md,
 * section 7): which devices (by name, every device of a type, or every device of the
 * project), which period, compared with the period before or not. The estimate under it says
 * how much the run will read; Run queues the analysis.
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
  const types = useQuery({
    queryKey: queryKeys.deviceTypes,
    queryFn: () =>
      api.get<PageType<DeviceType>>("/api/v1/device-types", {
        query: { limit: 500 },
      }),
  });
  const items = devices.data?.items ?? [];
  const usedTypes = new Set(items.map((d) => d.device_type_id));
  const typeOptions = (types.data?.items ?? []).filter((x) =>
    usedTypes.has(x.id),
  );
  const parameters = devicePerformanceParameters(state);
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
  // the three ways to choose exclude one another: a choice clears the other two
  const chooseDevices = (ids: string[]) =>
    onChange({
      devices: ids.slice(0, MAX_DEVICES),
      deviceType: null,
      allDevices: false,
    });
  const chooseType = (id: string) =>
    onChange({ devices: [], deviceType: id, allDevices: false });
  const chooseAll = (on: boolean) =>
    onChange({ devices: [], deviceType: null, allDevices: on });
  const e = estimate.data;
  const mayRun = can("analysis:run");
  const typeName = (id: string | null) =>
    typeOptions.find((x) => x.id === id)?.label ?? "";
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
            onChange={chooseDevices}
            placeholder={
              state.deviceType
                ? t("Every {{type}}", { type: typeName(state.deviceType) })
                : state.allDevices
                  ? t("Every device")
                  : t("Choose devices")
            }
            label={t("devices")}
            className="h-8 w-56"
            maxSelected={MAX_DEVICES}
          />
        </div>
        {typeOptions.length > 0 && (
          <Select value={state.deviceType ?? "none"} onValueChange={chooseType}>
            <SelectTrigger
              className="h-8 w-40"
              aria-label={t("Devices of a type")}
            >
              <SelectValue placeholder={t("Devices of a type")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>
                {t("Devices of a type")}
              </SelectItem>
              {typeOptions.map((x) => (
                <SelectItem key={x.id} value={x.id}>
                  {x.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <label className="flex h-8 items-center gap-2 text-sm">
          <Switch
            checked={state.allDevices}
            onCheckedChange={chooseAll}
            aria-label={t("Every device")}
          />
          {t("Every device")}
        </label>
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
          {parameters === null
            ? t("Choose devices, a device type or every device, and a period.")
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
