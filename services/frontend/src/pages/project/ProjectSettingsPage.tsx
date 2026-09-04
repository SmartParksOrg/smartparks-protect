import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AuditEntry, Project } from "@/api/types";
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
  const { projectId = "" } = useParams();
  const project = useQuery({ queryKey: queryKeys.project(projectId), queryFn: () => api.get<Project>(`/api/v1/projects/${projectId}`) });
  const audit = useQuery({ queryKey: queryKeys.audit(projectId), queryFn: () => api.get<AuditEntry[]>(`/api/v1/projects/${projectId}/audit`, { query: { limit: 50 } }) });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", description: "", timezone: "UTC", curation_requires_approval: false } });
  useEffect(() => {
    if (project.data) form.reset({ name: project.data.name, description: project.data.description ?? "", timezone: project.data.timezone, curation_requires_approval: Boolean((project.data.settings as Record<string, unknown>)?.curation_requires_approval) });
  }, [project.data, form]);
  const save = useMutationToast({
    mutationFn: (values: Values) => api.patch<Project>(`/api/v1/projects/${projectId}`, { body: { name: values.name, timezone: values.timezone, description: values.description || null, settings: { ...(project.data?.settings ?? {}), curation_requires_approval: values.curation_requires_approval } } }),
    invalidate: [queryKeys.project(projectId), queryKeys.projects],
    success: "Project saved",
    onError: (error) => form.setError("root", { message: error.message }),
  });
  return (
    <>
      <PageHeader title="Project settings" />
      <Page>
        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent>
            <form className="max-w-lg space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
              <Field label="Name" htmlFor="name" error={form.formState.errors.name?.message}><Input id="name" {...form.register("name")} /></Field>
              <Field label="Description" htmlFor="description"><Textarea id="description" rows={3} {...form.register("description")} /></Field>
              <Field label="Timezone" htmlFor="timezone" hint="IANA name, used for display and exports" error={form.formState.errors.timezone?.message}><Input id="timezone" {...form.register("timezone")} /></Field>
              <div className="flex items-start gap-2"><Switch id="curation-approval" checked={form.watch("curation_requires_approval")} onCheckedChange={(v) => form.setValue("curation_requires_approval", v)} /><label htmlFor="curation-approval" className="text-sm">Corrections need approval<span className="block text-xs text-muted-foreground">Data corrections and bulk jobs stay pending until a second person with the approve permission accepts them.</span></label></div>
              {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
              <Button type="submit" disabled={save.isPending}>Save</Button>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Recent changes</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {audit.data?.map((e) => <li key={e.id} className="flex flex-wrap gap-2 py-1.5"><span className="text-muted-foreground">{formatTime(e.time)}</span><span className="font-medium">{e.action}</span><span className="text-muted-foreground">{e.object_type} {e.object_id?.slice(0, 8)}</span></li>)}
              {audit.data?.length === 0 && <li className="text-muted-foreground">No changes recorded yet.</li>}
            </ul>
          </CardContent>
        </Card>
      </Page>
    </>
  );
}
