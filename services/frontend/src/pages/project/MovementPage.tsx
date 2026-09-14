import { useTranslation } from "react-i18next";
import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import type { AnalysisRun } from "@/api/types";
import { MovementForm } from "@/components/analysis/MovementForm";
import { ResultMap } from "@/components/analysis/ResultMap";
import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { SubjectCards } from "@/components/analysis/SubjectCards";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useIsPhone } from "@/hooks/useMediaQuery";
import { type FormState, readFormState, writeFormState } from "@/lib/analyses";

/** Movement and space use (docs/ANALYTICS_PHASE1_PLAN.md, section 8): the question form at
 * the top, the runs of the module, and the selected run's result with its cards, map,
 * charts and table. The form lives in the URL, so a link reproduces it; on a phone it folds
 * into a sheet. */
export function MovementPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const phone = useIsPhone();
  const [formOpen, setFormOpen] = useState(false);
  const state = readFormState(params);
  const update = (patch: Partial<FormState>) =>
    setParams(writeFormState({ ...state, ...patch }), { replace: true });
  const select = (run: string | null) => update({ run });
  const started = (run: AnalysisRun) => {
    setFormOpen(false);
    select(run.id);
  };
  const labels = MOVEMENT_LABELS(t);
  const form = (
    <MovementForm
      projectId={projectId}
      state={state}
      onChange={update}
      onRun={started}
    />
  );
  return (
    <>
      <PageHeader
        title={t("Movement")}
        description={t(
          "Distance, speed, space use and home range of tracked animals",
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
        <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="min-w-0 space-y-2">
            <h2 className="text-sm font-medium">{t("Runs")}</h2>
            <RunList
              projectId={projectId}
              module="movement"
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
                onRerun={(r) => select(r.id)}
                render={{
                  summary: (document) => (
                    <SubjectCards
                      document={document}
                      labels={labels}
                      metrics={CARD_METRICS}
                    />
                  ),
                  map: (document, run) => (
                    <ResultMap
                      projectId={projectId}
                      runId={run.id}
                      document={document}
                      labels={labels}
                    />
                  ),
                  after: () => <Limitations />,
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

/** The figures on a subject's card, with their unit. */
const CARD_METRICS: [string, string][] = [
  ["distance_km", "km"],
  ["daily_distance_km", "km/day"],
  ["median_speed_mps", "m/s"],
  ["stationary_share", "%"],
  ["mcp95_ha", "ha"],
  ["kde95_ha", "ha"],
  ["fixes", ""],
];

/** What the method cannot say (plan, section 8.10), folded under the results. */
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
            "Distance from fixes underestimates the path between them; a coarser sampling means a shorter apparent distance. The sampling interval stands next to the distance for that reason.",
          )}
        </li>
        <li>
          {t("Speed is the mean over a step, not an instantaneous speed.")}
        </li>
        <li>
          {t(
            "The KDE is an estimate of space use that depends on the bandwidth and the grid; its isopleths are unions of cells, not smooth contours.",
          )}
        </li>
        <li>{t("The MCP includes ground never visited between far fixes.")}</li>
        <li>
          {t(
            "Residence time on a regular grid depends on the cell size and is biased by irregular sampling.",
          )}
        </li>
        <li>
          {t(
            "Day and night follow the sun's elevation, not the animal's own rhythm or the cloud cover.",
          )}
        </li>
        <li>
          {t("The results describe the collared animals, not the population.")}
        </li>
      </ul>
    </details>
  );
}

/** The human names of the movement result's keys. */
export const MOVEMENT_LABELS = (
  t: (k: string) => string,
): Record<string, string> => ({
  subject: t("Subject"),
  period: t("Period"),
  main: t("This period"),
  comparison: t("Before"),
  mean: t("Mean"),
  sd: t("Standard deviation"),
  fixes: t("Fixes"),
  days_with_data: t("Days with data"),
  median_interval_min: t("Sampling interval (min)"),
  distance_km: t("Distance (km)"),
  daily_distance_km: t("Daily distance (km)"),
  displacement_km: t("Displacement (km)"),
  max_displacement_km: t("Farthest from the start (km)"),
  mean_speed_mps: t("Mean speed (m/s)"),
  median_speed_mps: t("Median speed (m/s)"),
  p95_speed_mps: t("95th percentile speed (m/s)"),
  stationary_share: t("Stationary share"),
  moving_share: t("Moving share"),
  stationary_periods: t("Stationary periods"),
  day_distance_km: t("Distance by day (km)"),
  night_distance_km: t("Distance by night (km)"),
  mcp95_ha: t("MCP 95% (ha)"),
  kde50_ha: t("KDE 50% (ha)"),
  kde95_ha: t("KDE 95% (ha)"),
  kde_bandwidth_m: t("KDE bandwidth (m)"),
  hotspot_count: t("Hotspots"),
  cluster_count: t("Clusters"),
  missing_share: t("Missing fixes share"),
  excluded_fixes: t("Excluded fixes"),
  daily_distance: t("Daily distance"),
  speed_histogram: t("Speed"),
  hour_profile: t("Activity by hour"),
  turning: t("Turning angles"),
  nsd: t("Net squared displacement"),
  day_night: t("Day and night"),
  summary: t("Summary"),
});
