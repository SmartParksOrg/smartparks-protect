import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityIntegration } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { IntegrateEntityDialog } from "@/components/integrations/IntegrateEntityDialog";
import { SubjectStateBadge } from "@/components/integrations/SubjectStateBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

/** The integrations this entity can be part of, on its own page (decision D412): those of
 * the project whose target keeps a register of its entities. Each says where the entity
 * stands and lets a person who may change integrations integrate it, change what was
 * chosen, or stop. Nothing at all in a project without such an integration. */
export function EntityIntegrationsCard({
  projectId,
  entityId,
  canWrite,
}: {
  projectId: string;
  entityId: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const key = queryKeys.entityIntegrations(projectId, entityId);
  const [integrating, setIntegrating] = useState<EntityIntegration | null>(
    null,
  );
  const [stopping, setStopping] = useState<EntityIntegration | null>(null);
  const list = useQuery({
    queryKey: key,
    queryFn: () =>
      api.get<EntityIntegration[]>(
        `/api/v1/projects/${projectId}/integrations/by-entity/${entityId}`,
      ),
    // while a history is on its way the card follows it
    refetchInterval: (query) =>
      query.state.data?.some(
        (i) =>
          i.subject?.state === "history_requested" ||
          i.subject?.state === "sending_history",
      )
        ? 5_000
        : false,
  });
  const stop = useMutationToast({
    mutationFn: (i: EntityIntegration) =>
      api.delete(
        `/api/v1/projects/${projectId}/integrations/${i.integration_id}/subjects/${entityId}`,
      ),
    invalidate: [key],
    success: t("No longer forwarded"),
    onSuccess: () => setStopping(null),
    onError: () => setStopping(null),
  });
  const items = list.data ?? [];
  if (items.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Integrations")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {items.map((i) => {
            const s = i.subject;
            const busy =
              s?.state === "history_requested" ||
              s?.state === "sending_history";
            return (
              <li
                key={i.integration_id}
                className="space-y-1 py-2 first:pt-0 last:pb-0"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 font-medium break-words">
                    {i.name}
                    {i.name !== i.connector_label && (
                      <span className="font-normal text-muted-foreground">
                        {" · "}
                        {i.connector_label}
                      </span>
                    )}
                  </span>
                  {s ? (
                    <SubjectStateBadge subject={s} />
                  ) : (
                    <span className="text-muted-foreground">
                      {t("Not integrated")}
                    </span>
                  )}
                </div>
                {s && (
                  <p className="text-xs break-words text-muted-foreground">
                    {[
                      s.species_name,
                      s.registered_at &&
                        t("registered {{time}}", {
                          time: formatTime(s.registered_at),
                        }),
                      s.history_from &&
                        t("history from {{time}}, {{count}} objects", {
                          time: formatTime(s.history_from),
                          count: s.history_queued,
                        }),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                )}
                {s?.detail && (
                  <p className="text-xs break-words text-destructive">
                    {s.detail}
                  </p>
                )}
                {!i.enabled && (
                  <p className="text-xs text-muted-foreground">
                    {t("The integration is switched off; nothing is sent.")}
                  </p>
                )}
                {canWrite && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Button
                      size="sm"
                      variant={s ? "outline" : "default"}
                      disabled={busy}
                      onClick={() => setIntegrating(i)}
                    >
                      {s ? t("Change") : t("Integrate")}
                    </Button>
                    {s && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setStopping(i)}
                      >
                        {t("Stop")}
                      </Button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
      {integrating && (
        <IntegrateEntityDialog
          projectId={projectId}
          entityId={entityId}
          integrationId={integrating.integration_id}
          target={integrating.connector_label}
          open
          onOpenChange={(o) => !o && setIntegrating(null)}
        />
      )}
      <ConfirmDialog
        open={stopping !== null}
        onOpenChange={(o) => !o && setStopping(null)}
        title={t("Stop forwarding to {{target}}?", {
          target: stopping?.connector_label ?? "",
        })}
        description={t(
          "No new data of this entity is sent. What {{target}} has already stays there: the animal, its sensor and its readings.",
          { target: stopping?.connector_label ?? "" },
        )}
        confirmLabel={t("Stop")}
        onConfirm={() => stopping && stop.mutate(stopping)}
        pending={stop.isPending}
      />
    </Card>
  );
}
