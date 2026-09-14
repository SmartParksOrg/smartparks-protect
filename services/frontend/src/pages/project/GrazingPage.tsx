import { useTranslation } from "react-i18next";
import { ArrowLeft, Plus } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import type { AnalysisRun } from "@/api/types";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/api/queryKeys";
import { AreaCards } from "@/components/analysis/AreaCards";
import { RestStrip } from "@/components/analysis/RestStrip";
import { ResultMap } from "@/components/analysis/ResultMap";
import { RunDialog } from "@/components/analysis/RunDialog";
import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/hooks/useProjects";
import {
  type FormState,
  hasFormInput,
  readFormState,
  writeFormState,
} from "@/lib/analyses";

/** Grazing and rewilding (docs/ANALYTICS_PHASE1_PLAN.md, section 9): the runs of the module
 * as a table, "New analysis" opening the dialog with the form, and an opened run with its
 * area cards, the map coloured by use, the timeline, the bars, the rest calendar and the
 * tables; "Edit and run again" opens the same dialog with the run's settings. */
export function GrazingPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { can } = usePermissions(projectId);
  const client = useQueryClient();
  const state = readFormState(params);
  // a deep link ("Analyse grazing" on a group, "Grazing in this area" on a zone) opens the
  // dialog filled in
  const [dialog, setDialog] = useState<{
    open: boolean;
    editing: AnalysisRun | null;
    initial: FormState;
  }>(() => ({ open: hasFormInput(state), editing: null, initial: state }));
  const show = (run: string | null) =>
    setParams(
      writeFormState({ ...readFormState(new URLSearchParams()), run }),
      {
        replace: true,
      },
    );
  const labels = GRAZING_LABELS(t);
  const created = (_run: AnalysisRun, replaced: AnalysisRun | null) => {
    setDialog((d) => ({ ...d, open: false, editing: null }));
    if (replaced)
      void api
        .delete(`/api/v1/projects/${projectId}/analyses/${replaced.id}`)
        .then(() =>
          client.invalidateQueries({
            queryKey: queryKeys.analyses(projectId, {
              module: "grazing",
              recent: true,
            }),
          }),
        );
    show(null);
  };
  return (
    <>
      <PageHeader
        title={t("Grazing")}
        description={t(
          "How tracked grazing animals use the management areas over time",
        )}
        actions={
          can("analysis:run") ? (
            <Button
              type="button"
              size="sm"
              onClick={() =>
                setDialog({
                  open: true,
                  editing: null,
                  initial: readFormState(new URLSearchParams()),
                })
              }
            >
              <Plus className="size-4" /> {t("New analysis")}
            </Button>
          ) : undefined
        }
      />
      <Page>
        {state.run ? (
          <div className="space-y-4">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="-ml-2"
              onClick={() => show(null)}
            >
              <ArrowLeft className="size-4" /> {t("All analyses")}
            </Button>
            <RunView
              projectId={projectId}
              runId={state.run}
              labels={labels}
              onEdit={(r) =>
                setDialog({ open: true, editing: r, initial: state })
              }
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
          </div>
        ) : (
          <RunList
            projectId={projectId}
            module="grazing"
            selected={null}
            onSelect={(run) => show(run.id)}
          />
        )}
      </Page>
      <RunDialog
        projectId={projectId}
        module="grazing"
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        initial={dialog.initial}
        editing={dialog.editing}
        onCreated={created}
      />
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
