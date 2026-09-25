import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import type { MoveDevice, MoveEntity, MoveResult } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { type BulkStart, BulkStartField } from "@/components/devices/BulkStartField";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProjects } from "@/hooks/useProjects";
import { formatTime } from "@/lib/format";

/** What is being moved: devices from a moment each, or entities of one project whole. */
export type MoveSubject =
  | { kind: "devices"; items: { id: string; name: string }[]; currentProjectId?: string | null }
  | { kind: "entities"; projectId: string; items: { id: string; name: string }[] };

/** Move devices or entities to another project with their history (decisions D292, D293):
 * the target, the moment for devices, a group of the target and a reason; the preview the
 * API answers says per device and per entity what comes along and what stays before anything
 * is written, and the same plan is then run. */
export function MoveToProjectDialog({ subject, open, onOpenChange, onMoved }: { subject: MoveSubject; open: boolean; onOpenChange: (open: boolean) => void; onMoved?: (result: MoveResult) => void }) {
  const { t } = useTranslation();
  const count = subject.items.length;
  const title =
    subject.kind === "devices"
      ? count === 1
        ? t("Move {{name}} to another project", { name: subject.items[0].name })
        : t("Move {{count}} devices to another project", { count })
      : count === 1
        ? t("Move {{name}} to another project", { name: subject.items[0].name })
        : t("Move {{count}} entities to another project", { count });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        {open && <MoveForm subject={subject} onDone={(r) => { onOpenChange(false); onMoved?.(r); }} onCancel={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function MoveForm({ subject, onDone, onCancel }: { subject: MoveSubject; onDone: (result: MoveResult) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const projects = useProjects();
  const exclude = subject.kind === "entities" ? subject.projectId : (subject.currentProjectId ?? null);
  const [projectId, setProjectId] = useState("");
  const [start, setStart] = useState<BulkStart>("first_data");
  const [groupId, setGroupId] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<MoveResult | null>(null);
  const target = projects.data?.items.find((p) => p.id === projectId);
  const body = () =>
    subject.kind === "devices"
      ? { url: "/api/v1/devices/move", body: { device_ids: subject.items.map((d) => d.id), project_id: projectId, start, group_id: groupId || null, reason: reason || null } }
      : { url: `/api/v1/projects/${subject.projectId}/entities/move`, body: { entity_ids: subject.items.map((e) => e.id), project_id: projectId, group_id: groupId || null, reason: reason || null } };
  const preview = useQuery({
    queryKey: ["move-preview", subject.kind, subject.items.map((i) => i.id), projectId, start, groupId],
    queryFn: () => {
      const { url, body: b } = body();
      return api.post<MoveResult>(url, { body: { ...b, preview: true } });
    },
    enabled: Boolean(projectId),
  });
  const move = useMutationToast({
    mutationFn: () => {
      const { url, body: b } = body();
      return api.post<MoveResult>(url, { body: b });
    },
    invalidate: [["devices"], ["projects"], ["attention"]],
    success: (r: MoveResult) =>
      r.attribution_jobs > 0
        ? t("{{devices}} devices and {{entities}} entities moved to {{project}}; the records follow in the background", { devices: r.moved_devices, entities: r.moved_entities, project: r.project_name })
        : t("{{devices}} devices and {{entities}} entities moved to {{project}}", { devices: r.moved_devices, entities: r.moved_entities, project: r.project_name }),
    onSuccess: (r: MoveResult) => { setResult(r); if (r.devices.every((d) => !d.skipped) && r.entities.every((e) => e.moves || e.project_id === r.project_id)) onDone(r); },
  });
  const plan = result ?? preview.data;
  const nothing = plan ? plan.moved_devices === 0 && plan.moved_entities === 0 : true;
  if (result) {
    return (
      <>
        <div className="space-y-3 text-sm">
          <Callout kind="info">{t("{{devices}} devices and {{entities}} entities moved; what was skipped is listed below.", { devices: result.moved_devices, entities: result.moved_entities })}</Callout>
          <PlanView plan={result} subject={subject} />
        </div>
        <DialogFooter><Button onClick={() => onDone(result)}>{t("Close")}</Button></DialogFooter>
      </>
    );
  }
  return (
    <>
      <div className="min-w-0 space-y-4">
        <Field label={t("To project")} htmlFor="move-project">
          <Select value={projectId} onValueChange={(v) => { setProjectId(v); setGroupId(""); }}>
            <SelectTrigger id="move-project"><SelectValue placeholder={t("Choose a project")} /></SelectTrigger>
            <SelectContent>{(projects.data?.items ?? []).filter((p) => p.id !== exclude).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        {subject.kind === "devices" && (
          <Field label={t("Move from")} htmlFor="move-start-choice" hint={t("From that moment the records belong to the new project; what lies before stays with the old one. An entity whose whole history moves comes along; one with history before that moment stays, and the device arrives without it.")}>
            <BulkStartField value={start} onChange={setStart} timeZone={target?.timezone ?? "UTC"} idPrefix="move-start" />
          </Field>
        )}
        {subject.kind === "entities" && (
          <p className="text-sm text-muted-foreground">{t("Each entity moves whole, with its history and its devices over the time they tracked it; a device reused on another entity keeps that part here.")}</p>
        )}
        {projectId && (
          <Field label={t("Put the entities in a group")} htmlFor="move-group" hint={t("A group of the target project; the entities leave their old group")}>
            <GroupSelect id="move-group" projectId={projectId} mode="choice" value={groupId} onChange={setGroupId} />
          </Field>
        )}
        <Field label={t("Reason")} htmlFor="move-reason"><Input id="move-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("Kept with the assignment")} /></Field>
        {projectId && preview.isPending && <div className="text-sm text-muted-foreground">{t("Working out what would move…")}</div>}
        {preview.isError && <Callout kind="error">{preview.error.message}</Callout>}
        {plan && <PlanView plan={plan} subject={subject} />}
        {plan && !nothing && <Callout kind="warning">{t("Members of the old project lose the moved records; members of {{project}} gain them. This is not undone by moving back: the history follows again.", { project: plan.project_name })}</Callout>}
        {move.isError && <Callout kind="error">{move.error.message}</Callout>}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>{t("Cancel")}</Button>
        <Button type="button" disabled={!projectId || nothing || preview.isPending || move.isPending} onClick={() => move.mutate()}>{move.isPending ? t("Moving…") : t("Move")}</Button>
      </DialogFooter>
    </>
  );
}

/** The plan as the API says it: one line per device with its moment and its entities, one per
 * entity with whether it moves; the same component before and after the move. */
export function PlanView({ plan, subject }: { plan: MoveResult; subject: MoveSubject }) {
  const { t } = useTranslation();
  const entityLine = (e: MoveEntity) =>
    e.moves ? t("{{name}} comes along", { name: e.name }) : t("{{name}} stays: {{reason}}", { name: e.name, reason: e.reason ?? "" });
  const deviceLine = (d: MoveDevice) => {
    if (d.skipped) return <span className="text-muted-foreground">{t("{{name}}: skipped, {{reason}}", { name: d.name, reason: d.skipped })}</span>;
    const span = d.spans[0];
    const when = span?.end ? t("from {{from}} to {{to}}", { from: formatTime(span.start), to: formatTime(span.end) }) : t("from {{from}} on", { from: formatTime(span?.start) });
    return (
      <>
        <span className="font-medium">{d.name}</span>{" "}
        <span className="text-muted-foreground">{d.project_name ? t("leaves {{project}} {{when}}", { project: d.project_name, when }) : when}</span>
        {(d.entities_along.length > 0 || d.entities_staying.length > 0) && (
          <ul className="ml-4 list-disc text-xs text-muted-foreground">
            {d.entities_along.map((e) => <li key={e.entity_id}>{entityLine(e)}</li>)}
            {d.entities_staying.map((e) => <li key={e.entity_id}>{entityLine(e)}</li>)}
          </ul>
        )}
      </>
    );
  };
  return (
    <div className="space-y-2 rounded-md border p-3 text-sm" aria-label={t("What moves")}>
      <div className="font-medium">{t("{{devices}} devices and {{entities}} entities move to {{project}}", { devices: plan.moved_devices, entities: plan.moved_entities, project: plan.project_name })}</div>
      {subject.kind === "entities" && (
        <ul className="space-y-1">{plan.entities.map((e) => <li key={e.entity_id}>{e.moves ? t("{{name}} moves", { name: e.name }) : <span className="text-muted-foreground">{t("{{name}}: skipped, {{reason}}", { name: e.name, reason: e.reason ?? "" })}</span>}</li>)}</ul>
      )}
      {plan.devices.length > 0 && (
        <ul className="space-y-1">{plan.devices.map((d) => <li key={d.device_id}>{deviceLine(d)}</li>)}</ul>
      )}
    </div>
  );
}
