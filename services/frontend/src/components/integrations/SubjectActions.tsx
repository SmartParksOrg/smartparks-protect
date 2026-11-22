import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { IntegrationSubject } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { IntegrateEntityDialog } from "@/components/integrations/IntegrateEntityDialog";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";

/** Integrate, Change and Stop for one entity and one integration (decisions D412 and D418):
 * the same buttons and dialogs on the entity's page and on the page of the device on it. */
export function SubjectActions({
  projectId,
  entityId,
  integrationId,
  target,
  subject,
}: {
  projectId: string;
  entityId: string;
  integrationId: string;
  /** The connector's name, as the page shows it. */
  target: string;
  subject: IntegrationSubject | null | undefined;
}) {
  const { t } = useTranslation();
  const [integrating, setIntegrating] = useState(false);
  const [stopping, setStopping] = useState(false);
  const busy =
    subject?.state === "history_requested" ||
    subject?.state === "sending_history";
  const stop = useMutationToast({
    mutationFn: () =>
      api.delete(
        `/api/v1/projects/${projectId}/integrations/${integrationId}/subjects/${entityId}`,
      ),
    invalidate: [
      ["projects", projectId, "integrations"],
      ["projects", projectId, "entities"],
    ],
    success: t("No longer forwarded"),
    onSuccess: () => setStopping(false),
    onError: () => setStopping(false),
  });
  return (
    <div className="flex flex-wrap gap-2 pt-1">
      <Button
        size="sm"
        variant={subject ? "outline" : "default"}
        disabled={busy}
        onClick={() => setIntegrating(true)}
      >
        {subject ? t("Change") : t("Integrate")}
      </Button>
      {subject && (
        <Button size="sm" variant="ghost" onClick={() => setStopping(true)}>
          {t("Stop")}
        </Button>
      )}
      {integrating && (
        <IntegrateEntityDialog
          projectId={projectId}
          entityId={entityId}
          integrationId={integrationId}
          target={target}
          open
          onOpenChange={(o) => !o && setIntegrating(false)}
        />
      )}
      <ConfirmDialog
        open={stopping}
        onOpenChange={setStopping}
        title={t("Stop forwarding to {{target}}?", { target })}
        description={t(
          "No new data of this entity is sent. What {{target}} has already stays there: the animal, its sensor and its readings.",
          { target },
        )}
        confirmLabel={t("Stop")}
        onConfirm={() => stop.mutate(undefined)}
        pending={stop.isPending}
      />
    </div>
  );
}
