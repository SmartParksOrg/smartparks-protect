import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityIntegration } from "@/api/types";
import { DeploymentList } from "@/components/integrations/DeploymentList";
import { SubjectActions } from "@/components/integrations/SubjectActions";
import { SubjectStateBadge } from "@/components/integrations/SubjectStateBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatTime } from "@/lib/format";

/** The integrations this entity can be part of, on its own page (decision D412): those of
 * the project whose target keeps a register of its entities. Each says where the entity
 * stands, which of its devices the target has on its animal and which wait for a person
 * (decision D416), and lets a person who may change integrations integrate it, change what
 * was chosen, stop, or confirm a device. Nothing at all in a project without such an
 * integration. */
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
  const list = useQuery({
    queryKey: queryKeys.entityIntegrations(projectId, entityId),
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
  const items = list.data ?? [];
  if (items.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Integrations")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {items.map((i) => (
            <li
              key={i.integration_id}
              className="space-y-1 py-2 first:pt-0 last:pb-0"
            >
              <IntegrationHead
                name={i.name}
                label={i.connector_label}
                subject={i.subject}
              />
              {!i.enabled && (
                <p className="text-xs text-muted-foreground">
                  {t("The integration is switched off; nothing is sent.")}
                </p>
              )}
              {i.subject?.state === "registered" &&
                (i.deployments ?? []).length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    {t(
                      "No device is on this entity. The first device assigned to it waits here for your confirmation.",
                    )}
                  </p>
                )}
              <DeploymentList
                projectId={projectId}
                deployments={i.deployments ?? []}
                target={i.connector_label}
                canWrite={canWrite}
              />
              {canWrite && (
                <SubjectActions
                  projectId={projectId}
                  entityId={entityId}
                  integrationId={i.integration_id}
                  target={i.connector_label}
                  subject={i.subject}
                />
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/** The integration's name with where the entity stands there, and what was chosen. */
export function IntegrationHead({
  name,
  label,
  subject,
}: {
  name: string;
  label: string;
  subject: EntityIntegration["subject"];
}) {
  const { t } = useTranslation();
  const s = subject;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 font-medium break-words">
          {name}
          {name !== label && (
            <span className="font-normal text-muted-foreground">
              {" · "}
              {label}
            </span>
          )}
        </span>
        {s ? (
          <SubjectStateBadge subject={s} />
        ) : (
          <span className="text-muted-foreground">{t("Not integrated")}</span>
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
            // the animal is made first and its sensor follows the history (decision D425)
            s.state === "sending_history" &&
              s.external_id &&
              t("animal made, its sensor follows the history"),
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
        <p className="text-xs break-words text-destructive">{s.detail}</p>
      )}
    </>
  );
}
