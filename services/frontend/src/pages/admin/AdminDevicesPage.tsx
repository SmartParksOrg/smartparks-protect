import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataSource, Device, DeviceDetail, DeviceType, Entity, Page as PageType, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const deviceSchema = z.object({ name: z.string().min(1).max(200), device_type_id: z.string().min(1, "Choose a type"), serial_number: z.string().optional(), status: z.enum(["active", "inventory", "repair", "retired"]), firmware_version: z.string().optional() });
type DeviceValues = z.infer<typeof deviceSchema>;

function nowIso(): string {
  return new Date().toISOString().slice(0, 16);
}

/** Device management: create, identities, project assignment, handover, entity assignment. */
function ManageDevice({ deviceId, onClose }: { deviceId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const detail = useQuery({ queryKey: queryKeys.device(deviceId), queryFn: () => api.get<DeviceDetail>(`/api/v1/devices/${deviceId}`) });
  const sources = useQuery({ queryKey: queryKeys.dataSources, queryFn: () => api.get<PageType<DataSource>>("/api/v1/data-sources", { query: { limit: 500 } }) });
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const [identity, setIdentity] = useState({ data_source_id: "", external_id: "" });
  const [assignment, setAssignment] = useState({ project_id: "", valid_from: nowIso() });
  const [handover, setHandover] = useState({ project_id: "", effective_at: nowIso(), reason: "" });
  const [entityAssignment, setEntityAssignment] = useState({ project_id: "", entity_id: "", valid_from: nowIso() });
  const entities = useQuery({ queryKey: queryKeys.entities(entityAssignment.project_id), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${entityAssignment.project_id}/entities`, { query: { limit: 500 } }), enabled: Boolean(entityAssignment.project_id) });
  const invalidate = [queryKeys.device(deviceId), queryKeys.devices({})];
  const addIdentity = useMutationToast({ mutationFn: () => api.post(`/api/v1/devices/${deviceId}/identities`, { body: identity }), invalidate, success: t("Identity linked"), onSuccess: () => setIdentity({ data_source_id: "", external_id: "" }) });
  const assign = useMutationToast({ mutationFn: () => api.post(`/api/v1/devices/${deviceId}/project-assignments`, { body: { project_id: assignment.project_id, valid_from: new Date(assignment.valid_from).toISOString() } }), invalidate, success: t("Assigned to project") });
  const doHandover = useMutationToast({ mutationFn: () => api.post(`/api/v1/devices/${deviceId}/handover`, { body: { project_id: handover.project_id, effective_at: new Date(handover.effective_at).toISOString(), reason: handover.reason || null } }), invalidate, success: t("Device handed over") });
  const assignEntity = useMutationToast({ mutationFn: () => api.post(`/api/v1/projects/${entityAssignment.project_id}/entity-assignments`, { body: { device_id: deviceId, entity_id: entityAssignment.entity_id, valid_from: new Date(entityAssignment.valid_from).toISOString() } }), invalidate: [...invalidate, queryKeys.currentState(entityAssignment.project_id)], success: t("Assigned to entity") });
  const d = detail.data;
  const currentProject = d?.project_assignments.find((a) => !a.valid_to);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>{d?.name ?? "Device"}</DialogTitle><DialogDescription>{t("Identities, project ownership over time, entity assignment")}</DialogDescription></DialogHeader>
        {d && (
          <Tabs defaultValue="identities">
            <TabsList><TabsTrigger value="identities">{t("Identities")}</TabsTrigger><TabsTrigger value="project">{t("Project")}</TabsTrigger><TabsTrigger value="entity">{t("Entity")}</TabsTrigger></TabsList>
            <TabsContent value="identities" className="space-y-3">
              <ul className="text-sm">{d.external_identities.map((i) => <li key={i.id} className="font-mono">{i.external_id} <span className="font-sans text-muted-foreground">{t("on {{source}}", { source: sources.data?.items.find((s) => s.id === i.data_source_id)?.name })}</span></li>)}{d.external_identities.length === 0 && <li className="text-muted-foreground">{t("None yet.")}</li>}</ul>
              <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Select value={identity.data_source_id} onValueChange={(v) => setIdentity({ ...identity, data_source_id: v })}><SelectTrigger><SelectValue placeholder={t("Data source")} /></SelectTrigger><SelectContent>{sources.data?.items.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent></Select>
                <Input placeholder={t("DevEUI or external id")} className="font-mono" value={identity.external_id} onChange={(e) => setIdentity({ ...identity, external_id: e.target.value.trim().toUpperCase() })} />
                <Button disabled={!identity.data_source_id || !identity.external_id || addIdentity.isPending} onClick={() => addIdentity.mutate()}>{t("Link")}</Button>
              </div>
            </TabsContent>
            <TabsContent value="project" className="space-y-3">
              <ul className="text-sm">{d.project_assignments.map((a) => <li key={a.id}>{t("{{name}}: {{from}} to {{to}}", { name: projects.data?.items.find((p) => p.id === a.project_id)?.name ?? a.project_id.slice(0, 8), from: formatTime(a.valid_from), to: a.valid_to ? formatTime(a.valid_to) : t("now") })}</li>)}{d.project_assignments.length === 0 && <li className="text-muted-foreground">{t("Not assigned to a project.")}</li>}</ul>
              {currentProject ? (
                <Card><CardHeader><CardTitle className="text-sm">{t("Hand over to another project")}</CardTitle></CardHeader><CardContent className="grid gap-2 sm:grid-cols-2">
                  <Select value={handover.project_id} onValueChange={(v) => setHandover({ ...handover, project_id: v })}><SelectTrigger><SelectValue placeholder={t("Destination project")} /></SelectTrigger><SelectContent>{projects.data?.items.filter((p) => p.id !== currentProject.project_id).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
                  <Input type="datetime-local" value={handover.effective_at} onChange={(e) => setHandover({ ...handover, effective_at: e.target.value })} aria-label={t("Effective at")} />
                  <Input placeholder={t("Reason")} value={handover.reason} onChange={(e) => setHandover({ ...handover, reason: e.target.value })} />
                  <Button disabled={!handover.project_id || doHandover.isPending} onClick={() => doHandover.mutate()}>{t("Hand over")}</Button>
                  <p className="text-xs text-muted-foreground sm:col-span-2">{t("Closes the current project and entity assignment at the effective time and opens the new one. History is untouched.")}</p>
                </CardContent></Card>
              ) : (
                <Card><CardHeader><CardTitle className="text-sm">{t("Assign to a project")}</CardTitle></CardHeader><CardContent className="grid gap-2 sm:grid-cols-3">
                  <Select value={assignment.project_id} onValueChange={(v) => setAssignment({ ...assignment, project_id: v })}><SelectTrigger><SelectValue placeholder={t("Project")} /></SelectTrigger><SelectContent>{projects.data?.items.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
                  <Input type="datetime-local" value={assignment.valid_from} onChange={(e) => setAssignment({ ...assignment, valid_from: e.target.value })} aria-label={t("Valid from")} />
                  <Button disabled={!assignment.project_id || assign.isPending} onClick={() => assign.mutate()}>{t("Assign")}</Button>
                </CardContent></Card>
              )}
            </TabsContent>
            <TabsContent value="entity" className="space-y-3">
              <ul className="text-sm">{d.entity_assignments.map((a) => <li key={a.id}>{t("Entity {{id}}: {{from}} to {{to}}", { id: a.entity_id.slice(0, 8), from: formatTime(a.valid_from), to: a.valid_to ? formatTime(a.valid_to) : t("now") })}</li>)}{d.entity_assignments.length === 0 && <li className="text-muted-foreground">{t("Not assigned to an entity.")}</li>}</ul>
              <div className="grid gap-2 sm:grid-cols-2">
                <Select value={entityAssignment.project_id} onValueChange={(v) => setEntityAssignment({ ...entityAssignment, project_id: v, entity_id: "" })}><SelectTrigger><SelectValue placeholder={t("Project")} /></SelectTrigger><SelectContent>{d.project_assignments.map((a) => a.project_id).filter((v, i, arr) => arr.indexOf(v) === i).map((pid) => <SelectItem key={pid} value={pid}>{projects.data?.items.find((p) => p.id === pid)?.name ?? pid}</SelectItem>)}</SelectContent></Select>
                <Select value={entityAssignment.entity_id} onValueChange={(v) => setEntityAssignment({ ...entityAssignment, entity_id: v })} disabled={!entityAssignment.project_id}><SelectTrigger><SelectValue placeholder={t("Entity")} /></SelectTrigger><SelectContent>{entities.data?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}</SelectContent></Select>
                <Input type="datetime-local" value={entityAssignment.valid_from} onChange={(e) => setEntityAssignment({ ...entityAssignment, valid_from: e.target.value })} aria-label={t("Valid from")} />
                <Button disabled={!entityAssignment.entity_id || assignEntity.isPending} onClick={() => assignEntity.mutate()}>{t("Assign to entity")}</Button>
                <p className="text-xs text-muted-foreground sm:col-span-2">{t("The device must belong to the project at the start time. An open assignment of this device to another entity is rejected; end it first.")}</p>
              </div>
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function AdminDevicesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const managing = params.get("device");
  const [q, setQ] = useState("");
  const devices = useQuery({ queryKey: queryKeys.devices({ q }), queryFn: () => api.get<PageType<Device>>("/api/v1/devices", { query: { q: q || undefined, limit: 500 } }), placeholderData: (previous) => previous });
  const types = useQuery({ queryKey: queryKeys.deviceTypes, queryFn: () => api.get<PageType<DeviceType>>("/api/v1/device-types", { query: { limit: 500 } }) });
  const typeById = new Map(types.data?.items.map((t) => [t.id, t]));
  const [open, setOpen] = useState(false);
  const form = useForm<DeviceValues>({ resolver: zodResolver(deviceSchema), defaultValues: { name: "", device_type_id: "", serial_number: "", status: "active", firmware_version: "" } });
  useEffect(() => { if (open) form.reset({ name: "", device_type_id: "", serial_number: "", status: "active", firmware_version: "" }); }, [open, form]);
  const create = useMutationToast({
    mutationFn: (values: DeviceValues) => api.post<Device>("/api/v1/devices", { body: { ...values, serial_number: values.serial_number || null, firmware_version: values.firmware_version || null } }),
    invalidate: [queryKeys.devices({})],
    success: t("Device created"),
    onSuccess: (device) => { setOpen(false); setParams({ device: device.id }); },
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const importCsv = useMutationToast({
    mutationFn: (file: File) => { const body = new FormData(); body.append("file", file); return api.post<{ created: number }>("/api/v1/devices/import", { body }); },
    invalidate: [queryKeys.devices({})],
    success: (r) => `${r.created} devices imported`,
    onError: (error) => toast.error(error.message),
  });
  const columns: ColumnDef<Device, unknown>[] = [
    { header: t("Name"), accessorKey: "name", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={typeById.get(row.original.device_type_id)?.icon_key} />{row.original.name}</span> },
    { header: t("Type"), accessorFn: (d) => typeById.get(d.device_type_id)?.label ?? "" },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Serial"), accessorKey: "serial_number" },
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { id: "actions", header: "", cell: ({ row }) => <div className="flex gap-1"><Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); setParams({ device: row.original.id }); }}>{t("Manage")}</Button><Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); void navigate(`/admin/devices/${row.original.id}`); }}>{t("Details")}</Button></div> },
  ];
  return (
    <>
      <PageHeader title={t("Devices")} description={t("Every device on the server, whichever project owns it")} actions={<>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent"><Upload className="size-4" /> {t("Import CSV")}<input type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv.mutate(f); e.target.value = ""; }} /></label>
        <Button onClick={() => setOpen(true)}><Plus className="size-4" /> {t("New device")}</Button>
      </>} />
      <Page>
        <Callout kind="info">{t("CSV columns: device_name, external_identifier, device_type, datasource, project, effective_from (ISO 8601 with offset), entity (optional). All rows or none.")}</Callout>
        <DataTable columns={columns} data={devices.data?.items} searchable onSearchChange={setQ} footer={devices.data?.next_cursor ? t("Only the first 500 rows are shown. Search to find the rest.") : undefined} isLoading={devices.isPending} onRowClick={(d) => setParams({ device: d.id })} />
      </Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("New device")}</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <Field label={t("Name")} htmlFor="d-name" error={form.formState.errors.name?.message}><Input id="d-name" {...form.register("name")} /></Field>
            <Field label={t("Type")} htmlFor="d-type" error={form.formState.errors.device_type_id?.message}>
              <Select value={form.watch("device_type_id")} onValueChange={(v) => form.setValue("device_type_id", v, { shouldValidate: true })}><SelectTrigger id="d-type"><SelectValue placeholder={t("Choose")} /></SelectTrigger><SelectContent>{types.data?.items.map((t) => <SelectItem key={t.id} value={t.id}>{t.label} ({t.driver_key})</SelectItem>)}</SelectContent></Select>
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Serial number")} htmlFor="d-serial"><Input id="d-serial" {...form.register("serial_number")} /></Field>
              <Field label={t("Status")} htmlFor="d-status"><Select value={form.watch("status")} onValueChange={(v) => form.setValue("status", v as DeviceValues["status"])}><SelectTrigger id="d-status"><SelectValue /></SelectTrigger><SelectContent>{["active", "inventory", "repair", "retired"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent></Select></Field>
            </div>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("Cancel")}</Button><Button type="submit" disabled={create.isPending}>{t("Create")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {managing && <ManageDevice deviceId={managing} onClose={() => setParams({})} />}
    </>
  );
}
