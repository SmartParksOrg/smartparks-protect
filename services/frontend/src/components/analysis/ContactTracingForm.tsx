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
  type ContactOptions,
  contactTracingParameters,
  DEFAULT_CONTACT,
  type FormState,
  withGroupMembers,
} from "@/lib/analyses";
import { inputValue } from "@/lib/records";

/** Every pair is compared with every other, so the work grows with the square: forty subjects
 * is 780 pairs. The server holds the same bound. */
const MAX_SUBJECTS = 40;
const RANGES: [string, string][] = [
  ["7d", t("Last 7 days")],
  ["30d", t("Last 30 days")],
  ["90d", t("Last 90 days")],
  ["1y", t("Last year")],
];

/**
 * The question form of the contact tracing page: which subjects, which period, and under
 * "Method" the two kinds of evidence with the limits each is judged by. The defaults say what
 * they mean — a hundred metres is beyond GNSS error but within sight, ten minutes is tighter
 * than the usual fix interval — so the form is answerable without opening the method at all.
 */
export function ContactTracingForm({
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
  const items = entities.data?.items ?? [];
  useResolveSubjects(state, entities.data?.items, MAX_SUBJECTS, onChange);
  const subjects = withGroupMembers(
    state.entities,
    items,
    groups.data,
    state.groups,
    MAX_SUBJECTS,
  );
  const usedTypes = new Set(items.map((e) => e.entity_type_id));
  const typeOptions = (types.data?.items ?? []).filter((x) =>
    usedTypes.has(x.id),
  );
  const parameters = contactTracingParameters({ ...state, entities: subjects });
  const estimate = useQuery({
    queryKey: queryKeys.analysisEstimate(projectId, parameters ?? {}),
    queryFn: () =>
      api.get<AnalysisEstimate>(
        `/api/v1/projects/${projectId}/analyses/estimate`,
        {
          query: {
            module: "contact_tracing",
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
        { body: { module: "contact_tracing", parameters } },
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
        module: "contact_tracing",
        recent: true,
      }),
    ],
    success: t("Analysis queued"),
    onSuccess: (r, replace) => onRun(r, replace),
  });
  const addAll = (ids: string[]) =>
    onChange({
      entities: [...new Set([...state.entities, ...ids])].slice(
        0,
        MAX_SUBJECTS,
      ),
    });
  const contact = (patch: Partial<ContactOptions>) =>
    onChange({ contact: { ...state.contact, ...patch } });
  const c = state.contact;
  const e = estimate.data;
  const mayRun = can("analysis:run");
  const neither = !c.bluetooth && !c.proximity;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label className="text-xs">{t("Subjects")}</Label>
          <MultiSelect
            options={items.map((x) => ({ value: x.id, label: x.name }))}
            value={state.entities}
            onChange={(v) => onChange({ entities: v })}
            placeholder={t("Choose subjects")}
            label={t("subjects")}
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
            {t("{{evidence}} · within {{distance}} m and {{window}} min", {
              evidence: neither
                ? t("no evidence")
                : [
                    c.bluetooth ? t("Bluetooth") : null,
                    c.proximity ? t("proximity") : null,
                  ]
                    .filter(Boolean)
                    .join(" + "),
              distance: c.distance,
              window: Math.round(c.window / 60),
            })}
          </span>
        )}
      </button>
      {methodOpen && (
        <div className="flex flex-wrap items-end gap-3 rounded-md border bg-muted/30 p-3">
          <div className="space-y-1">
            <Label className="text-xs">{t("Bluetooth sightings")}</Label>
            <div className="flex h-8 items-center">
              <Switch
                checked={c.bluetooth}
                onCheckedChange={(v) => contact({ bluetooth: v })}
                aria-label={t("Bluetooth sightings")}
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("Position proximity")}</Label>
            <div className="flex h-8 items-center">
              <Switch
                checked={c.proximity}
                onCheckedChange={(v) => contact({ proximity: v })}
                aria-label={t("Position proximity")}
              />
            </div>
          </div>
          <NumberField
            label={t("Distance (m)")}
            value={c.distance}
            min={5}
            max={10000}
            step={5}
            onChange={(v) => contact({ distance: v })}
          />
          <NumberField
            label={t("Time window (s)")}
            value={c.window}
            min={30}
            max={86400}
            step={30}
            onChange={(v) => contact({ window: v })}
          />
          <NumberField
            label={t("Shortest contact (s)")}
            value={c.shortest}
            min={0}
            max={86400}
            step={30}
            onChange={(v) => contact({ shortest: v })}
          />
          <div className="space-y-1">
            <Label className="text-xs">{t("Signal floor (dBm)")}</Label>
            <Input
              type="number"
              className="h-8 w-32"
              min={-128}
              max={0}
              step={1}
              placeholder={t("none")}
              value={c.rssi ?? ""}
              onChange={(ev) =>
                contact({
                  rssi: ev.target.value === "" ? null : Number(ev.target.value),
                })
              }
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-8"
            onClick={() => onChange({ contact: DEFAULT_CONTACT })}
          >
            {t("Defaults")}
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {neither
          ? t("Switch on Bluetooth sightings or position proximity, or both.")
          : !parameters
            ? t("Choose at least one subject and a period.")
            : !mayRun
              ? t("Your role can read results but not start a run.")
              : e
                ? e.ok
                  ? t(
                      "{{subjects}} subjects, {{pairs}} pairs, {{days}} days, about {{fixes}} fixes.",
                      {
                        subjects: e.subjects,
                        pairs: (e.subjects * (e.subjects - 1)) / 2,
                        days: e.days,
                        fixes: e.fixes.toLocaleString(),
                      },
                    )
                  : e.reasons?.join(" ") || t("The run is too large.")
                : t("Estimating\u2026")}
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
