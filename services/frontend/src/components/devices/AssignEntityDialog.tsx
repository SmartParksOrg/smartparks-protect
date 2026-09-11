import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceDataSpan, DeviceDetail, Entity, EntityAssignment, EntityType, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { AssignmentStartField } from "@/components/devices/AssignmentStartField";
import { EntityTypeSelect } from "@/components/entities/EntityTypeSelect";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProject } from "@/hooks/useProjects";

/** Assign a device to an entity from the device's side (decision D170): one of the project's
 * entities, or a new one made on the spot, from a start the guided field offers (D103). The
 * entity page's dialog is the same thing seen from the entity. */
export function AssignEntityDialog({ projectId, device, open, onOpenChange }: { projectId: string; device: DeviceDetail; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{t("Assign {{name}} to an entity", { name: device.name })}</DialogTitle></DialogHeader>
        {open && <AssignEntityForm projectId={projectId} device={device} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

/** Mounted while the dialog is open, so every opening starts with nothing chosen. */
function AssignEntityForm({ projectId, device, onDone }: { projectId: string; device: DeviceDetail; onDone: () => void }) {
  const { t } = useTranslation();
  const { project } = useProject(projectId);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [q, setQ] = useState("");
  const [entityId, setEntityId] = useState("");
  const [name, setName] = useState("");
  const [typeId, setTypeId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [validFrom, setValidFrom] = useState(() => new Date().toISOString());
  const entities = useQuery({
    queryKey: [...queryKeys.entities(projectId), "assignable", q],
    queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 200, ...(q.trim() ? { q: q.trim() } : {}) } }),
  });
  const types = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const iconOf = (e: Entity) => e.icon_key ?? types.data?.items.find((x) => x.id === e.entity_type_id)?.icon_key;
  const assignments = useQuery({
    queryKey: queryKeys.entityAssignments(projectId),
    queryFn: () => api.get<PageType<EntityAssignment>>(`/api/v1/projects/${projectId}/entity-assignments`, { query: { limit: 500 } }),
  });
  const trackedBy = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of assignments.data?.items ?? []) if (!a.valid_to && a.device_name) map.set(a.entity_id, a.device_name);
    return map;
  }, [assignments.data]);
  const span = useQuery({ queryKey: queryKeys.deviceSpan(device.id), queryFn: () => api.get<DeviceDataSpan>(`/api/v1/devices/${device.id}/data-span`) });
  const joinedAt = device.project_assignments.find((a) => a.project_id === projectId && !a.valid_to)?.valid_from ?? null;
  const ready = mode === "existing" ? Boolean(entityId) : Boolean(name.trim() && typeId);
  const assign = useMutationToast({
    mutationFn: () =>
      api.post<EntityAssignment>(`/api/v1/projects/${projectId}/entity-assignments`, {
        body: {
          device_id: device.id,
          valid_from: validFrom,
          ...(mode === "existing" ? { entity_id: entityId } : { new_entity: { name: name.trim(), entity_type_id: typeId, group_id: groupId || null } }),
        },
      }),
    invalidate: [queryKeys.device(device.id), queryKeys.deviceSpan(device.id), queryKeys.entities(projectId), queryKeys.entityAssignments(projectId), queryKeys.currentState(projectId), queryKeys.devices({ projectId, unassigned: true })],
    success: (a: EntityAssignment) => t("{{device}} now tracks {{entity}}", { device: device.name, entity: a.entity_name ?? name }),
    onSuccess: onDone,
  });
  return (
    <>
      <div className="min-w-0 space-y-4">
        <Tabs value={mode} onValueChange={(v) => setMode(v as "existing" | "new")}>
          <TabsList>
            <TabsTrigger value="existing">{t("An entity of the project")}</TabsTrigger>
            <TabsTrigger value="new">{t("A new entity")}</TabsTrigger>
          </TabsList>
        </Tabs>
        {mode === "existing" ? (
          <>
            <Field label={t("Entity")} htmlFor="assign-entity-search" hint={t("An entity that another device tracks today keeps that device as well; release it on the entity page if it should not.")}>
              <Input id="assign-entity-search" placeholder={t("Search by name")} value={q} onChange={(e) => setQ(e.target.value)} />
            </Field>
            <div className="max-h-56 overflow-y-auto rounded-md border" role="listbox" aria-label={t("Entities")}>
              {entities.isPending && <div className="p-3 text-sm text-muted-foreground">{t("Loading entities…")}</div>}
              {entities.data && entities.data.items.length === 0 && <div className="p-3 text-sm text-muted-foreground">{q ? t("No entity matches.") : t("No entities yet: make a new one.")}</div>}
              {entities.data?.items.map((e) => (
                <button key={e.id} type="button" role="option" aria-selected={e.id === entityId} className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted ${e.id === entityId ? "bg-muted" : ""}`} onClick={() => setEntityId(e.id)}>
                  <Icon iconKey={iconOf(e)} className="size-4 shrink-0 text-primary" />
                  <span className="min-w-0 flex-1 truncate font-medium">{e.name}</span>
                  {trackedBy.get(e.id) && <span className="shrink-0 text-xs text-muted-foreground">{t("tracked by {{device}}", { device: trackedBy.get(e.id) })}</span>}
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <Field label={t("Name")} htmlFor="new-entity-name"><Input id="new-entity-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={device.name} /></Field>
            <Field label={t("Type")} htmlFor="new-entity-type" hint={t("The kind of thing, then the species or model; the icon follows the choice")}>
              <EntityTypeSelect id="new-entity-type" projectId={projectId} value={typeId} onChange={setTypeId} />
            </Field>
            <Field label={t("Group")} htmlFor="new-entity-group"><GroupSelect id="new-entity-group" projectId={projectId} mode="choice" value={groupId} onChange={setGroupId} /></Field>
          </>
        )}
        {ready && (
          <Field label={t("Tracking since")} htmlFor="entity-choice" hint={t("Records before the chosen start stay without entity; the entity appears on the map with its first record from the start on.")}>
            {span.isPending ? <div className="text-sm text-muted-foreground">{t("Looking up the device's data…")}</div> : <AssignmentStartField idPrefix="entity" span={span.data} joinedAt={joinedAt} timeZone={project?.timezone ?? "UTC"} onChange={setValidFrom} />}
          </Field>
        )}
        {assign.isError && <Callout kind="error">{assign.error.message}</Callout>}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>{t("Cancel")}</Button>
        <Button type="button" disabled={!ready || span.isPending || assign.isPending} onClick={() => assign.mutate()}>{assign.isPending ? t("Assigning…") : t("Assign")}</Button>
      </DialogFooter>
    </>
  );
}
