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
import { cardiacPresentation } from "@/components/analysis/presentations";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/hooks/useProjects";
import {
  type FormState,
  hasFormInput,
  readFormState,
  writeFormState,
} from "@/lib/analyses";

const MODULE = "cardiac";

/** Cardiac monitoring (docs/analytics/cardiac.md): the runs of the module as a table, "New
 * analysis" opening the dialog with the form, and an opened run with a card per animal, the
 * daily rhythm and what the collar managed to hear. */
export function CardiacPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { can } = usePermissions(projectId);
  const client = useQueryClient();
  const state = readFormState(params);
  const [dialog, setDialog] = useState<{
    open: boolean;
    editing: AnalysisRun | null;
    initial: FormState;
  }>(() => ({ open: hasFormInput(state), editing: null, initial: state }));
  const show = (run: string | null) =>
    setParams(
      writeFormState({ ...readFormState(new URLSearchParams()), run }),
      { replace: true },
    );
  const presentation = cardiacPresentation(t);
  const created = (_run: AnalysisRun, replaced: AnalysisRun | null) => {
    setDialog((d) => ({ ...d, open: false, editing: null }));
    if (replaced)
      void api
        .delete(`/api/v1/projects/${projectId}/analyses/${replaced.id}`)
        .then(() =>
          client.invalidateQueries({
            queryKey: queryKeys.analyses(projectId, {
              module: MODULE,
              recent: true,
            }),
          }),
        );
    show(null);
  };
  return (
    <>
      <PageHeader
        title={t("Cardiac monitoring")}
        description={t(
          "Heart rate, variability and body temperature from a cardiac tag the animal wears, heard over Bluetooth by its device",
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
              labels={presentation.labels}
              onEdit={(r) =>
                setDialog({ open: true, editing: r, initial: state })
              }
              render={presentation.render}
            />
          </div>
        ) : (
          <RunList
            projectId={projectId}
            module={MODULE}
            selected={null}
            onSelect={(run) => show(run.id)}
          />
        )}
      </Page>
      <RunDialog
        projectId={projectId}
        module={MODULE}
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        initial={dialog.initial}
        editing={dialog.editing}
        onCreated={created}
      />
    </>
  );
}
