import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Page as PageType, Project, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const schema = z.object({ name: z.string().min(1).max(200), slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,98}$/, "Lowercase letters, digits and dashes"), timezone: z.string().min(1) });
type Values = z.infer<typeof schema>;

export function AdminProjectsPage() {
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", slug: "", timezone: "UTC" } });
  const create = useMutationToast({
    mutationFn: (values: Values) => api.post<Project>("/api/v1/projects", { body: values }),
    invalidate: [queryKeys.projects],
    success: "Project created",
    onSuccess: (project) => { setOpen(false); form.reset(); void navigate(`/projects/${project.id}/map`); },
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const columns: ColumnDef<ProjectWithRole, unknown>[] = [
    { header: "Name", accessorKey: "name" },
    { header: "Slug", accessorKey: "slug" },
    { header: "Timezone", accessorKey: "timezone" },
    { header: "Created", accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: "Archived", accessorKey: "archived_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) },
  ];
  return (
    <>
      <PageHeader title="Projects" actions={<Button onClick={() => setOpen(true)}><Plus className="size-4" /> New project</Button>} />
      <Page><DataTable columns={columns} data={projects.data?.items} isLoading={projects.isPending} onRowClick={(p) => navigate(`/projects/${p.id}/admin/settings`)} /></Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>New project</DialogTitle></DialogHeader>
          <form className="space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <Field label="Name" htmlFor="p-name" error={form.formState.errors.name?.message}><Input id="p-name" {...form.register("name", { onChange: (e) => { if (!form.formState.dirtyFields.slug) form.setValue("slug", String(e.target.value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); } })} /></Field>
            <Field label="Slug" htmlFor="p-slug" error={form.formState.errors.slug?.message} hint="Short identifier used in URLs and exports"><Input id="p-slug" {...form.register("slug")} /></Field>
            <Field label="Timezone" htmlFor="p-tz" error={form.formState.errors.timezone?.message}><Input id="p-tz" {...form.register("timezone")} /></Field>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={create.isPending}>Create</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
