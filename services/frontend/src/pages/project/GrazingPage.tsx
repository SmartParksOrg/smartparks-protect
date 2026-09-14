import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router";

import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { readFormState, writeFormState } from "@/lib/analyses";

/** Grazing and rewilding (docs/ANALYTICS_PHASE1_PLAN.md, section 9): how tracked grazing
 * animals use the management areas over time. The form and the map arrive with the grazing
 * module (tasks G1 and G2); until then the page lists and shows runs. */
export function GrazingPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const state = readFormState(params);
  const select = (run: string | null) =>
    setParams(writeFormState({ ...state, run }), { replace: true });
  return (
    <>
      <PageHeader
        title={t("Grazing")}
        description={t(
          "How tracked grazing animals use the management areas over time",
        )}
      />
      <Page>
        <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="space-y-2">
            <h2 className="text-sm font-medium">{t("Runs")}</h2>
            <RunList
              projectId={projectId}
              module="grazing"
              selected={state.run}
              onSelect={select}
            />
          </div>
          <div>
            {state.run ? (
              <RunView
                projectId={projectId}
                runId={state.run}
                labels={GRAZING_LABELS(t)}
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

/** The human names of the grazing result's keys. */
export const GRAZING_LABELS = (
  t: (k: string) => string,
): Record<string, string> => ({
  areas: t("Areas"),
  timeline: t("Daily animal-hours"),
  pressure: t("Use per hectare"),
  summary: t("Summary"),
  comparison: t("Comparison"),
});
