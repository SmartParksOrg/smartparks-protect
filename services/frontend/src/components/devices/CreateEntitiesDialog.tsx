import { useTranslation } from "react-i18next";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityAssignmentsBulkResult } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { type BulkStart, BulkStartField } from "@/components/devices/BulkStartField";
import { NameRows } from "@/components/devices/NameRows";
import { EntityTypeSelect } from "@/components/entities/EntityTypeSelect";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProject } from "@/hooks/useProjects";

/** An entity per selected device of the project (decision D294): a name per row, one type
 * and sub-type, a group, and the start each device tracks its entity from. */
export function CreateEntitiesDialog({ projectId, devices, onClose, onDone }: { projectId: string; devices: { id: string; name: string }[]; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const { project } = useProject(projectId);
  const [names, setNames] = useState<Record<string, string>>({});
  const [typeId, setTypeId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [start, setStart] = useState<BulkStart>("first_data");
  const [result, setResult] = useState<EntityAssignmentsBulkResult | null>(null);
  const create = useMutationToast({
    mutationFn: () =>
      api.post<EntityAssignmentsBulkResult>(`/api/v1/projects/${projectId}/entity-assignments/bulk`, {
        body: {
          items: devices.map((d) => ({ device_id: d.id, name: (names[d.id] ?? d.name).trim() || d.name })),
          entity_type_id: typeId,
          group_id: groupId || null,
          start,
        },
      }),
    invalidate: [["devices"], queryKeys.entities(projectId), queryKeys.entityAssignments(projectId), queryKeys.currentState(projectId), queryKeys.groups(projectId)],
    success: (r: EntityAssignmentsBulkResult) =>
      r.attribution_jobs > 0
        ? t("{{count}} entities created; the earlier records are being given their entity in the background", { count: r.created })
        : t("{{count}} entities created", { count: r.created }),
    onSuccess: (r: EntityAssignmentsBulkResult) => { setResult(r); onDone(); if (r.skipped.length === 0) onClose(); },
  });
  const open = devices.length > 0;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{t("Create an entity for each of {{count}} devices", { count: devices.length })}</DialogTitle></DialogHeader>
        {result ? (
          <div className="space-y-2 text-sm">
            <Callout kind="info">{t("{{count}} entities created", { count: result.created })}</Callout>
            {result.skipped.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs">{result.skipped.map((s) => <li key={s.device_id}>{s.name}: {s.reason}</li>)}</ul>}
          </div>
        ) : (
          <div className="space-y-4">
            <NameRows rows={devices} names={names} onChange={(id, name) => setNames((n) => ({ ...n, [id]: name }))} />
            <Field label={t("Type")} htmlFor="create-entities-type" hint={t("The kind of thing, then the species or model; the icon follows the choice")}>
              <EntityTypeSelect id="create-entities-type" projectId={projectId} value={typeId} onChange={setTypeId} />
            </Field>
            <Field label={t("Group")} htmlFor="create-entities-group"><GroupSelect id="create-entities-group" projectId={projectId} mode="choice" value={groupId} onChange={setGroupId} /></Field>
            <Field label={t("Tracking since")} htmlFor="create-entities-start-choice" hint={t("Records before the chosen start stay without entity; a device that tracks an entity from then on is skipped.")}>
              <BulkStartField value={start} onChange={setStart} timeZone={project?.timezone ?? "UTC"} idPrefix="create-entities-start" />
            </Field>
            {create.isError && <Callout kind="error">{create.error.message}</Callout>}
          </div>
        )}
        <DialogFooter>
          {result ? <Button onClick={onClose}>{t("Close")}</Button> : <><Button variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button disabled={!typeId || create.isPending} onClick={() => create.mutate()}>{create.isPending ? t("Creating…") : t("Create")}</Button></>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
