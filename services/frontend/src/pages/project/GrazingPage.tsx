import { useTranslation } from "react-i18next";
import { ArrowLeft, Plus } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import type { AnalysisRun } from "@/api/types";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/api/queryKeys";
import { RunDialog } from "@/components/analysis/RunDialog";
import { RunList } from "@/components/analysis/RunList";
import { RunView } from "@/components/analysis/RunView";
import { grazingPresentation } from "@/components/analysis/presentations";
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
  const presentation = grazingPresentation(t, projectId);
  const labels = presentation.labels;
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
              render={presentation.render}
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
