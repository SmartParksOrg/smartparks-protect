import { t } from "@/lib/i18nMark";
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
  LayerChoiceRead,
  Page as PageType,
} from "@/api/types";
import { DateRangeField } from "@/components/analysis/DateRangeField";
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

/** The tracked types whose entities, with their sub-types, are not animals. */
const NOT_ANIMAL_TYPE_KEYS = new Set(["vehicle", "person"]);
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePermissions } from "@/hooks/useProjects";
import {
  DEFAULT_HABITAT,
  type FormState,
  type HabitatOptions,
  habitatParameters,
  withGroupMembers,
} from "@/lib/analyses";

/** The server holds the same bound (`MAX_SUBJECTS_HABITAT`). */
const MAX_SUBJECTS = 40;
const MAX_LAYERS = 8;
const RANGES: [string, string][] = [
  ["1d", t("Last 24 hours")],
  ["7d", t("Last 7 days")],
  ["30d", t("Last 30 days")],
  ["90d", t("Last 90 days")],
  ["1y", t("Last year")],
];
const SOURCE_HEADINGS: Record<string, string> = {
  provider: t("From satellite data"),
  distance: t("Distance to the project's features"),
  project: t("Uploaded layers"),
};

/**
 * The question form of the habitat selection page (phase 41, decisions D315 and D316): which
 * animals, which period, which layers (what the project offers: the provider's, a distance
 * per feature type, the uploads) and, under "Method", hrHSA's settings: the quantile of each
 * animal's available area, the available points per used fix, the thinning, the buffer
 * around the areas, the validation and the stop rule. No comparison period: the module does
 * not offer one yet.
 */
