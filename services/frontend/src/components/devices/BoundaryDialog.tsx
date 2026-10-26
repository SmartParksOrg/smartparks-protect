import { useTranslation } from "react-i18next";
import { type QueryKey, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { BoundaryResult, LastMessage } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { type Counterpart, type Edge, isoToWall, type Kind, wallToIso } from "@/lib/assignments";
import { formatTime } from "@/lib/format";
import { zoneLabel } from "@/lib/timezones";

export interface NamedCounterpart extends Counterpart {
  name: string;
}

/** The row the dialog edits, with the row of the other list that shares each of its edges
 * (a transfer that changed the project and the entity at once, decision D355). */
export interface BoundaryTarget {
  kind: Kind;
  assignmentId: string;
  name: string;
  validFrom: string;
  validTo: string | null;
  shared: { start?: NamedCounterpart; end?: NamedCounterpart };
}

/** Edit the dates of one assignment after the fact (decisions D355 to D358, simplified at
 * Tim's word on 2026-10-26): From and, for a row that ended, To, as wall-clock times in the
 * project's timezone, "Use the last uplink" beside From, a tick to move the row of the other
 * list that changed at the same moment along, and an optional note. The neighbouring row's
 * edge follows on the server; one line under the fields says what else moves, and a refusal
 * (future, empty, crossing, outside the project) shows in the reader's words. */
export function BoundaryDialog({ deviceId, target, timeZone, open, onOpenChange, invalidate }: {
  deviceId: string;
  target: BoundaryTarget | null;
  timeZone: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invalidate: QueryKey[];
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {target?.kind === "project" ? t("Edit the project assignment") : t("Edit the entity assignment")}
          </DialogTitle>
        </DialogHeader>
        {open && target && (
          <BoundaryForm deviceId={deviceId} target={target} timeZone={timeZone} invalidate={invalidate} onDone={() => onOpenChange(false)} onCancel={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  );
}

interface Request {
  url: string;
  method: "post" | "patch";
  body: Record<string, unknown>;
}

/** The calls an edit takes: an edge moved together with its counterpart goes through the
 * combined correction, the rest of the row's edges through one PATCH. */
function requestsOf(
  deviceId: string,
  target: BoundaryTarget,
  edits: Record<Edge, string | null>,
  also: Record<Edge, boolean>,
  note: string,
  preview: boolean,
): Request[] {
  const out: Request[] = [];
  const own: Record<string, unknown> = {};
  for (const edge of ["start", "end"] as const) {
    const iso = edits[edge];
    if (!iso) continue;
    const other = target.shared[edge];
    if (other && also[edge]) {
      out.push({
        url: `/api/v1/devices/${deviceId}/assignments/correct`,
        method: "post",
        body: {
          project_assignment_id: target.kind === "project" ? target.assignmentId : other.assignmentId,
          entity_assignment_id: target.kind === "entity" ? target.assignmentId : other.assignmentId,
          project_edge: target.kind === "project" ? edge : other.edge,
          entity_edge: target.kind === "entity" ? edge : other.edge,
          instant: iso,
          reason: note,
          preview,
        },
      });
    } else own[edge === "start" ? "valid_from" : "valid_to"] = iso;
  }
  if (Object.keys(own).length > 0)
    out.push({
      url: `/api/v1/devices/${deviceId}/${target.kind}-assignments/${target.assignmentId}/boundary`,
      method: "patch",
      body: { ...own, reason: note, preview },
    });
  return out;
}

async function sendAll(requests: Request[]): Promise<BoundaryResult[]> {
  const out: BoundaryResult[] = [];
  for (const r of requests)
    out.push(r.method === "post" ? await api.post<BoundaryResult>(r.url, { body: r.body }) : await api.patch<BoundaryResult>(r.url, { body: r.body }));
  return out;
}

// the date fields hold whole seconds, a row's instant may carry milliseconds
const seconds = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);
const differs = (a: string, b: string) => seconds(a) !== seconds(b);

/** Mounted while the dialog is open, so every opening starts from the row's own dates. */
function BoundaryForm({ deviceId, target, timeZone, invalidate, onDone, onCancel }: {
  deviceId: string;
  target: BoundaryTarget;
  timeZone: string;
  invalidate: QueryKey[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [from, setFrom] = useState(() => isoToWall(target.validFrom, timeZone));
  const [to, setTo] = useState(() => (target.validTo ? isoToWall(target.validTo, timeZone) : ""));
  const [note, setNote] = useState("");
  const [also, setAlso] = useState<Record<Edge, boolean>>({ start: true, end: true });
  const [uplink, setUplink] = useState<{ fetching: boolean; none: boolean }>({ fetching: false, none: false });
  const queryClient = useQueryClient();
  const fromIso = wallToIso(from, timeZone);
  const toIso = target.validTo ? wallToIso(to, timeZone) : null;
  const fromChanged = fromIso !== null && differs(fromIso, target.validFrom);
  const toChanged = target.validTo !== null && toIso !== null && differs(toIso, target.validTo);
  const valid = fromIso !== null && (target.validTo === null || toIso !== null);
  const changed = fromChanged || toChanged;
  const edits: Record<Edge, string | null> = { start: fromChanged ? fromIso : null, end: toChanged ? toIso : null };
  const requests = changed && valid ? requestsOf(deviceId, target, edits, also, note.trim(), true) : [];
  const preview = useQuery({
    queryKey: queryKeys.boundaryPreview(deviceId, { requests: requests.map((r) => r.body) }),
    queryFn: () => sendAll(requests),
    enabled: requests.length > 0,
    retry: false,
  });
  // the device's last live message before the row's start, taken as From one second later
  const useUplink = async () => {
    setUplink({ fetching: true, none: false });
    try {
      const last = await queryClient.fetchQuery({
        queryKey: queryKeys.deviceLastMessage(deviceId, target.validFrom),
        queryFn: () => api.get<LastMessage>(`/api/v1/devices/${deviceId}/last-message`, { query: { before: target.validFrom } }),
      });
      if (last.snap_to) setFrom(isoToWall(last.snap_to, timeZone));
      setUplink({ fetching: false, none: !last.snap_to });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setUplink({ fetching: false, none: false });
    }
  };
  const move = useMutationToast({
    mutationFn: () => sendAll(requestsOf(deviceId, target, edits, also, note.trim(), false)),
    invalidate,
    success: (results: BoundaryResult[]) => {
      const job = results.map((r) => r.attribution_job).find((j) => j);
      return job
        ? t("Dates changed; {{count}} records get their project and entity again in the background", { count: job.records_total })
        : t("Dates changed; no record changes hands");
    },
    onSuccess: onDone,
  });
  const refusal = preview.error instanceof ApiError ? preview.error.message : preview.error?.message;
  const plans = requests.length > 0 && !preview.isError ? preview.data : undefined;
  // what the person asked for is the row and the counterparts ticked; the rest is the neighbours
  const chosen = new Set([
    target.assignmentId,
    ...(fromChanged && also.start && target.shared.start ? [target.shared.start.assignmentId] : []),
    ...(toChanged && also.end && target.shared.end ? [target.shared.end.assignmentId] : []),
  ]);
  const others = plans?.flatMap((p) => p.changes).filter((c) => !chosen.has(c.assignment_id)) ?? [];
  const gap = plans?.map((p) => p.gap).find((g) => g) ?? null;
  const canSubmit = requests.length > 0 && plans !== undefined && !move.isPending;
  const alsoLine = (edge: Edge) => {
    const other = target.shared[edge];
    if (!other) return null;
    return (
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-4 accent-primary"
          checked={also[edge]}
          onChange={(e) => setAlso({ ...also, [edge]: e.target.checked })}
        />
        <span>
          {other.kind === "entity"
            ? t("Also move the entity assignment {{name}}, which changed at the same moment", { name: other.name })
            : t("Also move the project assignment {{name}}, which changed at the same moment", { name: other.name })}
        </span>
      </label>
    );
  };
  return (
    <>
      <div className="min-w-0 space-y-4">
        <p className="text-sm text-muted-foreground">{target.name}</p>
        <Field label={t("From")} htmlFor="boundary-from" hint={t("Wall-clock time in {{zone}}", { zone: zoneLabel(timeZone) })} error={from && fromIso === null ? t("Not a date and time") : undefined}>
          <div className="flex flex-wrap items-center gap-2">
            <Input id="boundary-from" className="w-auto" type="datetime-local" step={1} value={from} onChange={(e) => setFrom(e.target.value)} />
            <Button type="button" variant="ghost" size="sm" disabled={uplink.fetching} onClick={useUplink}>
              {t("Use the last uplink")}
            </Button>
          </div>
        </Field>
        {uplink.none && (
          <p className="text-sm text-muted-foreground">{t("No live message before that moment in the last 90 days")}</p>
        )}
        {fromChanged && alsoLine("start")}
        {target.validTo && (
          <Field label={t("To")} htmlFor="boundary-to" error={to && toIso === null ? t("Not a date and time") : undefined}>
            <Input id="boundary-to" className="w-auto" type="datetime-local" step={1} value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
        )}
        {toChanged && alsoLine("end")}
        <Field label={t("Note")} htmlFor="boundary-note" hint={t("Optional; kept with the change")}>
          <Input id="boundary-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {requests.length > 0 && preview.isPending && <div className="text-sm text-muted-foreground">{t("Checking…")}</div>}
        {refusal && <Callout kind="error">{refusal}</Callout>}
        {plans && (others.length > 0 || gap) && (
          <div className="space-y-1 text-sm text-muted-foreground">
            {others.map((c) => (
              <div key={`${c.assignment_id}-${c.edge}`}>
                {c.edge === "end"
                  ? t("{{name}} then ends at {{time}}", { name: c.target_name ?? c.target_id.slice(0, 8), time: formatTime(c.new) })
                  : t("{{name}} then starts at {{time}}", { name: c.target_name ?? c.target_id.slice(0, 8), time: formatTime(c.new) })}
              </div>
            ))}
            {gap === "opens" && <div>{t("Nothing else touches this moment: the time in between belongs to no project and no entity.")}</div>}
            {gap === "closes" && <div>{t("Nothing else touches this moment: the change takes in time that was unassigned.")}</div>}
          </div>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>{t("Cancel")}</Button>
        <Button type="button" disabled={!canSubmit} onClick={() => move.mutate()}>{t("Save")}</Button>
      </DialogFooter>
    </>
  );
}
