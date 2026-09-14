import { useTranslation } from "react-i18next";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Play } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  AnalysisEstimate,
  AnalysisRun,
  Entity,
  EntityType,
  Page as PageType,
} from "@/api/types";
import { useResolveSubjects } from "@/components/analysis/subjects";
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
  ALL_METHODS,
  DEFAULT_METHOD,
  type FormState,
  groupWithSubgroups,
  type MethodOptions,
  movementParameters,
} from "@/lib/analyses";
import { inputValue } from "@/lib/records";

const MAX_SUBJECTS = 25;
const RANGES: [string, string][] = [
  ["7d", "Last 7 days"],
  ["30d", "Last 30 days"],
  ["90d", "Last 90 days"],
  ["1y", "Last year"],
];

/**
 * The question form of the movement page (plan, section 8.7): which animals, which period,
 * compared with what, and the method's options folded away with their defaults. The estimate
 * under it says how much the run will read and what to change when a bound is crossed; Run
 * queues the analysis and hands the run back.
 */
export function MovementForm({
  projectId,
  state,
  onChange,
  onRun,
}: {
  projectId: string;
  state: FormState;
  onChange: (patch: Partial<FormState>) => void;
  onRun: (run: AnalysisRun) => void;
}) {
  const { t } = useTranslation();
  const { can } = usePermissions(projectId);
  const [methodOpen, setMethodOpen] = useState(false);
  const entities = useQuery({
    queryKey: queryKeys.entities(projectId),
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
  });
  const groups = useGroups(projectId);
  const types = useQuery({
    queryKey: queryKeys.entityTypes,
    queryFn: () =>
      api.get<PageType<EntityType>>("/api/v1/entity-types", {
        query: { limit: 500 },
      }),
  });
  const items = entities.data?.items ?? [];
  useResolveSubjects(
    state,
    entities.data?.items,
    groups.data,
    MAX_SUBJECTS,
    onChange,
  );
  const usedTypes = new Set(items.map((e) => e.entity_type_id));
  const typeOptions = (types.data?.items ?? []).filter((x) =>
    usedTypes.has(x.id),
  );
  const parameters = movementParameters(state);
  const estimate = useQuery({
    queryKey: queryKeys.analysisEstimate(projectId, parameters ?? {}),
    queryFn: () =>
      api.get<AnalysisEstimate>(
        `/api/v1/projects/${projectId}/analyses/estimate`,
        {
          query: { module: "movement", parameters: JSON.stringify(parameters) },
        },
      ),
    enabled: parameters !== null && can("analysis:run"),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const run = useMutationToast({
    mutationFn: () =>
      api.post<AnalysisRun>(`/api/v1/projects/${projectId}/analyses`, {
        body: { module: "movement", parameters },
      }),
    invalidate: [
      queryKeys.analyses(projectId, { module: "movement", recent: true }),
    ],
    success: t("Analysis queued"),
    onSuccess: (r) => onRun(r),
  });
  const addAll = (ids: string[]) =>
    onChange({
      entities: [...new Set([...state.entities, ...ids])].slice(
        0,
        MAX_SUBJECTS,
      ),
    });
  const method = (patch: Partial<MethodOptions>) =>
    onChange({ method: { ...state.method, ...patch } });
  const e = estimate.data;
  const mayRun = can("analysis:run");
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label className="text-xs">{t("Subjects")}</Label>
          <MultiSelect
            options={items.map((x) => ({ value: x.id, label: x.name }))}
            value={state.entities}
            onChange={(v) => onChange({ entities: v })}
            placeholder={t("Choose animals")}
            label={t("animals")}
            className="h-8 w-48"
            maxSelected={MAX_SUBJECTS}
          />
        </div>
        {(groups.data?.length ?? 0) > 0 && (
          <Select
            value="none"
            onValueChange={(id) => {
              const inside = groupWithSubgroups(groups.data ?? [], id);
              addAll(
                items
                  .filter((x) => x.group_id && inside.has(x.group_id))
                  .map((x) => x.id),
              );
            }}
          >
            <SelectTrigger className="h-8 w-36" aria-label={t("Add a group")}>
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
        )}
        {typeOptions.length > 0 && (
          <Select
            value="none"
            onValueChange={(id) =>
              addAll(
                items.filter((x) => x.entity_type_id === id).map((x) => x.id),
              )
            }
          >
            <SelectTrigger className="h-8 w-36" aria-label={t("Add a type")}>
              <SelectValue placeholder={t("Add a type")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>
                {t("Add a type")}
              </SelectItem>
              {typeOptions.map((x) => (
                <SelectItem key={x.id} value={x.id}>
                  {x.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <div className="space-y-1">
          <Label className="text-xs">{t("Period")}</Label>
          <Select
            value={state.range}
            onValueChange={(v) => onChange({ range: v })}
          >
            <SelectTrigger className="h-8 w-40" aria-label={t("Period")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGES.map(([k, label]) => (
                <SelectItem key={k} value={k}>
                  {t(label)}
                </SelectItem>
              ))}
              <SelectItem value="custom">{t("Custom range")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {state.range === "custom" && (
          <>
            <Input
              type="datetime-local"
              aria-label={t("From")}
              className="h-8 w-48"
              value={inputValue(state.from)}
              onChange={(ev) => onChange({ from: ev.target.value })}
            />
            <Input
              type="datetime-local"
              aria-label={t("To")}
              className="h-8 w-48"
              value={inputValue(state.to)}
              onChange={(ev) => onChange({ to: ev.target.value })}
            />
          </>
        )}
        <div className="space-y-1">
          <Label className="text-xs">{t("Compare with")}</Label>
          <Select
            value={state.compare ?? "none"}
            onValueChange={(v) =>
              onChange({ compare: v === "none" ? null : v })
            }
          >
            <SelectTrigger className="h-8 w-40" aria-label={t("Compare with")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t("Nothing")}</SelectItem>
              <SelectItem value="previous">{t("The period before")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {mayRun && (
          <Button
            type="button"
            size="sm"
            className="h-8"
            disabled={!parameters || run.isPending || (e ? !e.ok : false)}
            onClick={() => run.mutate()}
          >
            <Play className="size-4" /> {t("Run")}
          </Button>
        )}
      </div>
      <button
        type="button"
        className="flex items-center gap-1 text-xs text-muted-foreground"
        onClick={() => setMethodOpen((o) => !o)}
        aria-expanded={methodOpen}
      >
        {methodOpen ? (
          <ChevronDown className="size-3.5" />
        ) : (
          <ChevronRight className="size-3.5" />
        )}
        {t("Method")}
        {!methodOpen && (
          <span className="ml-1">
            {t(
              "gap {{gap}} h · max speed {{speed}} m/s · cell {{cell}} m · {{methods}}",
              {
                gap: state.method.gap,
                speed: state.method.speed_max,
                cell: state.method.cell,
                methods:
                  state.method.methods.length === 0
                    ? t("no home range")
                    : state.method.methods
                        .map((m) => m.toUpperCase())
                        .join(", "),
              },
            )}
          </span>
        )}
      </button>
      {methodOpen && (
        <div className="flex flex-wrap items-end gap-3 rounded-md border bg-muted/30 p-3">
          <NumberField
            label={t("Gap threshold (hours)")}
            value={state.method.gap}
            min={0.25}
            max={168}
            step={0.25}
            onChange={(v) => method({ gap: v })}
          />
          <NumberField
            label={t("Maximum plausible speed (m/s)")}
            value={state.method.speed_max}
            min={0.5}
            max={100}
            step={0.5}
            onChange={(v) => method({ speed_max: v })}
          />
          <NumberField
            label={t("Grid cell (m)")}
            value={state.method.cell}
            min={10}
            max={5000}
            step={10}
            onChange={(v) => method({ cell: v })}
          />
          {ALL_METHODS.map((m) => (
            <label key={m} className="flex items-center gap-2 text-sm">
              <Switch
                checked={state.method.methods.includes(m)}
                onCheckedChange={(on) =>
                  method({
                    methods: on
                      ? ALL_METHODS.filter(
                          (x) => x === m || state.method.methods.includes(x),
                        )
                      : state.method.methods.filter((x) => x !== m),
                  })
                }
                aria-label={m}
              />
              {m === "mcp"
                ? t("MCP 95%")
                : m === "kde"
                  ? t("KDE 50% and 95%")
                  : t("Clusters")}
            </label>
          ))}
          {state.method.methods.includes("kde") && (
            <div className="space-y-1">
              <Label className="text-xs">{t("KDE bandwidth (m)")}</Label>
              <Input
                type="number"
                className="h-8 w-32"
                placeholder={t("automatic")}
                min={1}
                value={state.method.kde_bandwidth ?? ""}
                onChange={(ev) =>
                  method({
                    kde_bandwidth: ev.target.value
                      ? Number(ev.target.value) || null
                      : null,
                  })
                }
              />
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange({ method: DEFAULT_METHOD })}
          >
            {t("Defaults")}
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {!parameters
          ? t("Choose at least one animal and a period.")
          : !mayRun
            ? t("Your role can read results but not start a run.")
            : e
              ? e.ok
                ? t(
                    "{{subjects}} animals, {{days}} days, about {{fixes}} fixes.",
                    {
                      subjects: e.subjects,
                      days: e.days,
                      fixes: e.fixes.toLocaleString(),
                    },
                  )
                : e.reasons?.join(" ") || t("The run is too large.")
              : t("Estimating…")}
      </p>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        className="h-8 w-32"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(ev) => {
          const n = Number(ev.target.value);
          if (Number.isFinite(n) && n >= min && n <= max) onChange(n);
        }}
      />
    </div>
  );
}
