import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  DeviceDataSpan,
  DeviceDetail,
  Page as PageType,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { AssignmentStartField } from "@/components/devices/AssignmentStartField";
import { HealthLine } from "@/components/devices/HealthCard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { useProject } from "@/hooks/useProjects";
import { formatAgo } from "@/lib/format";

/** Assign one of the project's devices that tracks nothing today to an entity, from a start the
 * guided field offers (decisions D103 and D106). */
export function AssignDeviceDialog({
  projectId,
  entityId,
  entityName,
  open,
  onOpenChange,
}: {
  projectId: string;
  entityId: string;
  entityName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t("Assign a device to {{name}}", { name: entityName })}
          </DialogTitle>
        </DialogHeader>
        {open && (
          <AssignDeviceForm
            projectId={projectId}
            entityId={entityId}
            entityName={entityName}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Mounted while the dialog is open, so every opening starts with nothing chosen. */
function AssignDeviceForm({
  projectId,
  entityId,
  entityName,
  onDone,
}: {
  projectId: string;
  entityId: string;
  entityName: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const { project } = useProject(projectId);
  const [q, setQ] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [validFrom, setValidFrom] = useState(() => new Date().toISOString());
  const candidates = useQuery({
    queryKey: queryKeys.devices({ projectId, unassigned: true }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, unassigned: true, limit: 500 },
      }),
  });
  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    const items = candidates.data?.items ?? [];
    return term
      ? items.filter(
          (d) =>
            d.name.toLowerCase().includes(term) ||
            (d.serial_number ?? "").toLowerCase().includes(term),
        )
      : items;
  }, [candidates.data, q]);
  const detail = useQuery({
    queryKey: queryKeys.device(deviceId),
    queryFn: () => api.get<DeviceDetail>(`/api/v1/devices/${deviceId}`),
    enabled: Boolean(deviceId),
  });
  const span = useQuery({
    queryKey: queryKeys.deviceSpan(deviceId),
    queryFn: () =>
      api.get<DeviceDataSpan>(`/api/v1/devices/${deviceId}/data-span`),
    enabled: Boolean(deviceId),
  });
  const joinedAt =
    detail.data?.project_assignments.find(
      (a) => a.project_id === projectId && !a.valid_to,
    )?.valid_from ?? null;
  const assign = useMutationToast({
    mutationFn: () =>
      api.post(`/api/v1/projects/${projectId}/entity-assignments`, {
        body: {
          device_id: deviceId,
          entity_id: entityId,
          valid_from: validFrom,
        },
      }),
    invalidate: [
      queryKeys.entityAssignments(projectId),
      queryKeys.device(deviceId),
      queryKeys.deviceSpan(deviceId),
      queryKeys.devices({ projectId, unassigned: true }),
      queryKeys.currentState(projectId),
    ],
    success: t("Device assigned to {{name}}", { name: entityName }),
    onSuccess: onDone,
  });
  return (
    <>
      <div className="space-y-4">
        <Field
          label={t("Device")}
          htmlFor="assign-device-search"
          hint={t(
            "Devices of this project that track nothing today. A device on another entity must be released there first.",
          )}
        >
          <Input
            id="assign-device-search"
            placeholder={t("Search by name or serial")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </Field>
        <div
          className="max-h-56 overflow-y-auto rounded-md border"
          role="listbox"
          aria-label={t("Devices")}
        >
          {candidates.isPending && (
            <div className="p-3 text-sm text-muted-foreground">
              {t("Loading devices…")}
            </div>
          )}
          {candidates.data && shown.length === 0 && (
            <div className="p-3 text-sm text-muted-foreground">
              {candidates.data.items.length === 0
                ? t("Every device of this project already tracks an entity.")
                : t("No device matches.")}
            </div>
          )}
          {shown.map((d) => (
            <button
              key={d.id}
              type="button"
              role="option"
              aria-selected={d.id === deviceId}
              className={`flex w-full flex-wrap items-center gap-3 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted ${d.id === deviceId ? "bg-muted" : ""}`}
              onClick={() => setDeviceId(d.id)}
            >
              <span className="font-medium">{d.name}</span>
              {d.serial_number && (
                <span className="font-mono text-xs text-muted-foreground">
                  {d.serial_number}
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {formatAgo(d.last_seen_at, now)}
              </span>
              <span className="ml-auto">
                <HealthLine health={d.health} />
              </span>
            </button>
          ))}
        </div>
        {deviceId && (
          <Field label={t("Tracking since")} htmlFor="entity-choice">
            {span.isPending || detail.isPending ? (
              <div className="text-sm text-muted-foreground">
                {t("Looking up the device's data…")}
              </div>
            ) : (
              <AssignmentStartField
                idPrefix="entity"
                span={span.data}
                joinedAt={joinedAt}
                timeZone={project?.timezone ?? "UTC"}
                onChange={setValidFrom}
              />
            )}
          </Field>
        )}
        {assign.isError && (
          <Callout kind="error">{assign.error.message}</Callout>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          {t("Cancel")}
        </Button>
        <Button
          type="button"
          disabled={!deviceId || span.isPending || assign.isPending}
          onClick={() => assign.mutate()}
        >
          {assign.isPending ? t("Assigning…") : t("Assign device")}
        </Button>
      </DialogFooter>
    </>
  );
}
