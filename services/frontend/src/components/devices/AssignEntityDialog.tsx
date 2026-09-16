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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProject, useProjects } from "@/hooks/useProjects";

/** Assign a device from the device's side (decisions D170, D192): to one of the project's
 * entities or a new one made on the spot, from a start the guided field offers (D103). A device
 * no project holds yet is asked for the project first, in the same dialog, and both
 * assignments are made in one go; with `entity` off the dialog assigns the project alone. The
 * entity page's dialog is the same thing seen from the entity. */
export function AssignEntityDialog({ projectId, device, open, onOpenChange, entity = true }: { projectId: string | null; device: DeviceDetail; open: boolean; onOpenChange: (open: boolean) => void; entity?: boolean }) {
  const { t } = useTranslation();
  const title = entity
    ? projectId
      ? t("Assign {{name}} to an entity", { name: device.name })
      : t("Assign {{name}} to a project and an entity", { name: device.name })
    : t("Assign {{name}} to a project", { name: device.name });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        {open && <AssignEntityForm projectId={projectId} device={device} entity={entity} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

/** Mounted while the dialog is open, so every opening starts with nothing chosen. */
function AssignEntityForm({ projectId: fixedProjectId, device, entity: entityStep, onDone }: { projectId: string | null; device: DeviceDetail; entity: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const projects = useProjects();
  const [chosenProjectId, setChosenProjectId] = useState("");
  const [projectValidFrom, setProjectValidFrom] = useState(() => new Date().toISOString());
  const needProject = fixedProjectId === null;
  const projectId = fixedProjectId ?? chosenProjectId;
  const { project } = useProject(projectId || undefined);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [q, setQ] = useState("");
  const [entityId, setEntityId] = useState("");
  const [name, setName] = useState(device.name); // the device's name is the usual entity name; overwrite it if not
  const [typeId, setTypeId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [validFrom, setValidFrom] = useState(() => new Date().toISOString());
  const [attempted, setAttempted] = useState(false);
  const entities = useQuery({
    queryKey: [...queryKeys.entities(projectId), "assignable", q],
    queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 200, ...(q.trim() ? { q: q.trim() } : {}) } }),
    enabled: Boolean(projectId) && entityStep,
  });
  const types = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const iconOf = (e: Entity) => e.icon_key ?? types.data?.items.find((x) => x.id === e.entity_type_id)?.icon_key;
  const assignments = useQuery({
    queryKey: queryKeys.entityAssignments(projectId),
    queryFn: () => api.get<PageType<EntityAssignment>>(`/api/v1/projects/${projectId}/entity-assignments`, { query: { limit: 500 } }),
    enabled: Boolean(projectId) && entityStep,
  });
  const trackedBy = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of assignments.data?.items ?? []) if (!a.valid_to && a.device_name) map.set(a.entity_id, a.device_name);
    return map;
  }, [assignments.data]);
  const span = useQuery({ queryKey: queryKeys.deviceSpan(device.id), queryFn: () => api.get<DeviceDataSpan>(`/api/v1/devices/${device.id}/data-span`) });
  // the project the device is in, or the one chosen here: the entity's start is bounded by it
  const joinedAt = needProject ? projectValidFrom : (device.project_assignments.find((a) => a.project_id === projectId && !a.valid_to)?.valid_from ?? null);
  // What still stops the assignment; shown at the field once Assign was pressed, never a silently disabled button.
  const missingEntity = mode === "existing" ? (entityId ? null : "entity") : !name.trim() ? "name" : !typeId ? "type" : null;
  const missing = needProject && !projectId ? "project" : entityStep ? missingEntity : null;
  const ready = missing === null;
  const assign = useMutationToast({
    mutationFn: async () => {
      // the project first when the device has none; should the entity step then fail, the
      // device is in the project and the dialog, reopened, starts from there
      if (needProject) {
        await api.post(`/api/v1/devices/${device.id}/project-assignments`, { body: { project_id: projectId, valid_from: projectValidFrom } });
      }
      if (!entityStep) return null;
      return api.post<EntityAssignment>(`/api/v1/projects/${projectId}/entity-assignments`, {
        body: {
          device_id: device.id,
          valid_from: validFrom,
          ...(mode === "existing" ? { entity_id: entityId } : { new_entity: { name: name.trim(), entity_type_id: typeId, group_id: groupId || null } }),
        },
      });
    },
    invalidate: [queryKeys.device(device.id), queryKeys.deviceSpan(device.id), queryKeys.attributionJobs(device.id), queryKeys.devices({}), queryKeys.entities(projectId), queryKeys.entityAssignments(projectId), queryKeys.currentState(projectId), queryKeys.devices({ projectId, unassigned: true })],
    // the records already inside the range follow through a job the page shows (decision D206)
    success: (a: EntityAssignment | null) =>
      a
        ? a.attribution_job
          ? t("{{device}} now tracks {{entity}}; {{count}} earlier records are being given the entity in the background", { device: device.name, entity: a.entity_name ?? name, count: a.attribution_job.records_total })
          : t("{{device}} now tracks {{entity}}", { device: device.name, entity: a.entity_name ?? name })
        : t("{{device}} is in {{project}} now", { device: device.name, project: project?.name ?? "" }),
    onSuccess: onDone,
  });
  const projectStep = needProject && (
    <>
      <Field label={t("Project")} htmlFor="assign-project" hint={t("The device belongs to no project yet; its data is attributed to the project from the start chosen below.")} error={attempted && missing === "project" ? t("Choose a project") : undefined}>
        <Select value={chosenProjectId} onValueChange={setChosenProjectId}>
          <SelectTrigger id="assign-project"><SelectValue placeholder={t("Choose a project")} /></SelectTrigger>
          <SelectContent>
            {(projects.data?.items ?? []).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </Field>
      {projectId && (
        <Field label={t("In the project since")} htmlFor="project-choice" hint={t("Records before the chosen start stay without project.")}>
          {span.isPending ? <div className="text-sm text-muted-foreground">{t("Looking up the device's data…")}</div> : <AssignmentStartField idPrefix="project" span={span.data} joinedAt={null} timeZone={project?.timezone ?? "UTC"} onChange={setProjectValidFrom} />}
        </Field>
      )}
    </>
  );
  if (!entityStep) {
    return (
      <>
        <div className="min-w-0 space-y-4">
          {projectStep}
          {assign.isError && <Callout kind="error">{assign.error.message}</Callout>}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>{t("Cancel")}</Button>
          <Button type="button" disabled={span.isPending || assign.isPending} onClick={() => (ready ? assign.mutate() : setAttempted(true))}>{assign.isPending ? t("Assigning…") : t("Assign")}</Button>
        </DialogFooter>
      </>
    );
  }
  return (
    <>
      <div className="min-w-0 space-y-4">
        {projectStep}
        {needProject && projectId && <div className="border-t" />}
        <Tabs value={mode} onValueChange={(v) => setMode(v as "existing" | "new")}>
          <TabsList>
            <TabsTrigger value="existing">{t("An entity of the project")}</TabsTrigger>
            <TabsTrigger value="new">{t("A new entity")}</TabsTrigger>
          </TabsList>
        </Tabs>
        {mode === "existing" ? (
          <>
            <Field label={t("Entity")} htmlFor="assign-entity-search" hint={t("An entity that another device tracks today keeps that device as well; release it on the entity page if it should not.")} error={attempted && missing === "entity" ? t("Pick an entity from the list") : undefined}>
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
            <Field label={t("Name")} htmlFor="new-entity-name" error={attempted && missing === "name" ? t("Give the entity a name") : undefined}><Input id="new-entity-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label={t("Type")} htmlFor="new-entity-type" hint={t("The kind of thing, then the species or model; the icon follows the choice")} error={attempted && missing === "type" ? t("Choose a type") : undefined}>
              <EntityTypeSelect id="new-entity-type" projectId={projectId} value={typeId} onChange={setTypeId} />
            </Field>
            <Field label={t("Group")} htmlFor="new-entity-group"><GroupSelect id="new-entity-group" projectId={projectId} mode="choice" value={groupId} onChange={setGroupId} /></Field>
          </>
        )}
        {ready && projectId && (
          <Field label={t("Tracking since")} htmlFor="entity-choice" hint={t("Records before the chosen start stay without entity; the entity appears on the map with its first record from the start on.")}>
            {span.isPending ? <div className="text-sm text-muted-foreground">{t("Looking up the device's data…")}</div> : <AssignmentStartField idPrefix="entity" span={span.data} joinedAt={joinedAt} timeZone={project?.timezone ?? "UTC"} onChange={setValidFrom} />}
          </Field>
        )}
        {assign.isError && <Callout kind="error">{assign.error.message}</Callout>}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>{t("Cancel")}</Button>
        <Button type="button" disabled={span.isPending || assign.isPending} onClick={() => (ready ? assign.mutate() : setAttempted(true))}>{assign.isPending ? t("Assigning…") : t("Assign")}</Button>
      </DialogFooter>
    </>
  );
}
