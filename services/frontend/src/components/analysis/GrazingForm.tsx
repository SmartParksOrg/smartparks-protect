import { t } from "@/lib/i18nMark";
import { useTranslation } from "react-i18next";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Play } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  AnalysisEstimate,
  AnalysisRun,
  Entity,
  EntityType,
  Feature,
  Page as PageType,
} from "@/api/types";
import { membersOf, useResolveSubjects } from "@/components/analysis/subjects";
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
  DEFAULT_GRAZING,
  DEFAULT_METHOD,
  type FormState,
  type GrazingOptions,
  grazingParameters,
  withGroupMembers,
  isManagementUnit,
} from "@/lib/analyses";
import { inputValue } from "@/lib/records";

const MAX_ANIMALS = 100;
const MAX_AREAS = 50;
const AREA_TYPES = new Set(["zone", "geofence"]);
const RANGES: [string, string][] = [
  ["7d", t("Last 7 days")],
  ["30d", t("Last 30 days")],
  ["90d", t("Last 90 days")],
  ["1y", t("Last year")],
];

/**
 * The question form of the grazing page (plan, section 9.4): the herd, the areas, the
 * period, what to compare with (nothing, the period before, the seasons, another herd), the
 * weighting, and the method's options folded away. The estimate line names the areas the
 * run cannot use before Run is pressed.
 */
