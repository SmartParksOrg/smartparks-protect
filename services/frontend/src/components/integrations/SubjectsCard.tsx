import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { IntegrationSubjects } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONES: Record<string, string> = {
  registered: "bg-brand-green-light/40 text-foreground border-transparent",
  not_registered: "bg-brand-sand/50 text-foreground border-transparent",
  blocked: "bg-destructive/15 text-destructive border-transparent",
};

/** The entities ticked on an integration whose target keeps a register of its own, with
 * what the target has for each (decision D408): registered, not yet, or why it cannot be.
 * "Register now" makes what is missing at once; "Send history, then register" opens the
 * backfill with its tick, the safe order when the target reacts to old readings (decision
 * D409). Shown to people who may change integrations, since the read uses the
 * integration's credentials. */
export function SubjectsCard({
  projectId,
  integrationId,
  target,
  hasEntities,
  onHistory,
}: {
  projectId: string;
  integrationId: string;
  /** The connector's name, as the page shows it. */
  target: string;
  hasEntities: boolean;
  onHistory: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const path = `/api/v1/projects/${projectId}/integrations/${integrationId}/subjects`;
  const key = queryKeys.integrationSubjects(projectId, integrationId);
  const subjects = useQuery({
    queryKey: key,
    queryFn: () => api.get<IntegrationSubjects>(path),
    enabled: hasEntities,
    retry: false,
  });
  const register = useMutationToast({
    mutationFn: () => api.post<IntegrationSubjects>(`${path}/register`),
    invalidate: [key],
    success: (answer) =>
      t("{{count}} registered on {{target}}", {
        count: answer.items.filter((s) => s.state === "registered").length,
        target,
      }),
    onSuccess: () => setConfirming(false),
    onError: () => setConfirming(false),
  });
  const label: Record<string, string> = {
    registered: t("Registered"),
    not_registered: t("Not registered"),
    blocked: t("Cannot be registered"),
  };
  const items = subjects.data?.items ?? [];
  const missing = items.filter((s) => s.state === "not_registered").length;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">
        {t("Entities on {{target}}", { target })}
      </h3>
      {!hasEntities ? (
        <p className="text-muted-foreground">
          {t(
            "Tick the entities to forward under Edit. They can then be registered on {{target}} from here.",
            { target },
          )}
        </p>
      ) : subjects.isPending ? (
        <p className="text-muted-foreground">
          {t("Asking {{target}}…", { target })}
        </p>
      ) : subjects.error ? (
        <Callout kind="warning">{subjects.error.message}</Callout>
      ) : (
        <>
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
                  <Badge
                    variant="outline"
                    className={cn("shrink-0", TONES[s.state])}
                  >
                    {label[s.state]}
                  </Badge>
                </div>
                <p className="text-xs break-words text-muted-foreground">
                  {[
                    s.sensor_id && t("sensor {{id}}", { id: s.sensor_id }),
                    s.species,
                    s.state === "registered" &&
                      s.since &&
                      t("since {{time}}", { time: formatTime(s.since) }),
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
          {missing > 0 && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={onHistory}>
                {t("Send history, then register")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setConfirming(true)}
              >
                {t("Register now")}
              </Button>
            </div>
          )}
        </>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("Register {{count}} on {{target}}?", {
          count: missing,
          target,
        })}
        description={t(
          "An animal and a sensor deployment are made on {{target}} for each entity that has none. From then on {{target}} treats every reading of the sensor as that animal's, old ones as well. To send the history first, choose 'Send history, then register'.",
          { target },
        )}
        confirmLabel={t("Register now")}
        onConfirm={() => register.mutate()}
        pending={register.isPending}
      />
    </div>
  );
}
