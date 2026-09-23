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
import { useGroups } from "@/hooks/useGroups";
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePermissions } from "@/hooks/useProjects";
import {
  type CardiacOptions,
  cardiacParameters,
  eventInside,
  type FormState,
  withGroupMembers,
} from "@/lib/analyses";
import { inputValue } from "@/lib/records";

const MAX_SUBJECTS = 25;
const RANGES: [string, string][] = [
  ["7d", t("Last 7 days")],
  ["30d", t("Last 30 days")],
  ["90d", t("Last 90 days")],
  ["1y", t("Last year")],
];
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

/**
 * The question form of the cardiac page: which animals, which period, and under "Method" how
 * a resting heart rate is read. The two method fields are there because the answer depends on
 * them: "resting" is the low tenth of the quiet hours, and the quiet hours of a rhino are not
 * those of a bat. A reader who never opens the method still gets an answer with the numbers
 * printed beside it in the result.
 */
export function CardiacForm({
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
  // an event outside the period is refused by the module (decision D289), so it is not asked
  const outside = !eventInside(state);
  const parameters = outside
    ? null
    : cardiacParameters({ ...state, entities: subjects });
  const estimate = useQuery({
    queryKey: queryKeys.analysisEstimate(projectId, parameters ?? {}),
    queryFn: () =>
      api.get<AnalysisEstimate>(
        `/api/v1/projects/${projectId}/analyses/estimate`,
        {
          query: {
            module: "cardiac",
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
        { body: { module: "cardiac", parameters } },
      );
      if (replace && editing && (editing.name || editing.shared))
        return api.patch<AnalysisRun>(
          `/api/v1/projects/${projectId}/analyses/${created.id}`,
          { body: { name: editing.name, shared: editing.shared } },
        );
      return created;
    },
    invalidate: [
      queryKeys.analyses(projectId, { module: "cardiac", recent: true }),
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
  const cardiac = (patch: Partial<CardiacOptions>) =>
    onChange({ cardiac: { ...state.cardiac, ...patch } });
  const c = state.cardiac;
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
        <div className="space-y-1">
          <Label className="text-xs">
            {t("Event, to compare before and after")}
          </Label>
          <Input
            type="datetime-local"
            aria-label={t("Event, to compare before and after")}
            className="h-8 w-48"
            value={inputValue(c.event)}
            onChange={(ev) => cardiac({ event: ev.target.value || null })}
          />
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
              {t("Run and replace")}
            </Button>
          </>
        )}
      </div>

      <button
        type="button"
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setMethodOpen((open) => !open)}
        aria-expanded={methodOpen}
      >
        {methodOpen ? (
          <ChevronDown className="size-3" />
        ) : (
          <ChevronRight className="size-3" />
        )}
        {t("Method")}
      </button>
      {methodOpen && (
        <div className="flex flex-wrap items-end gap-3 rounded-md border p-3">
          <div className="space-y-1">
            <Label className="text-xs">{t("Quiet hours from")}</Label>
            <Select
              value={String(c.quietFrom)}
              onValueChange={(v) => cardiac({ quietFrom: Number(v) })}
            >
              <SelectTrigger
                className="h-8 w-24"
                aria-label={t("Quiet hours from")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HOURS.map((hour) => (
                  <SelectItem key={hour} value={String(hour)}>
                    {`${String(hour).padStart(2, "0")}:00`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("Quiet hours to")}</Label>
            <Select
              value={String(c.quietTo)}
              onValueChange={(v) => cardiac({ quietTo: Number(v) })}
            >
              <SelectTrigger
                className="h-8 w-24"
                aria-label={t("Quiet hours to")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HOURS.map((hour) => (
                  <SelectItem key={hour} value={String(hour)}>
                    {`${String(hour).padStart(2, "0")}:59`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("Resting quantile")}</Label>
            <Input
              type="number"
              className="h-8 w-28"
              min={0.01}
              max={0.5}
              step={0.01}
              value={c.quantile}
              onChange={(ev) => {
                const n = Number(ev.target.value);
                if (Number.isFinite(n) && n >= 0.01 && n <= 0.5)
                  cardiac({ quantile: n });
              }}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("Restless above (activity)")}</Label>
            <Input
              type="number"
              className="h-8 w-28"
              min={1}
              max={254}
              step={1}
              value={c.restless}
              onChange={(ev) => {
                const n = Number(ev.target.value);
                if (Number.isInteger(n) && n >= 1 && n <= 254)
                  cardiac({ restless: n });
              }}
            />
          </div>
          <p className="w-full text-xs text-muted-foreground">
            {t(
              "The resting heart rate is this quantile of the readings taken in the quiet hours, on the project's clock. The quiet hours may wrap past midnight.",
            )}{" "}
            {t(
              "A night's restless minutes count the readings whose activity, on the implant's scale of 0 to 255, is above this value.",
            )}
          </p>
        </div>
      )}

      <p className="text-xs text-muted-foreground" aria-live="polite">
        {outside
          ? t("The event must fall inside the period.")
          : !parameters
            ? t("Choose at least one subject and a period.")
            : !mayRun
              ? t("Your role can read results but not start a run.")
              : e
                ? e.ok
                  ? t("{{subjects}} subjects, {{days}} days.", {
                      subjects: e.subjects,
                      days: e.days,
                    })
                  : e.reasons?.join(" ") || t("The run is too large.")
                : t("Estimating…")}
      </p>
    </div>
  );
}