export function HabitatForm({
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
  const layers = useQuery({
    queryKey: queryKeys.analysisLayers(projectId),
    queryFn: () =>
      api.get<LayerChoiceRead[]>(
        `/api/v1/projects/${projectId}/analysis-layers`,
      ),
  });
  // the animals: every tracked type but people and vehicles and their sub-types, the only
  // entities the module admits
  const allTypes = types.data?.items ?? [];
  const notAnimalIds = new Set(
    allTypes.filter((x) => NOT_ANIMAL_TYPE_KEYS.has(x.key)).map((x) => x.id),
  );
  const animalTypeIds = new Set(
    allTypes
      .filter(
        (x) =>
          x.group_key === "tracked" &&
          !notAnimalIds.has(x.id) &&
          (x.parent_id == null || !notAnimalIds.has(x.parent_id)),
      )
      .map((x) => x.id),
  );
  const items = (entities.data?.items ?? []).filter((e) =>
    animalTypeIds.has(e.entity_type_id),
  );
  useResolveSubjects(state, items, MAX_SUBJECTS, onChange);
  const subjects = withGroupMembers(
    state.entities,
    items,
    groups.data,
    state.groups,
    MAX_SUBJECTS,
  );
  const choices = layers.data ?? [];
  const chosen = choices.filter((c) => state.habitat.layers.includes(c.name));
  const parameters = habitatParameters({ ...state, entities: subjects });
  const estimate = useQuery({
    queryKey: queryKeys.analysisEstimate(projectId, parameters ?? {}),
    queryFn: () =>
      api.get<AnalysisEstimate>(
        `/api/v1/projects/${projectId}/analyses/estimate`,
        {
          query: {
            module: "habitat_selection",
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
        { body: { module: "habitat_selection", parameters } },
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
        module: "habitat_selection",
        recent: true,
      }),
    ],
    success: t("Analysis queued"),
    onSuccess: (r, replace) => onRun(r, replace),
  });
  const habitat = (patch: Partial<HabitatOptions>) =>
    onChange({ habitat: { ...state.habitat, ...patch } });
  const h = state.habitat;
  const e = estimate.data;
  const mayRun = can("analysis:run");
  const noLayers = layers.data !== undefined && choices.length === 0;
  const readyToRun =
    parameters !== null && !run.isPending && (e ? e.ok : false);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label className="text-xs">{t("Animals")}</Label>
          <MultiSelect
            options={items.map((x) => ({ value: x.id, label: x.name }))}
            value={state.entities}
            onChange={(val) => onChange({ entities: val })}
            placeholder={t("Choose animals")}
            label={t("animals")}
            className="h-8 w-48"
            maxSelected={MAX_SUBJECTS}
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
              onChange={(val) => onChange({ groups: val })}
              placeholder={t("Add groups")}
              label={t("groups")}
              className="h-8 w-40"
            />
          </div>
        )}
        <div className="space-y-1">
          <Label className="text-xs">{t("Layers")}</Label>
          <MultiSelect
            options={choices.map((c) => ({
              value: c.name,
              label: c.label,
              group: t(SOURCE_HEADINGS[c.source] ?? c.source),
            }))}
            value={h.layers}
            onChange={(val) =>
              habitat({
                layers: val,
                quadratic: h.quadratic.filter((n) => val.includes(n)),
              })
            }
            placeholder={t("Choose layers")}
            label={t("layers")}
            className="h-8 w-56"
            maxSelected={MAX_LAYERS}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">{t("Period")}</Label>
          <Select
            value={state.range}
            onValueChange={(val) => onChange({ range: val })}
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
          <DateRangeField
            from={state.from}
            to={state.to}
            onChange={onChange}
          />
        )}
        {mayRun && !editing && (
          <Button
            type="button"
            size="sm"
            className="h-8"
            disabled={!readyToRun}
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
              disabled={!readyToRun}
              onClick={() => run.mutate(false)}
            >
              {t("Run as new")}
            </Button>
            <Button
              type="button"
              size="sm"
              className="h-8"
              disabled={!readyToRun}
              onClick={() => run.mutate(true)}
            >
              <Play className="size-4" /> {t("Run and replace")}
            </Button>
          </>
        )}
      </div>
      {chosen.some((c) => c.kind === "continuous") && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <Label className="text-xs">{t("Also squared")}</Label>
            <MultiSelect
              options={chosen
                .filter((c) => c.kind === "continuous")
                .map((c) => ({ value: c.name, label: c.label }))}
              value={h.quadratic}
              onChange={(val) => habitat({ quadratic: val })}
              placeholder={t("None")}
              label={t("layers squared")}
              className="h-8 w-56"
            />
          </div>
          <p className="max-w-md text-xs text-muted-foreground">
            {t(
              "A squared layer lets the response peak: a distance that is good up to a point, a greenness that is best in the middle.",
            )}
          </p>
        </div>
      )}
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
              "available area at the {{quantile}} quantile · {{sampling}} available points per fix · {{thin}} · {{loio}}",
              {
                quantile: h.quantile,
                sampling: h.sampling,
                thin: h.thin
                  ? t("one fix per {{hours}} h", { hours: h.thin })
                  : t("every fix"),
                loio: h.loio
                  ? t("validated animal by animal")
                  : t("no validation"),
              },
            )}
          </span>
        )}
      </button>
      {methodOpen && (
        <div className="flex flex-wrap items-end gap-3 rounded-md border bg-muted/30 p-3">
          <NumberField
            label={t("Available area (MCP quantile)")}
            value={h.quantile}
            min={0.5}
            max={1}
            step={0.01}
            onChange={(val) => habitat({ quantile: val })}
          />
          <NumberField
            label={t("Available points per fix")}
            value={h.sampling}
            min={1}
            max={50}
            step={1}
            onChange={(val) => habitat({ sampling: val })}
          />
          <NumberField
            label={t("One fix per (hours, 0 for all)")}
            value={h.thin ?? 0}
            min={0}
            max={168}
            step={1}
            onChange={(val) => habitat({ thin: val > 0 ? val : null })}
          />
          <NumberField
            label={t("Buffer around the areas (m)")}
            value={h.buffer}
            min={0}
            max={20000}
            step={100}
            onChange={(val) => habitat({ buffer: val })}
          />
          <NumberField
            label={t("Stop radius (m, 0 off)")}
            value={h.stopRadius}
            min={0}
            max={500}
            step={1}
            onChange={(val) => habitat({ stopRadius: val })}
          />
          <label className="flex items-center gap-2 text-xs">
            <Switch
              checked={h.loio}
              onCheckedChange={(val) => habitat({ loio: val })}
              aria-label={t("Validate animal by animal")}
            />
            {t("Validate animal by animal")}
          </label>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-8"
            onClick={() =>
              onChange({
                habitat: { ...DEFAULT_HABITAT, layers: h.layers },
              })
            }
          >
            {t("Defaults")}
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {noLayers
          ? t(
              "This project has no layer yet: set up the environmental data provider under Server admin, draw or import features, or upload a GeoTIFF under Project admin, Features.",
            )
          : !parameters
            ? t("Choose at least one animal, one layer and a period.")
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
        className="h-8 w-36"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(ev) => {
          const n = Number(ev.target.value);
          if (Number.isFinite(n)) onChange(Math.min(max, Math.max(min, n)));
        }}
      />
    </div>
  );
}
