import { useTranslation } from "react-i18next";
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
import { IconPicker } from "@/components/icons/IconPicker";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";

const KEY = /^[a-z][a-z0-9_]{1,62}$/;

interface FieldSpec<T extends FieldValues, R = unknown> {
  name: Path<T>;
  label: string;
  kind?: "text" | "textarea" | "select" | "icon";
  options?: { value: string; label: string }[];
  /** Options read from the catalogue's own rows (a parent type), given the row being edited. */
  optionsFrom?: (rows: R[], editing: R | null) => { value: string; label: string }[];
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
  fields: FieldSpec<T, R>[];
  defaults: DefaultValues<T>;
  toForm: (row: R) => DefaultValues<T>;
  /** Turns the form's values into the request body when a field needs a translation. */
  toBody?: (values: T) => Record<string, unknown>;
}

/** One list plus dialog for every server-level catalogue: same shape, different fields. */
function CatalogPage<T extends FieldValues, R>({ title, description, path, queryKey, idOf, columns, schema, fields, defaults, toForm, toBody }: CatalogProps<T, R>) {
  const { t } = useTranslation();
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
      const body = Object.fromEntries(Object.entries(toBody ? toBody(values) : values).map(([k, v]) => [k, v === "" ? null : v]));
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
  const remove = useMutationToast({ mutationFn: (row: R) => api.delete(`${path}/${idOf(row)}`), invalidate: [queryKey], success: t("Deleted"), onSuccess: () => setRemoving(null) });
  const allColumns: ColumnDef<R, unknown>[] = [...columns, { id: "actions", header: "", cell: ({ row }) => <Button variant="ghost" size="icon" aria-label={t("Delete")} onClick={(e) => { e.stopPropagation(); setRemoving(row.original); }}><Trash2 className="size-4" /></Button> }];
  const errors = form.formState.errors as Record<string, { message?: string } | undefined>;
  return (
    <>
      <PageHeader title={title} description={description} actions={<Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> {t("New")}</Button>} />
      <Page><DataTable columns={allColumns} data={rows.data?.items} searchable isLoading={rows.isPending} onRowClick={(r) => { setEditing(r); setOpen(true); }} /></Page>
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
                   f.kind === "select" ? <Select value={String(form.watch(f.name) ?? "")} onValueChange={(v) => form.setValue(f.name, v as never, { shouldValidate: true })} disabled={disabled}><SelectTrigger id={id}><SelectValue placeholder={t("Choose")} /></SelectTrigger><SelectContent>{(f.optionsFrom ? f.optionsFrom(rows.data?.items ?? [], editing) : f.options ?? []).map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent></Select> :
                   f.kind === "icon" ? <IconPicker id={id} value={String(form.watch(f.name) ?? "")} onChange={(v) => form.setValue(f.name, v as never, { shouldValidate: true })} /> :
                   <Input id={id} disabled={disabled} {...form.register(f.name)} />}
                </Field>
              );
            })}
            {errors.root?.message && <Callout kind="error">{errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending}>{t("Save")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={removing != null} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${title.toLowerCase().replace(/s$/, "")}`} description={t("Only possible when nothing refers to it.")} confirmLabel={t("Delete")} onConfirm={() => removing && remove.mutate(removing)} pending={remove.isPending} />
    </>
  );
}

const NO_PARENT = "__none__";
const entityTypeSchema = zod.object({ key: zod.string().regex(KEY, "lowercase letters, digits, underscores"), label: zod.string().min(1), parent_id: zod.string(), group_key: zod.enum(["tracked", "infrastructure", "environmental", "equipment", "site"]), icon_key: zod.string().min(1, "Choose an icon"), description: zod.string().optional() });
const entityTypeDefaults: DefaultValues<zod.infer<typeof entityTypeSchema>> = { key: "", label: "", parent_id: NO_PARENT, group_key: "tracked", icon_key: "wildlife.generic", description: "" };
/** Types with sub-types one level deep (decision D166): the standard catalogue seeds
 * Wildlife, People, Vehicles, Infrastructure, Environmental sensors and Equipment with a
 * sub-type per icon; an administrator adds more or a type of their own. */
export function EntityTypesPage() {
  const { t } = useTranslation();
  const types = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const parentLabel = (id: string | null | undefined) => types.data?.items.find((x) => x.id === id)?.label ?? "";
  return (
    <CatalogPage<zod.infer<typeof entityTypeSchema>, EntityType>
      title={t("Entity types")} description={t("Kinds of monitored objects and their sub-types: Wildlife holds Elephant, Vehicles holds 4x4. A project hides what it does not need under its settings.")} path="/api/v1/entity-types" queryKey={queryKeys.entityTypes} idOf={(r) => r.id}
      columns={[{ header: t("Key"), accessorKey: "key" }, { header: t("Label"), accessorKey: "label", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={row.original.icon_key} />{row.original.label}</span> }, { header: t("Type"), id: "parent", accessorFn: (r) => parentLabel(r.parent_id) }, { header: t("Group"), accessorKey: "group_key" }, { header: t("Icon"), accessorKey: "icon_key" }]}
      schema={entityTypeSchema}
      fields={[{ name: "key", label: t("Key"), createOnly: true, hint: t("Stable identifier, for example rhino") }, { name: "label", label: t("Label") }, { name: "parent_id", label: t("Sub-type of"), kind: "select", hint: t("A type on its own, or a sub-type of one of the types"), optionsFrom: (rows, editing) => [{ value: NO_PARENT, label: t("A type on its own") }, ...rows.filter((r) => !r.parent_id && r.id !== editing?.id).sort((a, b) => a.label.localeCompare(b.label)).map((r) => ({ value: r.id, label: r.label }))] }, { name: "group_key", label: t("Group"), kind: "select", options: ["tracked", "infrastructure", "environmental", "equipment", "site"].map((v) => ({ value: v, label: v })) }, { name: "icon_key", label: t("Icon"), kind: "icon" }, { name: "description", label: t("Description"), kind: "textarea" }]}
      defaults={entityTypeDefaults} toForm={(r) => ({ key: r.key, label: r.label, parent_id: r.parent_id ?? NO_PARENT, group_key: r.group_key as never, icon_key: r.icon_key, description: r.description ?? "" })}
      toBody={(v) => ({ ...v, parent_id: v.parent_id === NO_PARENT ? null : v.parent_id })}
    />
  );
}

const deviceTypeSchema = zod.object({ key: zod.string().regex(KEY, "lowercase letters, digits, underscores"), label: zod.string().min(1), driver_key: zod.enum(["generic_json", "opencollar"]), manufacturer: zod.string().optional(), icon_key: zod.string().min(1) });
const deviceTypeDefaults: DefaultValues<zod.infer<typeof deviceTypeSchema>> = { key: "", label: "", driver_key: "opencollar", manufacturer: "", icon_key: "device.opencollar" };
export function DeviceTypesPage() {
  const { t } = useTranslation();
  return (
    <CatalogPage<zod.infer<typeof deviceTypeSchema>, DeviceType>
      title={t("Device types")} description={t("Hardware families and the driver that decodes them")} path="/api/v1/device-types" queryKey={queryKeys.deviceTypes} idOf={(r) => r.id}
      columns={[{ header: t("Key"), accessorKey: "key" }, { header: t("Label"), accessorKey: "label", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={row.original.icon_key} />{row.original.label}</span> }, { header: t("Driver"), accessorKey: "driver_key" }, { header: t("Manufacturer"), accessorKey: "manufacturer" }]}
      schema={deviceTypeSchema}
      fields={[{ name: "key", label: t("Key"), createOnly: true }, { name: "label", label: t("Label") }, { name: "driver_key", label: t("Driver"), kind: "select", options: [{ value: "opencollar", label: t("OpenCollar Edge") }, { value: "generic_json", label: t("Generic JSON") }] }, { name: "manufacturer", label: t("Manufacturer") }, { name: "icon_key", label: t("Icon"), kind: "icon" }]}
      defaults={deviceTypeDefaults} toForm={(r) => ({ key: r.key, label: r.label, driver_key: r.driver_key as never, manufacturer: r.manufacturer ?? "", icon_key: r.icon_key })}
    />
  );
}

const metricSchema = zod.object({ key: zod.string().regex(KEY, "lowercase letters, digits, underscores"), label: zod.string().min(1), unit: zod.string().optional(), value_type: zod.enum(["numeric", "boolean", "text", "json"]), category: zod.string().regex(KEY), description: zod.string().optional() });
const metricDefaults: DefaultValues<zod.infer<typeof metricSchema>> = { key: "", label: "", unit: "", value_type: "numeric", category: "uncategorized", description: "" };
export function MetricsPage() {
  const { t } = useTranslation();
  return (
    <CatalogPage<zod.infer<typeof metricSchema>, Metric>
      title={t("Metrics")} description={t("The registry that gives every measurement a stable key, unit and type")} path="/api/v1/metrics" queryKey={queryKeys.metrics} idOf={(r) => r.key}
      columns={[{ header: t("Key"), accessorKey: "key" }, { header: t("Label"), accessorKey: "label" }, { header: t("Unit"), accessorKey: "unit" }, { header: t("Type"), accessorKey: "value_type" }, { header: t("Category"), accessorKey: "category" }]}
      schema={metricSchema}
      fields={[{ name: "key", label: t("Key"), createOnly: true }, { name: "label", label: t("Label") }, { name: "unit", label: t("Unit"), hint: t("Canonical unit, empty when none") }, { name: "value_type", label: t("Value type"), kind: "select", createOnly: true, options: ["numeric", "boolean", "text", "json"].map((v) => ({ value: v, label: v })) }, { name: "category", label: t("Category") }, { name: "description", label: t("Description"), kind: "textarea" }]}
      defaults={metricDefaults} toForm={(r) => ({ key: r.key, label: r.label, unit: r.unit ?? "", value_type: r.value_type as never, category: r.category, description: r.description ?? "" })}
    />
  );
}
