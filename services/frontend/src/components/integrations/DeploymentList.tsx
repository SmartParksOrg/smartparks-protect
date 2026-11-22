import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Deployment } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { api } from "@/api/client";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONES: Record<Deployment["state"], string> = {
  sent: "bg-brand-green-light/40 text-foreground border-transparent",
  pending: "bg-brand-sand/50 text-foreground border-transparent",
  refused: "bg-destructive/15 text-destructive border-transparent",
  declined: "bg-muted text-muted-foreground border-transparent",
};

/** A device on an integrated entity as a deployment of its sensor on the target's animal
 * (decisions D416 to D419): what was sent, and what waits for a person. A deployment that
 * waits holds the device's data for that entity until somebody confirms it, since the
 * target would put it on the animal the sensor was on before; declining it means that
 * data is not sent. The same list shows on the entity, on the device and on the
 * integration. */
export function DeploymentList({
  projectId,
  deployments,
  target,
  canWrite,
}: {
  projectId: string;
  deployments: Deployment[];
  /** The connector's name, as the page shows it. */
  target: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState<Deployment | null>(null);
  const [declining, setDeclining] = useState<Deployment | null>(null);
  // the entity cards, the device cards and the integration's overview all read these rows
  const invalidate = [
    ["projects", projectId, "integrations"],
    ["projects", projectId, "entities"],
  ];
  const path = (d: Deployment, action: string) =>
    `/api/v1/projects/${projectId}/integrations/${d.integration_id}/deployments/${d.id}/${action}`;
  const confirm = useMutationToast({
    mutationFn: (d: Deployment) => api.post<Deployment>(path(d, "confirm")),
    invalidate,
    success: (d) =>
      d.state === "sent"
        ? t("Sent to {{target}}", { target })
        : t("{{target}} refused the deployment", { target }),
    onSuccess: () => setConfirming(null),
    onError: () => setConfirming(null),
  });
  const decline = useMutationToast({
    mutationFn: (d: Deployment) => api.post<Deployment>(path(d, "decline")),
    invalidate,
    success: t("Declined; the data of that period is not sent"),
    onSuccess: () => setDeclining(null),
    onError: () => setDeclining(null),
  });
  if (deployments.length === 0) return null;
  const label: Record<Deployment["state"], string> = {
    sent: t("On {{target}}", { target }),
    pending: t("Waits for you"),
    refused: t("Refused"),
    declined: t("Declined"),
  };
  return (
    <>
      <ul className="space-y-2">
        {deployments.map((d) => {
          const waits = d.state === "pending" || d.state === "refused";
          return (
            <li key={d.id} className="space-y-1 rounded-md border p-2 text-xs">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <span className="min-w-0 break-words">
                  {t("{{device}} on {{entity}}", {
                    device: d.device_name,
                    entity: d.entity_name,
                  })}
                  <span className="block text-muted-foreground">
                    {d.ends_at
                      ? t("{{from}} to {{to}}", {
                          from: formatTime(d.starts_at),
                          to: formatTime(d.ends_at),
                        })
                      : t("since {{time}}", { time: formatTime(d.starts_at) })}
                    {d.sensor_id && (
                      <>
                        {" · "}
                        <span className="font-mono break-all">
                          {d.sensor_id}
                        </span>
                      </>
                    )}
                  </span>
                </span>
                <Badge
                  variant="outline"
                  className={cn("shrink-0", TONES[d.state])}
                >
                  {label[d.state]}
                </Badge>
              </div>
              {d.state === "pending" && (
                <p className="text-muted-foreground">
                  {t(
                    "The device came onto this entity. Its data for this entity waits until you confirm the deployment on {{target}}.",
                    { target },
                  )}
                </p>
              )}
              {d.detail && (
                <p
                  className={cn(
                    "break-words",
                    d.state === "refused"
                      ? "text-destructive"
                      : "text-muted-foreground",
                  )}
                >
                  {d.detail}
                </p>
              )}
              {d.state === "sent" && d.open_on_target && d.ends_at && (
                <p className="text-muted-foreground">
                  {t(
                    "The device left this entity. {{target}} keeps the sensor on this animal, since it cannot end a deployment; that ends when the sensor is deployed again.",
                    { target },
                  )}
                </p>
              )}
              {waits && canWrite && (
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button size="sm" onClick={() => setConfirming(d)}>
                    {d.state === "refused" ? t("Try again") : t("Confirm")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setDeclining(d)}
                  >
                    {t("Decline")}
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(o) => !o && setConfirming(null)}
        title={t("Put {{device}} on {{entity}} on {{target}}?", {
          device: confirming?.device_name ?? "",
          entity: confirming?.entity_name ?? "",
          target,
        })}
        description={
          confirming && (
            <span className="block space-y-2">
              <span className="block">
                {t(
                  "{{target}} gets a deployment of sensor {{sensor}} on the animal of {{entity}} from {{time}}. It ends the sensor's deployment before it at that moment. Then the held data of {{entity}} is sent, oldest first.",
                  {
                    target,
                    sensor: confirming.sensor_id ?? "",
                    entity: confirming.entity_name,
                    time: formatTime(confirming.starts_at),
                  },
                )}
              </span>
              {confirming.rewrites > 0 && (
                <span className="block rounded-md border border-brand-sand bg-brand-sand/30 px-3 py-2 text-foreground">
                  {t(
                    "This sensor had {{count}} finished deployments on {{target}} before. {{target}} sets the end of those to this start as well, so their animals' tracks will be wrong after it. This is a fault in {{target}}.",
                    { count: confirming.rewrites, target },
                  )}
                </span>
              )}
              <span className="block">
                {t("A deployment cannot be removed from {{target}}.", {
                  target,
                })}
              </span>
            </span>
          )
        }
        confirmLabel={t("Confirm")}
        destructive={false}
        onConfirm={() => confirming && confirm.mutate(confirming)}
        pending={confirm.isPending}
      />
      <ConfirmDialog
        open={declining !== null}
        onOpenChange={(o) => !o && setDeclining(null)}
        title={t("Decline this deployment?")}
        description={
          declining &&
          t(
            "Nothing is sent to {{target}}. The data of {{device}} on {{entity}} from {{time}} is not sent either.",
            {
              target,
              device: declining.device_name,
              entity: declining.entity_name,
              time: formatTime(declining.starts_at),
            },
          )
        }
        confirmLabel={t("Decline")}
        onConfirm={() => declining && decline.mutate(declining)}
        pending={decline.isPending}
      />
    </>
  );
}
