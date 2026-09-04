import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Building2, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Organization, Page as PageType, Project, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const schema = z.object({ name: z.string().min(1).max(200), slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,98}$/, "Lowercase letters, digits and dashes"), timezone: z.string().min(1), organization_id: z.string() });
type Values = z.infer<typeof schema>;

const ALL = "all";
const NONE = "none";

export function AdminProjectsPage() {
  const { t } = useTranslation();
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const organizations = useQuery({ queryKey: queryKeys.organizations, queryFn: () => api.get<Organization[]>("/api/v1/admin/organizations") });
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<string>(ALL);
  const organizationById = useMemo(() => new Map(organizations.data?.map((o) => [o.id, o])), [organizations.data]);
  const visible = useMemo(() => {
    const items = projects.data?.items ?? [];
    if (filter === ALL) return items;
    if (filter === NONE) return items.filter((p) => !p.organization_id);
    return items.filter((p) => p.organization_id === filter);
  }, [projects.data, filter]);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", slug: "", timezone: "UTC", organization_id: NONE } });
  const create = useMutationToast({
    mutationFn: (values: Values) => api.post<Project>("/api/v1/projects", { body: { ...values, organization_id: values.organization_id === NONE ? null : values.organization_id } }),
    invalidate: [queryKeys.projects],
    success: t("Project created"),
    onSuccess: (project) => { setOpen(false); form.reset(); void navigate(`/projects/${project.id}/map`); },
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const columns: ColumnDef<ProjectWithRole, unknown>[] = [
    { header: t("Name"), accessorKey: "name" },
    { header: t("Organization"), accessorFn: (p) => organizationById.get(p.organization_id ?? "")?.name ?? "" },
    { header: t("Slug"), accessorKey: "slug" },
    { header: t("Timezone"), accessorKey: "timezone" },
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Archived"), accessorKey: "archived_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) },
  ];
  return (
    <>
      <PageHeader title={t("Projects")} actions={<Button onClick={() => setOpen(true)}><Plus className="size-4" /> {t("New project")}</Button>} />
      <Page>
        <div className="flex items-center gap-2">
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="w-64" aria-label={t("Filter by organization")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("All organizations")}</SelectItem>
              <SelectItem value={NONE}>{t("Without organization")}</SelectItem>
              {organizations.data?.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <DataTable columns={columns} data={visible} isLoading={projects.isPending} onRowClick={(p) => navigate(`/projects/${p.id}/admin/settings`)} />
        <OrganizationsCard organizations={organizations.data ?? []} />
      </Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("New project")}</DialogTitle></DialogHeader>
          <form className="space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <Field label={t("Name")} htmlFor="p-name" error={form.formState.errors.name?.message}><Input id="p-name" {...form.register("name", { onChange: (e) => { if (!form.formState.dirtyFields.slug) form.setValue("slug", String(e.target.value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); } })} /></Field>
            <Field label={t("Slug")} htmlFor="p-slug" error={form.formState.errors.slug?.message} hint={t("Short identifier used in URLs and exports")}><Input id="p-slug" {...form.register("slug")} /></Field>
            <Field label={t("Timezone")} htmlFor="p-tz" error={form.formState.errors.timezone?.message}><Input id="p-tz" {...form.register("timezone")} /></Field>
            <Field label={t("Organization")} htmlFor="p-org" hint={t("A grouping for the admin pages, not a permission boundary")}>
              <Select value={form.watch("organization_id")} onValueChange={(v) => form.setValue("organization_id", v)}>
                <SelectTrigger id="p-org"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t("None")}</SelectItem>
                  {organizations.data?.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("Cancel")}</Button><Button type="submit" disabled={create.isPending}>{t("Create")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

const organizationSchema = z.object({ name: z.string().min(1).max(200), slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,98}$/, "Lowercase letters, digits and dashes") });
type OrganizationValues = z.infer<typeof organizationSchema>;

/** Organizations group projects for server admins (decision D92); they carry no rights. */
function OrganizationsCard({ organizations }: { organizations: Organization[] }) {
  const { t } = useTranslation();
  const [removing, setRemoving] = useState<Organization | null>(null);
  const form = useForm<OrganizationValues>({ resolver: zodResolver(organizationSchema), defaultValues: { name: "", slug: "" } });
  const create = useMutationToast({
    mutationFn: (values: OrganizationValues) => api.post<Organization>("/api/v1/admin/organizations", { body: values }),
    invalidate: [queryKeys.organizations],
    success: t("Organization created"),
    onSuccess: () => form.reset(),
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const remove = useMutationToast({
    mutationFn: (organization: Organization) => api.delete(`/api/v1/admin/organizations/${organization.id}`),
    invalidate: [queryKeys.organizations, queryKeys.projects],
    success: t("Organization removed; its projects keep running without one"),
    onSuccess: () => setRemoving(null),
  });
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Building2 className="size-4" /> {t("Organizations")}</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">{t("A grouping of projects for these admin pages. Membership and permissions stay per project.")}</p>
        {organizations.length > 0 && (
          <ul className="divide-y rounded-md border">
            {organizations.map((o) => (
              <li key={o.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span><span className="font-medium">{o.name}</span> <span className="text-muted-foreground">{o.slug}</span></span>
                <span className="flex items-center gap-3">
                  <span className="text-muted-foreground">{o.project_count === 1 ? "1 project" : `${o.project_count} projects`}</span>
                  <Button variant="ghost" size="icon" aria-label={t("Remove organization")} onClick={() => setRemoving(o)}><Trash2 className="size-4" /></Button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <form className="flex flex-wrap items-end gap-2" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <Field label={t("Name")} htmlFor="org-name" error={form.formState.errors.name?.message}><Input id="org-name" className="w-56" {...form.register("name", { onChange: (e) => { if (!form.formState.dirtyFields.slug) form.setValue("slug", String(e.target.value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); } })} /></Field>
          <Field label={t("Slug")} htmlFor="org-slug" error={form.formState.errors.slug?.message}><Input id="org-slug" className="w-48" {...form.register("slug")} /></Field>
          <Button type="submit" disabled={create.isPending}><Plus className="size-4" /> {t("Add organization")}</Button>
        </form>
        {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
      </CardContent>
      <ConfirmDialog open={removing !== null} onOpenChange={(open) => { if (!open) setRemoving(null); }} title={t("Remove organization")} description={removing ? `${removing.name} is removed; its ${removing.project_count} project(s) stay and lose the grouping.` : ""} confirmLabel={t("Remove")} onConfirm={() => { if (removing) remove.mutate(removing); }} />
    </Card>
  );
}
