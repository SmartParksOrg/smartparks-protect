import { useTranslation } from "react-i18next";
import { useState } from "react";

import type { AnalysisRun } from "@/api/types";
import { CardiacForm } from "@/components/analysis/CardiacForm";
import { ContactTracingForm } from "@/components/analysis/ContactTracingForm";
import { DevicePerformanceForm } from "@/components/analysis/DevicePerformanceForm";
import { GrazingForm } from "@/components/analysis/GrazingForm";
import { MovementForm } from "@/components/analysis/MovementForm";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type FormState, formStateOfRun } from "@/lib/analyses";

/** The one place an analysis is set up: a dialog with the module's form, for a new run or
 * for a change to an existing one (its settings filled in; "Run as new" keeps the old run,
 * "Run and replace" carries its name and sharing to the new run and removes the old). */
export function RunDialog({
  projectId,
  module,
  open,
  onOpenChange,
  initial,
  editing = null,
  onCreated,
}: {
  projectId: string;
  module:
    | "movement"
    | "grazing"
    | "device_performance"
    | "contact_tracing"
    | "cardiac";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The form's first state: defaults, a deep link's choices, or an existing run's. */
  initial: FormState;
  editing?: AnalysisRun | null;
  onCreated: (run: AnalysisRun, replaced: AnalysisRun | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-x-hidden overflow-y-auto sm:max-w-4xl [&>*]:min-w-0">
        <DialogHeader>
          <DialogTitle>
            {editing
              ? t("Change and run again")
              : module === "movement"
                ? t("New movement analysis")
                : module === "grazing"
                  ? t("New grazing analysis")
                  : module === "contact_tracing"
                    ? t("New contact tracing analysis")
                    : module === "cardiac"
                      ? t("New cardiac analysis")
                      : t("New device performance analysis")}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? t(
                  "The settings of the run as it was made; change what you want, then run it as a new run or in place of this one.",
                )
              : module === "device_performance"
                ? t("Choose the devices and the period, then run.")
                : t(
                    "Choose the subjects, the period and the method, then run.",
                  )}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <RunDialogBody
            key={editing?.id ?? "new"}
            projectId={projectId}
            module={module}
            initial={editing ? formStateOfRun(editing, initial) : initial}
            editing={editing}
            onCreated={onCreated}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** The form with its own state, remounted per run edited (the key above). */
function RunDialogBody({
  projectId,
  module,
  initial,
  editing,
  onCreated,
}: {
  projectId: string;
  module:
    | "movement"
    | "grazing"
    | "device_performance"
    | "contact_tracing"
    | "cardiac";
  initial: FormState;
  editing: AnalysisRun | null;
  onCreated: (run: AnalysisRun, replaced: AnalysisRun | null) => void;
}) {
  const [state, setState] = useState<FormState>(initial);
  const update = (patch: Partial<FormState>) =>
    setState((s) => ({ ...s, ...patch }));
  const props = {
    projectId,
    state,
    onChange: update,
    editing: editing ? { name: editing.name, shared: editing.shared } : null,
    onRun: (run: AnalysisRun, replaced: boolean) =>
      onCreated(run, replaced ? editing : null),
  };
  if (module === "movement") return <MovementForm {...props} />;
  if (module === "grazing") return <GrazingForm {...props} />;
  if (module === "contact_tracing") return <ContactTracingForm {...props} />;
  if (module === "cardiac") return <CardiacForm {...props} />;
  return <DevicePerformanceForm {...props} />;
}
