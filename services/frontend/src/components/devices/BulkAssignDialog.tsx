import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { BulkAssignResult, Device, EntityType, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProjects } from "@/hooks/useProjects";

/** Devices in no project join one project at once (decision D122): from each device's first
 * data or from now, optionally with an entity per device named as the device. */
export function BulkAssignDialog({ devices, onClose, onDone }: { devices: Device[]; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const projects = useProjects();
  const entityTypes = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const [projectId, setProjectId] = useState("");
  const [start, setStart] = useState<"first_data" | "now">("first_data");
  const [entityTypeId, setEntityTypeId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [result, setResult] = useState<BulkAssignResult | null>(null);
  const assign = useMutationToast({
    mutationFn: () =>
      api.post<BulkAssignResult>("/api/v1/devices/bulk-assign", {
        body: {
          device_ids: devices.map((d) => d.id),
          project_id: projectId,
          valid_from: start === "now" ? new Date().toISOString() : null,
          entity_type_id: entityTypeId || null,
          group_id: entityTypeId && groupId ? groupId : null,
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
      <DialogContent>
        <DialogHeader><DialogTitle>{t("Assign {{count}} devices to a project", { count: devices.length })}</DialogTitle></DialogHeader>
        {result ? (
          <div className="space-y-2 text-sm">
            <Callout kind="info">{t("{{assigned}} devices assigned and {{entities}} entities created; {{positions}} positions and {{measurements}} measurements from before now carry the project.", { assigned: result.assigned, entities: result.entities, positions: result.reattributed.positions, measurements: result.reattributed.measurements })}</Callout>
            {result.skipped.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs">{result.skipped.map((s) => <li key={s.device_id}>{s.name ?? s.device_id}: {s.reason}</li>)}</ul>}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{names.slice(0, 5).join(", ")}{names.length > 5 ? ` … (+${names.length - 5})` : ""}</p>
            <Field label={t("Project")} htmlFor="bulk-assign-project">
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setGroupId(""); }}><SelectTrigger id="bulk-assign-project"><SelectValue placeholder={t("Choose")} /></SelectTrigger><SelectContent>{projects.data?.items.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
            </Field>
            <Field label={t("Assignment starts")} htmlFor="bulk-assign-start" hint={start === "first_data" ? t("Each device from the first thing known about it: a record, its identity seen, a log file. Records from then on get the project.") : t("Every device from this moment; earlier records stay without a project.")}>
              <Select value={start} onValueChange={(v) => setStart(v as "first_data" | "now")}><SelectTrigger id="bulk-assign-start"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="first_data">{t("At each device's first data")}</SelectItem><SelectItem value="now">{t("Now")}</SelectItem></SelectContent></Select>
            </Field>
            <Field label={t("Also create an entity per device")} htmlFor="bulk-assign-entity-type" hint={projectId ? t("Each device gets an entity of this type with the same name, assigned from the same time, so it shows on the map at once") : t("Needs a project")}>
              <Select value={entityTypeId || "none"} onValueChange={(v) => setEntityTypeId(v === "none" ? "" : v)} disabled={!projectId}><SelectTrigger id="bulk-assign-entity-type"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{t("No entity")}</SelectItem>{entityTypes.data?.items.map((et) => <SelectItem key={et.id} value={et.id}>{et.label}</SelectItem>)}</SelectContent></Select>
            </Field>
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
