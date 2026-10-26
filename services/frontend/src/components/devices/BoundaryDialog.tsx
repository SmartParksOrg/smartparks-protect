import { useTranslation } from "react-i18next";
import { type QueryKey, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { BoundaryResult, EdgeChange, LastMessage } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { TimezoneSelect } from "@/components/TimezoneSelect";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { type Edge, isoToWall, wallToIso } from "@/lib/assignments";
import { formatTime } from "@/lib/format";
import { zoneLabel } from "@/lib/timezones";

/** Which boundary the dialog moves: one edge of one row, or a project edge and an entity edge
 * that share an instant, moved together (the chained correction of decision D355). */
export type BoundaryTarget =
  | { kind: "project" | "entity"; assignmentId: string; edge: Edge; current: string; name: string }
  | {
      kind: "both";
      projectAssignmentId: string;
      projectEdge: Edge;
      entityAssignmentId: string;
      entityEdge: Edge;
      current: string;
    };

/** Move an assignment boundary after the fact (decisions D355 to D358): a wall-clock time in
 * the project's timezone (any zone can be picked), "the last uplink before" offered from the
 * device's own messages, a required reason, and the API's preview of every row that moves
 * and the window the records are attributed again over; a refusal (future, empty, crossing,
 * outside the project) shows inline in the reader's words. */
export function BoundaryDialog({ deviceId, target, timeZone, open, onOpenChange, invalidate }: {
  deviceId: string;
  target: BoundaryTarget | null;
  timeZone: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invalidate: QueryKey[];
}) {
  const { t } = useTranslation();
  const title =
    target?.kind === "both"
      ? t("Correct the project and the entity boundary together")
      : target?.kind === "project"
        ? target.edge === "start"
          ? t("Move the start of the project assignment")
          : t("Move the end of the project assignment")
        : target?.edge === "start"
          ? t("Move the start of the entity assignment")
          : t("Move the end of the entity assignment");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        {open && target && (
          <BoundaryForm deviceId={deviceId} target={target} timeZone={timeZone} invalidate={invalidate} onDone={() => onOpenChange(false)} onCancel={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function requestOf(deviceId: string, target: BoundaryTarget, iso: string, reason: string, preview: boolean) {
  if (target.kind === "both")
    return {
      url: `/api/v1/devices/${deviceId}/assignments/correct`,
      method: "post" as const,
      body: {
        project_assignment_id: target.projectAssignmentId,
        entity_assignment_id: target.entityAssignmentId,
        project_edge: target.projectEdge,
        entity_edge: target.entityEdge,
        instant: iso,
        reason,
        preview,
      },
    };
  return {
    url: `/api/v1/devices/${deviceId}/${target.kind}-assignments/${target.assignmentId}/boundary`,
    method: "patch" as const,
    body: { [target.edge === "start" ? "valid_from" : "valid_to"]: iso, reason, preview },
  };
}

/** Mounted while the dialog is open, so every opening starts from the current boundary. */
function BoundaryForm({ deviceId, target, timeZone: projectZone, invalidate, onDone, onCancel }: {
  deviceId: string;
  target: BoundaryTarget;
  timeZone: string;
  invalidate: QueryKey[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [zone, setZone] = useState(projectZone);
  const [wall, setWall] = useState(() => isoToWall(target.current, projectZone));
  const [reason, setReason] = useState("");
  const [snapAsked, setSnapAsked] = useState(false);
  const iso = wallToIso(wall, zone);
  const changed = iso !== null && new Date(iso).getTime() !== new Date(target.current).getTime();
  const last = useQuery({
    queryKey: queryKeys.deviceLastMessage(deviceId, target.current),
    queryFn: () => api.get<LastMessage>(`/api/v1/devices/${deviceId}/last-message`, { query: { before: target.current } }),
    enabled: snapAsked,
  });
  const previewRequest = iso ? requestOf(deviceId, target, iso, reason || "-", true) : null;
  const preview = useQuery({
    queryKey: queryKeys.boundaryPreview(deviceId, previewRequest?.body ?? {}),
    queryFn: () => {
      const r = previewRequest!;
      return r.method === "post"
        ? api.post<BoundaryResult>(r.url, { body: r.body })
        : api.patch<BoundaryResult>(r.url, { body: r.body });
    },
    enabled: changed && previewRequest !== null,
    retry: false,
  });
  const move = useMutationToast({
    mutationFn: () => {
      const r = requestOf(deviceId, target, iso!, reason.trim(), false);
      return r.method === "post"
        ? api.post<BoundaryResult>(r.url, { body: r.body })
        : api.patch<BoundaryResult>(r.url, { body: r.body });
    },
    invalidate,
    success: (r: BoundaryResult) =>
      r.attribution_job
        ? t("Boundary moved; {{count}} records are given their project and entity in the background", { count: r.attribution_job.records_total })
        : t("Boundary moved; no record changes hands"),
    onSuccess: onDone,
  });
  // the first press asks the server; once the answer is there it is applied at once
  const snapTo = last.data?.snap_to ?? null;
  const applySnap = () => {
    setSnapAsked(true);
    if (snapTo) setWall(isoToWall(snapTo, zone));
  };
  const refusal = preview.error instanceof ApiError ? preview.error.message : preview.error?.message;
  const plan = changed ? preview.data : null;
  const canSubmit = changed && reason.trim().length > 0 && plan !== undefined && plan !== null && !preview.isError && !move.isPending;
  return (
    <>
      <div className="min-w-0 space-y-4">
        <p className="text-sm text-muted-foreground">
          {t("Now at {{time}}. The neighbouring assignment's edge moves with it, so the timeline keeps no gap and no overlap; the records between the old and the new moment are attributed again to the project and entity of that time. Raw messages never change.", { time: formatTime(target.current) })}
        </p>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <Field label={t("New moment")} htmlFor="boundary-time" hint={t("Wall-clock time in {{zone}}", { zone: zoneLabel(zone) })} error={wall && !iso ? t("Not a date and time") : undefined}>
            <Input id="boundary-time" type="datetime-local" step={1} value={wall} onChange={(e) => setWall(e.target.value)} />
          </Field>
          <Field label={t("Timezone")} htmlFor="boundary-zone">
            <TimezoneSelect id="boundary-zone" value={zone} onChange={(z) => { if (iso) setWall(isoToWall(iso, z)); setZone(z); }} first={[projectZone]} size="sm" />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Button type="button" variant="outline" size="sm" disabled={last.isFetching} onClick={applySnap}>
            {t("Snap to the last uplink before")}
          </Button>
          {snapAsked && last.data && (
            <span className="text-muted-foreground">
              {last.data.time
                ? t("Last message {{time}} via {{source}}; one second after it", { time: formatTime(last.data.time), source: last.data.data_source_name ?? last.data.acquisition_channel ?? "" })
                : t("No live message before that moment in the last 90 days")}
            </span>
          )}
        </div>
        <Field label={t("Reason")} htmlFor="boundary-reason" hint={t("Kept with the change: who moved what, when and why")}>
          <Input id="boundary-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("One second after the last uplink before the handover")} />
        </Field>
        {changed && preview.isPending && <div className="text-sm text-muted-foreground">{t("Working out what would move…")}</div>}
        {changed && refusal && <Callout kind="error">{refusal}</Callout>}
        {plan && !preview.isError && <PlanView plan={plan} />}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>{t("Cancel")}</Button>
        <Button type="button" disabled={!canSubmit} onClick={() => move.mutate()}>
          {target.kind === "both" ? t("Correct both") : t("Move the boundary")}
        </Button>
      </DialogFooter>
    </>
  );
}

function changeText(c: EdgeChange, t: (key: string, options?: Record<string, unknown>) => string): string {
  const name = c.target_name ?? c.target_id.slice(0, 8);
  const old = c.old ? formatTime(c.old) : t("open");
  const kind = c.kind === "project" ? t("Project") : t("Entity");
  return c.edge === "start"
    ? t("{{kind}} {{name}}: start {{old}} to {{new}}", { kind, name, old, new: formatTime(c.new) })
    : t("{{kind}} {{name}}: end {{old}} to {{new}}", { kind, name, old, new: formatTime(c.new) });
}

/** The preview: every row that moves, old and new, the gap note and the window. */
export function PlanView({ plan }: { plan: BoundaryResult }) {
  const { t } = useTranslation();
  if (plan.changes.length === 0)
    return <Callout kind="info">{t("The same moment: nothing changes.")}</Callout>;
  return (
    <div className="space-y-2 text-sm">
      <div className="font-medium">{t("What moves")}</div>
      <ul className="list-disc space-y-1 pl-5">
        {plan.changes.map((c) => <li key={`${c.assignment_id}-${c.edge}`}>{changeText(c, t)}</li>)}
      </ul>
      {plan.gap === "opens" && <Callout kind="warning">{t("No assignment touches this boundary: unassigned time opens there. Records in it belong to no project and no entity.")}</Callout>}
      {plan.gap === "closes" && <Callout kind="info">{t("No assignment touches this boundary: the move takes in time that was unassigned.")}</Callout>}
      {plan.window_from && plan.window_to ? (
        <Callout kind="info">{t("Records between {{from}} and {{to}} are attributed again in the background.", { from: formatTime(plan.window_from), to: formatTime(plan.window_to) })}</Callout>
      ) : null}
    </div>
  );
}
