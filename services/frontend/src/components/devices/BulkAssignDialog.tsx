import { useTranslation } from "react-i18next";
import { useState } from "react";

import { api } from "@/api/client";
import type { BulkAssignResult, Device } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { type BulkStart, BulkStartField } from "@/components/devices/BulkStartField";
import { NameRows } from "@/components/devices/NameRows";
import { EntityTypeSelect } from "@/components/entities/EntityTypeSelect";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProjects } from "@/hooks/useProjects";

/** Devices in no project join one project at once (decision D122): from each device's first
 * data, from now or from a date, optionally with an entity per device named per row
 * (decision D294; the device's name is the default). */
export function BulkAssignDialog({ devices, onClose, onDone }: { devices: Device[]; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const projects = useProjects();
  const [projectId, setProjectId] = useState("");
  const [start, setStart] = useState<BulkStart>("first_data");
  const [entityNames, setEntityNames] = useState<Record<string, string>>({});
  const [entityTypeId, setEntityTypeId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [result, setResult] = useState<BulkAssignResult | null>(null);
  const assign = useMutationToast({
    mutationFn: () =>
      api.post<BulkAssignResult>("/api/v1/devices/bulk-assign", {
        body: {
          device_ids: devices.map((d) => d.id),
          project_id: projectId,
          valid_from: start === "first_data" ? null : start === "now" ? new Date().toISOString() : start,
          entity_type_id: entityTypeId || null,
          group_id: entityTypeId && groupId ? groupId : null,
          names: entityTypeId ? Object.fromEntries(devices.filter((d) => (entityNames[d.id] ?? "").trim() && entityNames[d.id].trim() !== d.name).map((d) => [d.id, entityNames[d.id].trim()])) : null,
        },
      }),
    invalidate: [["devices"], ["projects"]],
    success: (data: BulkAssignResult) => t("{{count}} devices assigned", { count: data.assigned }),
    onSuccess: (data: BulkAssignResult) => { setResult(data); onDone(); if (data.skipped.length === 0) onClose(); },
  });
  const open = devices.length > 0;
  const names = devices.map((d) => d.name);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{t("Assign {{count}} devices to a project", { count: devices.length })}</DialogTitle></DialogHeader>
        {result ? (
          <div className="space-y-2 text-sm">
            <Callout kind="info">{t("{{assigned}} devices assigned and {{entities}} entities created; the records from before now are being given the project in the background for {{jobs}} of them.", { assigned: result.assigned, entities: result.entities, jobs: result.attribution_jobs })}</Callout>
            {result.skipped.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs">{result.skipped.map((s) => <li key={s.device_id}>{s.name ?? s.device_id}: {s.reason}</li>)}</ul>}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{names.slice(0, 5).join(", ")}{names.length > 5 ? ` … (+${names.length - 5})` : ""}</p>
            <Field label={t("Project")} htmlFor="bulk-assign-project">
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setGroupId(""); }}><SelectTrigger id="bulk-assign-project"><SelectValue placeholder={t("Choose")} /></SelectTrigger><SelectContent>{projects.data?.items.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
            </Field>
            <Field label={t("Assignment starts")} htmlFor="bulk-assign-start-choice" hint={start === "first_data" ? t("Each device from the first thing known about it: a record, its identity seen, a log file. Records from then on get the project.") : t("Every device from this moment; earlier records stay without a project.")}>
              <BulkStartField value={start} onChange={setStart} timeZone={projects.data?.items.find((p) => p.id === projectId)?.timezone ?? "UTC"} joined={false} idPrefix="bulk-assign-start" />
            </Field>
            <Field label={t("Also create an entity per device")} htmlFor="bulk-assign-entity-type" hint={projectId ? t("Each device gets an entity of this type with the same name, assigned from the same time, so it shows on the map at once") : t("Needs a project")}>
              <EntityTypeSelect id="bulk-assign-entity-type" projectId={projectId || undefined} value={entityTypeId} onChange={setEntityTypeId} disabled={!projectId} noneLabel={t("No entity")} />
            </Field>
            {projectId && entityTypeId && (
              <NameRows rows={devices} names={entityNames} onChange={(id, name) => setEntityNames((n) => ({ ...n, [id]: name }))} />
            )}
            {projectId && entityTypeId && (
              <Field label={t("Put the entities in a group")} htmlFor="bulk-assign-group">
                <GroupSelect id="bulk-assign-group" projectId={projectId} mode="choice" value={groupId} onChange={setGroupId} />
              </Field>
            )}
          </div>
        )}
        <DialogFooter>
          {result ? <Button onClick={onClose}>{t("Close")}</Button> : <><Button variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button disabled={!projectId || assign.isPending} onClick={() => assign.mutate()}>{t("Assign")}</Button></>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
