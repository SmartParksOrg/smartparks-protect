import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AuditEntry, Organization, Project, ProjectIcon } from "@/api/types";
import { isServerAdmin, useAuthStore } from "@/stores/auth";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Icon } from "@/components/icons/Icon";
import { useIconStore } from "@/stores/icons";
import { toast } from "sonner";
import { useRef, useState } from "react";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const schema = z.object({ name: z.string().min(1).max(200), description: z.string().optional(), timezone: z.string().min(1), curation_requires_approval: z.boolean() });
type Values = z.infer<typeof schema>;

export function ProjectSettingsPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const project = useQuery({ queryKey: queryKeys.project(projectId), queryFn: () => api.get<Project>(`/api/v1/projects/${projectId}`) });
  const audit = useQuery({ queryKey: queryKeys.audit(projectId), queryFn: () => api.get<AuditEntry[]>(`/api/v1/projects/${projectId}/audit`, { query: { limit: 50 } }) });
  const serverAdmin = isServerAdmin(useAuthStore((s) => s.user));
  const organizations = useQuery({ queryKey: queryKeys.organizations, queryFn: () => api.get<Organization[]>("/api/v1/admin/organizations"), enabled: serverAdmin });
  const move = useMutationToast({
    mutationFn: (organizationId: string | null) => api.patch<Project>(`/api/v1/projects/${projectId}`, { body: { organization_id: organizationId } }),
    invalidate: [queryKeys.project(projectId), queryKeys.projects, queryKeys.organizations],
    success: t("Organization updated"),
  });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", description: "", timezone: "UTC", curation_requires_approval: false } });
  useEffect(() => {
    if (project.data) form.reset({ name: project.data.name, description: project.data.description ?? "", timezone: project.data.timezone, curation_requires_approval: Boolean((project.data.settings as Record<string, unknown>)?.curation_requires_approval) });
  }, [project.data, form]);
  const save = useMutationToast({
    mutationFn: (values: Values) => api.patch<Project>(`/api/v1/projects/${projectId}`, { body: { name: values.name, timezone: values.timezone, description: values.description || null, settings: { ...(project.data?.settings ?? {}), curation_requires_approval: values.curation_requires_approval } } }),
    invalidate: [queryKeys.project(projectId), queryKeys.projects],
    success: t("Project saved"),
    onError: (error) => form.setError("root", { message: error.message }),
  });
  return (
    <>
      <PageHeader title={t("Project settings")} />
      <Page>
        <Card>
          <CardHeader><CardTitle>{t("Details")}</CardTitle></CardHeader>
          <CardContent>
            <form className="max-w-lg space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
              <Field label={t("Name")} htmlFor="name" error={form.formState.errors.name?.message}><Input id="name" {...form.register("name")} /></Field>
              <Field label={t("Description")} htmlFor="description"><Textarea id="description" rows={3} {...form.register("description")} /></Field>
              <Field label={t("Timezone")} htmlFor="timezone" hint={t("IANA name, used for display and exports")} error={form.formState.errors.timezone?.message}><Input id="timezone" {...form.register("timezone")} /></Field>
              <div className="flex items-start gap-2"><Switch id="curation-approval" checked={form.watch("curation_requires_approval")} onCheckedChange={(v) => form.setValue("curation_requires_approval", v)} /><label htmlFor="curation-approval" className="text-sm">{t("Corrections need approval")}<span className="block text-xs text-muted-foreground">{t("Data corrections and bulk jobs stay pending until a second person with the approve permission accepts them.")}</span></label></div>
              {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
              <Button type="submit" disabled={save.isPending}>{t("Save")}</Button>
            </form>
            {serverAdmin && (
              <div className="mt-6 max-w-lg">
                <Field label={t("Organization")} htmlFor="organization" hint={t("A grouping for the server admin pages; only server admins change it")}>
                  <Select value={project.data?.organization_id ?? "none"} onValueChange={(v) => move.mutate(v === "none" ? null : v)}>
                    <SelectTrigger id="organization"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t("None")}</SelectItem>
                      {organizations.data?.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            )}
          </CardContent>
        </Card>
        <IconsCard projectId={projectId} />
        <Card>
          <CardHeader><CardTitle>{t("Recent changes")}</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {audit.data?.map((e) => <li key={e.id} className="flex flex-wrap gap-2 py-1.5"><span className="text-muted-foreground">{formatTime(e.time)}</span><span className="font-medium">{e.action}</span><span className="text-muted-foreground">{e.object_type} {e.object_id?.slice(0, 8)}</span></li>)}
              {audit.data?.length === 0 && <li className="text-muted-foreground">{t("No changes recorded yet.")}</li>}
            </ul>
          </CardContent>
        </Card>
      </Page>
    </>
  );
}

/** The project's own SVG icons (architecture 24.6): uploaded here, usable as icon keys on
 * entity types, device types and entities as `project.<slug>`. */
function IconsCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const icons = useQuery({ queryKey: queryKeys.projectIcons(projectId), queryFn: () => api.get<ProjectIcon[]>(`/api/v1/projects/${projectId}/icons`) });
  const reload = () => { useIconStore.setState({ projectId: null }); void useIconStore.getState().load(projectId); };
  const upload = useMutationToast({
    mutationFn: async (file: File) => api.post<ProjectIcon>(`/api/v1/projects/${projectId}/icons`, { body: { label: label.trim() || file.name.replace(/\.svg$/i, ""), svg: await file.text() } }),
    invalidate: [queryKeys.projectIcons(projectId)],
    onSuccess: (icon) => { toast.success(`Icon ${icon.key} saved`); setLabel(""); reload(); },
  });
  const remove = useMutationToast({ mutationFn: (key: string) => api.delete<void>(`/api/v1/projects/${projectId}/icons/${key}`), invalidate: [queryKeys.projectIcons(projectId)], success: t("Icon removed"), onSuccess: reload });
  return (
    <Card>
      <CardHeader><CardTitle>{t("Custom icons")}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">{t("Small SVG files (up to 64 KB, no scripts or external references) become icon keys `project.name` for this project's entity types, device types and entities. Colour follows the text colour when the SVG uses currentColor.")}</p>
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t("Label")} htmlFor="icon-label"><Input id="icon-label" className="w-56" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("Pangolin")} /></Field>
          <input ref={input} type="file" accept=".svg,image/svg+xml" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
          <Button variant="outline" disabled={upload.isPending} onClick={() => input.current?.click()}>{upload.isPending ? "Uploading…" : "Upload SVG"}</Button>
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {icons.data?.map((i) => (
            <li key={i.id} className="flex items-center gap-3 rounded-md border p-2">
              <span className="inline-flex size-8 items-center justify-center [&>svg]:size-full" dangerouslySetInnerHTML={{ __html: i.svg }} />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{i.label}</span><span className="block truncate font-mono text-xs text-muted-foreground">{i.key}</span></span>
              <Icon iconKey={i.key} className="size-5 text-muted-foreground" />
              <Button variant="ghost" size="sm" onClick={() => remove.mutate(i.key)}>{t("Remove")}</Button>
            </li>
          ))}
          {icons.data?.length === 0 && <li className="text-muted-foreground">{t("No custom icons yet.")}</li>}
        </ul>
      </CardContent>
    </Card>
  );
}
