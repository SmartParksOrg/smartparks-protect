import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  DeviceDataSpan,
  DeviceDetail,
  EntityAssignment,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { AssignmentStartField } from "@/components/devices/AssignmentStartField";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProject } from "@/hooks/useProjects";
import { formatTime, startOfDayIso } from "@/lib/format";

/** Change when a device tracked an entity (decision D103): the start from the guided choices, the
 * end as a date or open again. Records between the old and the new bounds follow the change. */
export function ChangeAssignmentDialog({
  projectId,
  assignment,
  open,
  onOpenChange,
}: {
  projectId: string;
  assignment: EntityAssignment;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const { project } = useProject(projectId);
  const timeZone = project?.timezone ?? "UTC";
  const [validFrom, setValidFrom] = useState<string>(assignment.valid_from);
  const [endMode, setEndMode] = useState<"keep" | "open" | "date">(
    assignment.valid_to ? "keep" : "open",
  );
  const [endDate, setEndDate] = useState(() =>
    (assignment.valid_to ?? new Date().toISOString()).slice(0, 10),
  );
  const span = useQuery({
    queryKey: queryKeys.deviceSpan(assignment.device_id),
    queryFn: () =>
      api.get<DeviceDataSpan>(
        `/api/v1/devices/${assignment.device_id}/data-span`,
      ),
    enabled: open,
  });
  const detail = useQuery({
    queryKey: queryKeys.device(assignment.device_id),
    queryFn: () =>
      api.get<DeviceDetail>(`/api/v1/devices/${assignment.device_id}`),
    enabled: open,
  });
  const joinedAt =
    detail.data?.project_assignments.find((a) => a.project_id === projectId)
      ?.valid_from ?? null;
  const change = useMutationToast({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      if (validFrom !== assignment.valid_from) body.valid_from = validFrom;
      if (endMode === "open" && assignment.valid_to) body.valid_to = null;
      if (endMode === "date") body.valid_to = startOfDayIso(endDate, timeZone);
      return api.patch<EntityAssignment>(
        `/api/v1/projects/${projectId}/entity-assignments/${assignment.id}`,
        { body },
      );
    },
    invalidate: [
      queryKeys.entityAssignments(projectId),
      queryKeys.currentState(projectId),
      queryKeys.device(assignment.device_id),
      queryKeys.deviceSpan(assignment.device_id),
      queryKeys.devices({ projectId, unassigned: true }),
    ],
    success: t("Assignment changed; the records in between follow"),
    onSuccess: () => onOpenChange(false),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("Change the assignment of {{device}}", {
              device: assignment.device_name ?? t("the device"),
            })}
          </DialogTitle>
          <DialogDescription>
            {t("Today: {{from}} to {{to}}", {
              from: formatTime(assignment.valid_from),
              to: assignment.valid_to
                ? formatTime(assignment.valid_to)
                : t("now"),
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field
            label={t("Tracking since")}
            htmlFor="change-start"
            hint={t(
              "Records between the old and the new start move with it; the device must be in the project at the new start.",
            )}
          >
            {span.isPending || detail.isPending ? (
              <div className="text-sm text-muted-foreground">
                {t("Looking up the device's data…")}
              </div>
            ) : (
              <AssignmentStartField
                idPrefix="change"
                span={span.data}
                joinedAt={joinedAt}
                timeZone={timeZone}
                onChange={setValidFrom}
              />
            )}
          </Field>
          <Field label={t("Until")} htmlFor="change-end">
            <div className="space-y-2 text-sm">
              {assignment.valid_to && (
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="change-end"
                    className="accent-primary"
                    checked={endMode === "keep"}
                    onChange={() => setEndMode("keep")}
                  />
                  {t("Keep {{date}}", {
                    date: formatTime(assignment.valid_to),
                  })}
                </label>
              )}
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="change-end"
                  className="accent-primary"
                  checked={endMode === "open"}
                  onChange={() => setEndMode("open")}
                />
                {t("Still tracking (no end)")}
              </label>
              <label className="flex flex-wrap items-center gap-2">
                <input
                  type="radio"
                  name="change-end"
                  className="accent-primary"
                  checked={endMode === "date"}
                  onChange={() => setEndMode("date")}
                />
                {t("Ended on")}{" "}
                <Input
                  id="change-end"
                  type="date"
                  className="h-8 w-40"
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value);
                    setEndMode("date");
                  }}
                  aria-label={t("End date")}
                />
                <span className="text-xs text-muted-foreground">
                  {t("start of the day, {{zone}}", { zone: timeZone })}
                </span>
              </label>
            </div>
          </Field>
          {change.isError && (
            <Callout kind="error">{change.error.message}</Callout>
          )}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={change.isPending || span.isPending}
            onClick={() => change.mutate()}
          >
            {change.isPending ? t("Saving…") : t("Save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
