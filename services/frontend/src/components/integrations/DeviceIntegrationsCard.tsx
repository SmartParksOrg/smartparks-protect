import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceIntegration } from "@/api/types";
import { DeploymentList } from "@/components/integrations/DeploymentList";
import { IntegrationHead } from "@/components/integrations/EntityIntegrationsCard";
import { SubjectActions } from "@/components/integrations/SubjectActions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** The integrations of the project whose target keeps a register, seen from the device
 * (decision D418): the device is the sensor, the entity it is on is the animal. It shows the
 * entity it is on now with how that entity stands, the same Integrate, Change and Stop as
 * the entity's page, and the device's deployments: on which animals it was sent, which wait
 * for a person, and whether the target still has it on an entity it left. */
export function DeviceIntegrationsCard({
  projectId,
  deviceId,
  canWrite,
}: {
  projectId: string;
  deviceId: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: queryKeys.deviceIntegrations(projectId, deviceId),
    queryFn: () =>
      api.get<DeviceIntegration[]>(
        `/api/v1/projects/${projectId}/integrations/by-device/${deviceId}`,
      ),
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
              <p className="text-xs break-words text-muted-foreground">
                {i.entity_id ? (
                  <>
                    {t("On entity")}{" "}
                    <Link
                      className="underline"
                      to={`/projects/${projectId}/entities/${i.entity_id}`}
                    >
                      {i.entity_name}
                    </Link>
                  </>
                ) : (
                  t(
                    "The device is on no entity. Assign it to an entity to integrate that entity.",
                  )
                )}
              </p>
              {!i.enabled && (
                <p className="text-xs text-muted-foreground">
                  {t("The integration is switched off; nothing is sent.")}
                </p>
              )}
              <DeploymentList
                projectId={projectId}
                deployments={i.deployments ?? []}
                target={i.connector_label}
                canWrite={canWrite}
              />
              {canWrite && i.entity_id && (
                <SubjectActions
                  projectId={projectId}
                  entityId={i.entity_id}
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
