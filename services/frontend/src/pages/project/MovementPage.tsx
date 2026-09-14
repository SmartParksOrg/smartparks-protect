import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router";

import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { readFormState, writeFormState } from "@/lib/analyses";

/** Movement and space use (docs/ANALYTICS_PHASE1_PLAN.md, section 8): the question form, the
 * runs of the module and the selected run's result. The form and the map arrive with the
 * movement module (tasks M1 to M3); until then the page lists and shows runs. */
export function MovementPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const state = readFormState(params);
  const select = (run: string | null) =>
    setParams(writeFormState({ ...state, run }), { replace: true });
  return (
    <>
      <PageHeader
        title={t("Movement")}
        description={t(
          "Distance, speed, space use and home range of tracked animals",
        )}
      />
      <Page>
        <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="space-y-2">
            <h2 className="text-sm font-medium">{t("Runs")}</h2>
            <RunList
              projectId={projectId}
              module="movement"
              selected={state.run}
              onSelect={select}
            />
          </div>
          <div>
            {state.run ? (
              <RunView
                projectId={projectId}
                runId={state.run}
                labels={MOVEMENT_LABELS(t)}
                onRerun={(r) => select(r.id)}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("Pick a run, or start one.")}
              </p>
            )}
          </div>
        </div>
      </Page>
    </>
  );
}

/** The human names of the movement result's keys. */
export const MOVEMENT_LABELS = (
  t: (k: string) => string,
): Record<string, string> => ({
  distance_km: t("Distance (km)"),
  daily_distance: t("Daily distance"),
  speed_histogram: t("Speed"),
  hour_profile: t("Activity by hour"),
  turning: t("Turning angles"),
  nsd: t("Net squared displacement"),
  summary: t("Summary"),
  comparison: t("Comparison"),
});
