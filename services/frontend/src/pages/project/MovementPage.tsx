import { useTranslation } from "react-i18next";
import { ArrowLeft, Plus } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import type { AnalysisRun } from "@/api/types";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/api/queryKeys";
import { ResultMap } from "@/components/analysis/ResultMap";
import { RunDialog } from "@/components/analysis/RunDialog";
import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { SubjectCards } from "@/components/analysis/SubjectCards";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/hooks/useProjects";
import {
  type FormState,
  hasFormInput,
  readFormState,
  writeFormState,
} from "@/lib/analyses";

/** Movement and space use (docs/ANALYTICS_PHASE1_PLAN.md, section 8): the runs of the
 * module as a table, "New analysis" opening the dialog with the form, and an opened run with
 * its cards, map, charts and table; "Edit and run again" opens the same dialog with the run's
 * settings. */
export function MovementPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { can } = usePermissions(projectId);
  const client = useQueryClient();
  const state = readFormState(params);
  // a deep link ("Analyse …" on an entity, a group or a zone) opens the dialog filled in
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
  const labels = MOVEMENT_LABELS(t);
  const created = (_run: AnalysisRun, replaced: AnalysisRun | null) => {
    setDialog((d) => ({ ...d, open: false, editing: null }));
    if (replaced)
      void api
        .delete(`/api/v1/projects/${projectId}/analyses/${replaced.id}`)
        .then(() =>
          client.invalidateQueries({
            queryKey: queryKeys.analyses(projectId, {
              module: "movement",
              recent: true,
            }),
          }),
        );
    show(null);
  };
  return (
    <>
      <PageHeader
        title={t("Movement")}
        description={t(
          "Distance, speed, space use and home range of tracked animals",
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
                summary: (document, _run, colors) => (
                  <SubjectCards
                    document={document}
                    labels={labels}
                    metrics={CARD_METRICS}
                    colors={colors}
                  />
                ),
                map: (document, run, colors) => (
                  <ResultMap
                    projectId={projectId}
                    runId={run.id}
                    document={document}
                    labels={labels}
                    colors={colors}
                  />
                ),
                after: () => <Limitations />,
              }}
            />
          </div>
        ) : (
          <RunList
            projectId={projectId}
            module="movement"
            selected={null}
            onSelect={(run) => show(run.id)}
          />
        )}
      </Page>
      <RunDialog
        projectId={projectId}
        module="movement"
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        initial={dialog.initial}
        editing={dialog.editing}
        onCreated={created}
      />
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
