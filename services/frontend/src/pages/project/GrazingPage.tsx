import { useTranslation } from "react-i18next";
import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import type { AnalysisRun } from "@/api/types";
import { AreaCards } from "@/components/analysis/AreaCards";
import { GrazingForm } from "@/components/analysis/GrazingForm";
import { RestStrip } from "@/components/analysis/RestStrip";
import { ResultMap } from "@/components/analysis/ResultMap";
import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useIsPhone } from "@/hooks/useMediaQuery";
import {
  type FormState,
  formStateOfRun,
  readFormState,
  writeFormState,
} from "@/lib/analyses";

/** Grazing and rewilding (docs/ANALYTICS_PHASE1_PLAN.md, section 9): the herd, the areas
 * and the period at the top, the runs of the module, and the selected run's result with its
 * area cards, the map coloured by pressure, the timeline, the use-per-hectare bars, the rest
 * calendar and the tables. */
export function GrazingPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const phone = useIsPhone();
  const [formOpen, setFormOpen] = useState(false);
  const state = readFormState(params);
  const update = (patch: Partial<FormState>) =>
    setParams(writeFormState({ ...state, ...patch }), { replace: true });
  // opening a run loads its settings into the form; Run then makes a new run from the form
  const select = (run: AnalysisRun) =>
    update({ ...formStateOfRun(run, state), run: run.id });
  const started = (run: AnalysisRun) => {
    setFormOpen(false);
    update({ run: run.id });
  };
  const labels = GRAZING_LABELS(t);
  const form = (
    <GrazingForm
      projectId={projectId}
      state={state}
      onChange={update}
      onRun={started}
    />
  );
  return (
    <>
      <PageHeader
        title={t("Grazing")}
        description={t(
          "How tracked grazing animals use the management areas over time",
        )}
        actions={
          phone ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setFormOpen(true)}
            >
              <SlidersHorizontal className="size-4" /> {t("Set up a run")}
            </Button>
          ) : undefined
        }
      />
      <Page>
        {phone ? (
          <Sheet open={formOpen} onOpenChange={setFormOpen}>
            <SheetContent
              side="bottom"
              className="max-h-[85vh] overflow-y-auto"
            >
              <SheetTitle>{t("Set up a run")}</SheetTitle>
              <div className="pt-3">{form}</div>
            </SheetContent>
          </Sheet>
        ) : (
          <div className="rounded-md border bg-card p-3">{form}</div>
        )}
        <div className="space-y-4">
          <div className="space-y-2">
            <h2 className="text-sm font-medium">{t("Runs")}</h2>
            <RunList
              projectId={projectId}
              module="grazing"
              selected={state.run}
              onSelect={select}
            />
          </div>
          <div className="min-w-0">
            {state.run ? (
              <RunView
                projectId={projectId}
                runId={state.run}
                labels={labels}
                onEdit={(r) => {
                  select(r);
                  if (phone) setFormOpen(true);
                  else
                    document
                      .querySelector("main")
                      ?.scrollTo({ top: 0, behavior: "smooth" });
                }}
                render={{
                  summary: (document) => (
                    <AreaCards document={document} labels={labels} />
                  ),
                  map: (document, run, colors) => (
                    <ResultMap
                      projectId={projectId}
                      runId={run.id}
                      document={document}
                      labels={labels}
                      colors={colors}
                      tracksOn={false}
                    />
                  ),
                  after: (document, run) => (
                    <>
                      <RestStrip
                        document={document}
                        restThreshold={Number(
                          (run.parameters as { rest_threshold_hours?: number })
                            .rest_threshold_hours ?? 0,
                        )}
                      />
                      <Limitations />
                    </>
                  ),
                }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("Pick a run, or set one up and run it.")}
              </p>
            )}
          </div>
        </div>
      </Page>
    </>
  );
}

/** What the figures cannot say (plan, section 9.6), folded under the results. */
function Limitations() {
  const { t } = useTranslation();
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        {t("What these figures can and cannot say")}
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
        <li>
          {t(
            "Time in an area is a proxy for potential grazing pressure, not measured feeding; the tables say use, not grazing.",
          )}
        </li>
        <li>
          {t(
            "Only collared animals count; the herd is not extrapolated unless a weighting is chosen, and then the document names it.",
          )}
        </li>
        <li>
          {t(
            "Fix sampling and gaps bias the hours; the missing fix share and the gaps are in the warnings next to the totals.",
          )}
        </li>
        <li>
          {t(
            "Overlapping areas double-count by design; the overlap is listed.",
          )}
        </li>
        <li>
          {t(
            "Areas are fixed polygons without validity in time; an area that changed during the period must be two features.",
          )}
        </li>
      </ul>
    </details>
  );
}

/** The human names of the grazing result's keys; every header says use, not grazing. */
export const GRAZING_LABELS = (
  t: (k: string) => string,
): Record<string, string> => ({
  area: t("Area"),
  period: t("Period"),
  herd: t("Herd"),
  animal: t("Animal"),
  metric: t("Figure"),
  main: t("This period"),
  comparison: t("Before"),
  change_percent: t("Change (%)"),
  area_a: t("Area"),
  area_b: t("Overlaps with"),
  hectares: t("Hectares"),
  animal_hours: t("Animal-hours"),
  animal_days: t("Animal-days"),
  animal_hours_per_ha: t("Use (animal-hours per ha)"),
  animal_days_per_ha: t("Use (animal-days per ha)"),
  weighted_animal_days_per_ha: t("Weighted use (per ha)"),
  relative_pressure: t("Relative pressure"),
  pressure_rank: t("Rank"),
  share_of_herd_time: t("Share of herd time"),
  animals_used: t("Animals that used it"),
  visits: t("Visits"),
  mean_visit_hours: t("Mean visit (hours)"),
  use_days: t("Use days"),
  rest_days: t("Rest days"),
  longest_rest_days: t("Longest rest (days)"),
  last_use: t("Last use"),
  hours_since_last_use: t("Hours since last use"),
  hotspot_count: t("Hotspots"),
  hours: t("Hours"),
  weighted_hours: t("Weighted hours"),
  first_use: t("First use"),
  days_used: t("Days used"),
  areas: t("Areas"),
  animals: t("Animals"),
  overlaps: t("Overlaps"),
  changes: t("Change against the period before"),
  timeline: t("Daily animal-hours"),
  pressure: t("Use per hectare"),
  summary: t("Summary"),
});
