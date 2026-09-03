import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { type DefaultValues, type FieldValues, type Path, useForm } from "react-hook-form";
import type { z } from "zod";
import { z as zod } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceType, EntityType, Metric, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Icon } from "@/components/icons/Icon";
import { iconKeys } from "@/components/icons/registry";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";

const KEY = /^[a-z][a-z0-9_]{1,62}$/;

interface FieldSpec<T extends FieldValues> {
  name: Path<T>;
  label: string;
  kind?: "text" | "textarea" | "select" | "icon";
  options?: { value: string; label: string }[];
  hint?: string;
  /** Not editable after creation (primary keys). */
  createOnly?: boolean;
}

interface CatalogProps<T extends FieldValues, R> {
  title: string;
  description: string;
  path: string;
  queryKey: readonly unknown[];
  idOf: (row: R) => string;
  columns: ColumnDef<R, unknown>[];
  schema: z.ZodType<T>;
  fields: FieldSpec<T>[];
  defaults: DefaultValues<T>;
  toForm: (row: R) => DefaultValues<T>;
}

/** One list plus dialog for every server-level catalogue: same shape, different fields. */
function CatalogPage<T extends FieldValues, R>({ title, description, path, queryKey, idOf, columns, schema, fields, defaults, toForm }: CatalogProps<T, R>) {
  const rows = useQuery({ queryKey, queryFn: () => api.get<PageType<R>>(path, { query: { limit: 500 } }) });
  const [editing, setEditing] = useState<R | null>(null);
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState<R | null>(null);
  const form = useForm<T>({ resolver: zodResolver(schema as never), defaultValues: defaults });
  useEffect(() => {
    if (open) form.reset(editing ? toForm(editing) : defaults);
  }, [open, editing, form, defaults, toForm]);
  const save = useMutationToast({
    mutationFn: (values: T) => {
      const body = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v === "" ? null : v]));
      if (editing) {
        for (const f of fields) if (f.createOnly) delete body[f.name];
        return api.patch(`${path}/${idOf(editing)}`, { body });
      }
      return api.post(path, { body });
    },
    invalidate: [queryKey],
    success: editing ? "Saved" : "Created",
    onSuccess: () => setOpen(false),
    onError: (error) => form.setError("root" as never, { message: error.message }),
  });
  const remove = useMutationToast({ mutationFn: (row: R) => api.delete(`${path}/${idOf(row)}`), invalidate: [queryKey], success: "Deleted", onSuccess: () => setRemoving(null) });
  const allColumns: ColumnDef<R, unknown>[] = [...columns, { id: "actions", header: "", cell: ({ row }) => <Button variant="ghost" size="icon" aria-label="Delete" onClick={(e) => { e.stopPropagation(); setRemoving(row.original); }}><Trash2 className="size-4" /></Button> }];
  const errors = form.formState.errors as Record<string, { message?: string } | undefined>;
  return (
    <>
      <PageHeader title={title} description={description} actions={<Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> New</Button>} />
      <Page><DataTable columns={allColumns} data={rows.data?.items} isLoading={rows.isPending} onRowClick={(r) => { setEditing(r); setOpen(true); }} /></Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? `Edit ${title.toLowerCase().replace(/s$/, "")}` : `New ${title.toLowerCase().replace(/s$/, "")}`}</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            {fields.map((f) => {
              const id = `f-${String(f.name)}`;
              const disabled = Boolean(editing && f.createOnly);
              return (
                <Field key={String(f.name)} label={f.label} htmlFor={id} hint={f.hint} error={errors[String(f.name)]?.message}>
                  {f.kind === "textarea" ? <Textarea id={id} rows={2} {...form.register(f.name)} /> :
                   f.kind === "select" ? <Select value={String(form.watch(f.name) ?? "")} onValueChange={(v) => form.setValue(f.name, v as never, { shouldValidate: true })} disabled={disabled}><SelectTrigger id={id}><SelectValue placeholder="Choose" /></SelectTrigger><SelectContent>{f.options?.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent></Select> :
                   f.kind === "icon" ? <Select value={String(form.watch(f.name) ?? "")} onValueChange={(v) => form.setValue(f.name, v as never, { shouldValidate: true })}><SelectTrigger id={id}><SelectValue placeholder="Choose an icon" /></SelectTrigger><SelectContent>{iconKeys.map((k) => <SelectItem key={k} value={k}><span className="inline-flex items-center gap-2"><Icon iconKey={k} className="size-4" />{k}</span></SelectItem>)}</SelectContent></Select> :
                   <Input id={id} disabled={disabled} {...form.register(f.name)} />}
                </Field>
              );
            })}
            {errors.root?.message && <Callout kind="error">{errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={save.isPending}>Save</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={removing != null} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${title.toLowerCase().replace(/s$/, "")}`} description="Only possible when nothing refers to it." confirmLabel="Delete" onConfirm={() => removing && remove.mutate(removing)} pending={remove.isPending} />
    </>
  );
}

const entityTypeSchema = zod.object({ key: zod.string().regex(KEY, "lowercase letters, digits, underscores"), label: zod.string().min(1), group_key: zod.enum(["tracked", "infrastructure", "environmental", "equipment", "site"]), icon_key: zod.string().min(1, "Choose an icon"), description: zod.string().optional() });
const entityTypeDefaults: DefaultValues<zod.infer<typeof entityTypeSchema>> = { key: "", label: "", group_key: "tracked", icon_key: "wildlife.generic", description: "" };
export function EntityTypesPage() {
  return (
    <CatalogPage<zod.infer<typeof entityTypeSchema>, EntityType>
      title="Entity types" description="Kinds of monitored objects: animals, vehicles, gates. Administrators add types without a code change." path="/api/v1/entity-types" queryKey={queryKeys.entityTypes} idOf={(r) => r.id}
      columns={[{ header: "Key", accessorKey: "key" }, { header: "Label", accessorKey: "label", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={row.original.icon_key} />{row.original.label}</span> }, { header: "Group", accessorKey: "group_key" }, { header: "Icon", accessorKey: "icon_key" }]}
      schema={entityTypeSchema}
      fields={[{ name: "key", label: "Key", createOnly: true, hint: "Stable identifier, for example rhino" }, { name: "label", label: "Label" }, { name: "group_key", label: "Group", kind: "select", options: ["tracked", "infrastructure", "environmental", "equipment", "site"].map((v) => ({ value: v, label: v })) }, { name: "icon_key", label: "Icon", kind: "icon" }, { name: "description", label: "Description", kind: "textarea" }]}
      defaults={entityTypeDefaults} toForm={(r) => ({ key: r.key, label: r.label, group_key: r.group_key as never, icon_key: r.icon_key, description: r.description ?? "" })}
    />
  );
}

const deviceTypeSchema = zod.object({ key: zod.string().regex(KEY, "lowercase letters, digits, underscores"), label: zod.string().min(1), driver_key: zod.enum(["generic_json", "opencollar"]), manufacturer: zod.string().optional(), icon_key: zod.string().min(1) });
const deviceTypeDefaults: DefaultValues<zod.infer<typeof deviceTypeSchema>> = { key: "", label: "", driver_key: "opencollar", manufacturer: "", icon_key: "device.opencollar" };
export function DeviceTypesPage() {
  return (
    <CatalogPage<zod.infer<typeof deviceTypeSchema>, DeviceType>
      title="Device types" description="Hardware families and the driver that decodes them" path="/api/v1/device-types" queryKey={queryKeys.deviceTypes} idOf={(r) => r.id}
      columns={[{ header: "Key", accessorKey: "key" }, { header: "Label", accessorKey: "label", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={row.original.icon_key} />{row.original.label}</span> }, { header: "Driver", accessorKey: "driver_key" }, { header: "Manufacturer", accessorKey: "manufacturer" }]}
      schema={deviceTypeSchema}
      fields={[{ name: "key", label: "Key", createOnly: true }, { name: "label", label: "Label" }, { name: "driver_key", label: "Driver", kind: "select", options: [{ value: "opencollar", label: "OpenCollar Edge" }, { value: "generic_json", label: "Generic JSON" }] }, { name: "manufacturer", label: "Manufacturer" }, { name: "icon_key", label: "Icon", kind: "icon" }]}
      defaults={deviceTypeDefaults} toForm={(r) => ({ key: r.key, label: r.label, driver_key: r.driver_key as never, manufacturer: r.manufacturer ?? "", icon_key: r.icon_key })}
    />
  );
}

const metricSchema = zod.object({ key: zod.string().regex(KEY, "lowercase letters, digits, underscores"), label: zod.string().min(1), unit: zod.string().optional(), value_type: zod.enum(["numeric", "boolean", "text", "json"]), category: zod.string().regex(KEY), description: zod.string().optional() });
const metricDefaults: DefaultValues<zod.infer<typeof metricSchema>> = { key: "", label: "", unit: "", value_type: "numeric", category: "uncategorized", description: "" };
export function MetricsPage() {
  return (
    <CatalogPage<zod.infer<typeof metricSchema>, Metric>
      title="Metrics" description="The registry that gives every measurement a stable key, unit and type" path="/api/v1/metrics" queryKey={queryKeys.metrics} idOf={(r) => r.key}
      columns={[{ header: "Key", accessorKey: "key" }, { header: "Label", accessorKey: "label" }, { header: "Unit", accessorKey: "unit" }, { header: "Type", accessorKey: "value_type" }, { header: "Category", accessorKey: "category" }]}
      schema={metricSchema}
      fields={[{ name: "key", label: "Key", createOnly: true }, { name: "label", label: "Label" }, { name: "unit", label: "Unit", hint: "Canonical unit, empty when none" }, { name: "value_type", label: "Value type", kind: "select", createOnly: true, options: ["numeric", "boolean", "text", "json"].map((v) => ({ value: v, label: v })) }, { name: "category", label: "Category" }, { name: "description", label: "Description", kind: "textarea" }]}
      defaults={metricDefaults} toForm={(r) => ({ key: r.key, label: r.label, unit: r.unit ?? "", value_type: r.value_type as never, category: r.category, description: r.description ?? "" })}
    />
  );
}