export function GrazingForm({
  projectId,
  state,
  onChange,
  onRun,
  editing = null,
}: {
  projectId: string;
  state: FormState;
  onChange: (patch: Partial<FormState>) => void;
  /** The new run, and whether it replaces the run being edited. */
  onRun: (run: AnalysisRun, replaced: boolean) => void;
  /** Set when an existing run is being changed: its name and sharing carry over on
   * "Run and replace". */
  editing?: { name: string | null; shared: boolean } | null;
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
  const features = useQuery({
    queryKey: queryKeys.features(projectId),
    queryFn: () =>
      api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, {
        query: { limit: 500 },
      }),
  });
  const items = entities.data?.items ?? [];
  useResolveSubjects(state, entities.data?.items, MAX_ANIMALS, onChange);
  // the subjects sent: the ones picked by name and the members of the chosen groups
  const subjects = withGroupMembers(
    state.entities,
    items,
    groups.data,
    state.groups,
    MAX_ANIMALS,
  );
  const usedTypes = new Set(items.map((e) => e.entity_type_id));
  const typeOptions = (types.data?.items ?? []).filter((x) =>
    usedTypes.has(x.id),
  );
  const areas = (features.data?.items ?? []).filter((f) =>
    AREA_TYPES.has(f.feature_type),
  );
  const units = areas.filter(isManagementUnit);
  const herdB = membersOf(
    entities.data?.items,
    groups.data,
    state.compare === "herd" ? state.grazing.herd_b : null,
    MAX_ANIMALS,
  );
  const parameters = grazingParameters({ ...state, entities: subjects }, herdB);
  const estimate = useQuery({
    queryKey: queryKeys.analysisEstimate(projectId, parameters ?? {}),
    queryFn: () =>
      api.get<AnalysisEstimate>(
        `/api/v1/projects/${projectId}/analyses/estimate`,
        {
          query: { module: "grazing", parameters: JSON.stringify(parameters) },
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
        { body: { module: "grazing", parameters } },
      );
      if (replace && editing && (editing.name || editing.shared))
        return api.patch<AnalysisRun>(
          `/api/v1/projects/${projectId}/analyses/${created.id}`,
          { body: { name: editing.name, shared: editing.shared } },
        );
      return created;
    },
    invalidate: [
      queryKeys.analyses(projectId, { module: "grazing", recent: true }),
    ],
    success: t("Analysis queued"),
    onSuccess: (r, replace) => onRun(r, replace),
  });
  const addAll = (ids: string[]) =>
    onChange({
      entities: [...new Set([...state.entities, ...ids])].slice(0, MAX_ANIMALS),
    });
  const grazing = (patch: Partial<GrazingOptions>) =>
    onChange({ grazing: { ...state.grazing, ...patch } });
  const e = estimate.data;
  const mayRun = can("analysis:run");
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label className="text-xs">{t("Herd")}</Label>
          <MultiSelect
            options={items.map((x) => ({ value: x.id, label: x.name }))}
            value={state.entities}
            onChange={(v) => onChange({ entities: v })}
            placeholder={t("Choose animals")}
            label={t("animals")}
            className="h-8 w-48"
            maxSelected={MAX_ANIMALS}
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
              onChange={(v) => onChange({ groups: v })}
              placeholder={t("Add groups")}
              label={t("groups")}
              className="h-8 w-40"
            />
          </div>
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
          <Label className="text-xs">{t("Areas")}</Label>
          <MultiSelect
            options={areas.map((f) => ({
              value: f.id,
              label: f.name,
              hint: f.feature_type,
            }))}
            value={state.grazing.areas}
            onChange={(v) => grazing({ areas: v })}
            placeholder={t("Choose zones")}
            label={t("areas")}
            className="h-8 w-48"
            maxSelected={MAX_AREAS}
          />
        </div>
        {units.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() =>
              grazing({ areas: units.map((f) => f.id).slice(0, MAX_AREAS) })
            }
          >
            {t("All management units")}
          </Button>
        )}
        {areas.length === 0 && features.data && (
          <span className="text-xs text-muted-foreground">
            {t("No zones yet.")}{" "}
            <Link
              className="underline"
              to={`/projects/${projectId}/admin/features`}
            >
              {t("Draw one on the map")}
            </Link>
          </span>
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
              onChange({
                compare: v === "none" ? null : v,
                grazing: { ...state.grazing, seasons: v === "seasons" },
              })
            }
          >
            <SelectTrigger className="h-8 w-44" aria-label={t("Compare with")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t("Nothing")}</SelectItem>
              <SelectItem value="previous">{t("The period before")}</SelectItem>
              <SelectItem value="seasons">{t("The seasons")}</SelectItem>
              {(groups.data?.length ?? 0) > 0 && (
                <SelectItem value="herd">{t("Another herd")}</SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>
        {state.compare === "herd" && (
          <Select
            value={state.grazing.herd_b ?? "none"}
            onValueChange={(id) =>
              grazing({ herd_b: id === "none" ? null : id })
            }
          >
            <SelectTrigger className="h-8 w-40" aria-label={t("Second herd")}>
              <SelectValue placeholder={t("Second herd")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>
                {t("Second herd")}
              </SelectItem>
              {(groups.data ?? []).map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <div className="space-y-1">
          <Label className="text-xs">{t("Weighting")}</Label>
          <Select
            value={state.grazing.weighting}
            onValueChange={(v) =>
              grazing({ weighting: v as GrazingOptions["weighting"] })
            }
          >
            <SelectTrigger className="h-8 w-44" aria-label={t("Weighting")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="equal">
                {t("Each animal counts one")}
              </SelectItem>
              <SelectItem value="attribute">{t("By an attribute")}</SelectItem>
              <SelectItem value="metabolic">
                {t("Metabolic (mass to the 0.75)")}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        {state.grazing.weighting !== "equal" && (
          <Input
            aria-label={t("Attribute key")}
            placeholder={
              state.grazing.weighting === "metabolic"
                ? "body_mass_kg"
                : "livestock_unit"
            }
            className="h-8 w-40"
            value={state.grazing.weight_key ?? ""}
            onChange={(ev) => grazing({ weight_key: ev.target.value || null })}
          />
        )}
        {mayRun && !editing && (
          <Button
            type="button"
            size="sm"
            className="h-8"
            disabled={!parameters || run.isPending || (e ? !e.ok : false)}
            onClick={() => run.mutate(false)}
          >
            <Play className="size-4" /> {t("Run")}
          </Button>
        )}
        {mayRun && editing && (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8"
              disabled={!parameters || run.isPending || (e ? !e.ok : false)}
              onClick={() => run.mutate(false)}
            >
              {t("Run as new")}
            </Button>
            <Button
              type="button"
              size="sm"
              className="h-8"
              disabled={!parameters || run.isPending || (e ? !e.ok : false)}
              onClick={() => run.mutate(true)}
            >
              <Play className="size-4" /> {t("Run and replace")}
            </Button>
          </>
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
              "gap {{gap}} h · new visit after {{absence}} h away · cell {{cell}} m · rest under {{rest}} animal-hours",
              {
                gap: state.method.gap,
                absence: state.grazing.absence,
                cell: state.method.cell,
                rest: state.grazing.rest,
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
            onChange={(v) => onChange({ method: { ...state.method, gap: v } })}
          />
          <NumberField
            label={t("New visit after (hours away)")}
            value={state.grazing.absence}
            min={1}
            max={168}
            step={0.5}
            onChange={(v) => grazing({ absence: v })}
          />
          <NumberField
            label={t("Grid cell (m)")}
            value={state.method.cell}
            min={10}
            max={5000}
            step={1}
            onChange={(v) => onChange({ method: { ...state.method, cell: v } })}
          />
          <NumberField
            label={t("Rest day at or below (animal-hours)")}
            value={state.grazing.rest}
            min={0}
            max={24}
            step={0.5}
            onChange={(v) => grazing({ rest: v })}
          />
          <NumberField
            label={t("Maximum plausible speed (m/s)")}
            value={state.method.speed_max}
            min={0.5}
            max={100}
            step={0.5}
            onChange={(v) =>
              onChange({ method: { ...state.method, speed_max: v } })
            }
          />
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={state.grazing.seasons}
              onCheckedChange={(on) => grazing({ seasons: on })}
              aria-label={t("Seasons")}
            />
            {t("Rows per season")}
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() =>
              onChange({
                method: { ...DEFAULT_METHOD, speed_max: 5 },
                grazing: {
                  ...state.grazing,
                  absence: DEFAULT_GRAZING.absence,
                  rest: 0,
                },
              })
            }
          >
            {t("Defaults")}
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {!parameters
          ? t("Choose at least one animal, one area and a period.")
          : !mayRun
            ? t("Your role can read results but not start a run.")
            : e
              ? e.ok
                ? t(
                    "{{subjects}} animals, {{areas}} areas, {{days}} days, about {{fixes}} fixes.",
                    {
                      subjects: e.subjects,
                      areas: state.grazing.areas.length,
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
