import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { IntegrationSubjects } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { DeploymentList } from "@/components/integrations/DeploymentList";
import { SubjectStateBadge } from "@/components/integrations/SubjectStateBadge";

/** The entities integrated with a target that keeps a register of its own, with what the
 * target has for each (decisions D408 and D412): the overview on the integration. Nothing is
 * changed here; an entity is integrated from its own page, where its species and history are
 * chosen. Shown to people who may change integrations, since the read uses the
 * integration's credentials. Devices that came onto an integrated entity and wait for a
 * person are listed first, with Confirm and Decline (decision D416). */
export function SubjectsCard({
  projectId,
  integrationId,
  target,
}: {
  projectId: string;
  integrationId: string;
  /** The connector's name, as the page shows it. */
  target: string;
}) {
  const { t } = useTranslation();
  const subjects = useQuery({
    queryKey: queryKeys.integrationSubjects(projectId, integrationId),
    queryFn: () =>
      api.get<IntegrationSubjects>(
        `/api/v1/projects/${projectId}/integrations/${integrationId}/subjects`,
      ),
    retry: false,
    refetchInterval: 10_000,
  });
  const items = subjects.data?.items ?? [];
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">
        {t("Entities on {{target}}", { target })}
      </h3>
      {subjects.isPending ? (
        <p className="text-muted-foreground">{t("Loading…")}</p>
      ) : subjects.error ? (
        <Callout kind="warning">{subjects.error.message}</Callout>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">
          {t(
            "No entity is integrated yet. Open an entity and choose Integrate on its Integrations card.",
          )}
        </p>
      ) : (
        <>
          {(subjects.data?.waiting?.length ?? 0) > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                {t(
                  "Devices that came onto an integrated entity. Their data for it waits until you confirm.",
                )}
              </p>
              <DeploymentList
                projectId={projectId}
                deployments={subjects.data?.waiting ?? []}
                target={target}
                canWrite
              />
            </div>
          )}
          {subjects.data?.target_error && (
            <Callout kind="warning">
              {t("{{target}} could not be asked: {{error}}", {
                target,
                error: subjects.data.target_error,
              })}
            </Callout>
          )}
          <ul className="divide-y rounded-md border">
            {items.map((s) => (
              <li key={s.entity_id} className="space-y-0.5 p-2">
                <div className="flex items-start justify-between gap-2">
                  <Link
                    className="min-w-0 font-medium break-words underline"
                    to={`/projects/${projectId}/entities/${s.entity_id}`}
                  >
                    {s.entity_name}
                  </Link>
                  <SubjectStateBadge subject={s} />
                </div>
                <p className="text-xs break-words text-muted-foreground">
                  {[
                    s.target?.sensor_id &&
                      t("sensor {{id}}", { id: s.target.sensor_id }),
                    s.species_name,
                    s.target &&
                      (s.target.registered
                        ? t("on {{target}} as {{name}}", {
                            target,
                            name: s.target.external_name ?? s.entity_name,
                          })
                        : s.target.elsewhere
                          ? t("the sensor is on {{name}} on {{target}}", {
                              target,
                              name: s.target.elsewhere,
                            })
                          : t("not on {{target}} yet", { target })),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {s.detail && (
                  <p className="text-xs break-words text-destructive">
                    {s.detail}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
