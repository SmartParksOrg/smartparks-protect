import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Copy, KeyRound, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataSource, Page as PageType, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const ADAPTERS = [
  { key: "chirpstack", label: "ChirpStack", config: { mqtt_host: "chirpstack-mosquitto", mqtt_port: 1883, api_url: "http://chirpstack-rest-api:8090", web_url: "http://localhost:8080", tenant_id: "" }, credentials: { api_token: "" } },
  { key: "generic_http", label: "Generic HTTP webhook", config: { external_id_field: "device_id", event_type_field: "type", time_field: "received_at" }, credentials: {} },
  { key: "generic_mqtt", label: "Generic MQTT broker", config: { host: "", port: 1883, topics: ["devices/#"], topic_template: "devices/{external_id}/+" }, credentials: { username: "", password: "" } },
];

const schema = z.object({
  name: z.string().min(1).max(200),
  adapter_key: z.string().min(1),
  enabled: z.boolean(),
  config: z.string().refine((v) => { try { return typeof JSON.parse(v) === "object"; } catch { return false; } }, "Must be a JSON object"),
  credentials: z.string().refine((v) => { if (!v.trim()) return true; try { return typeof JSON.parse(v) === "object"; } catch { return false; } }, "Must be a JSON object or empty"),
  project_ids: z.array(z.string()),
});
type Values = z.infer<typeof schema>;

/** The capability inspector shows what the adapter supports for this account (architecture 8.2). */
function Capabilities({ source }: { source: DataSource }) {
  const entries = Object.entries(source.capabilities as Record<string, boolean>);
  if (entries.length === 0) return null;
  return <div className="flex flex-wrap gap-1">{entries.map(([k, v]) => <span key={k} className={`rounded px-1.5 py-0.5 text-[11px] ${v ? "bg-brand-green-light/40" : "bg-muted text-muted-foreground line-through"}`}>{k}</span>)}</div>;
}

export function DataSourcesPage() {
  const sources = useQuery({ queryKey: queryKeys.dataSources, queryFn: () => api.get<PageType<DataSource>>("/api/v1/data-sources", { query: { limit: 500 } }) });
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<{ token: string; url: string | null } | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", adapter_key: "chirpstack", enabled: true, config: JSON.stringify(ADAPTERS[0].config, null, 2), credentials: JSON.stringify(ADAPTERS[0].credentials, null, 2), project_ids: [] } });
  const adapterKey = form.watch("adapter_key");
  useEffect(() => {
    if (!open) return;
    if (editing) form.reset({ name: editing.name, adapter_key: editing.adapter_key, enabled: editing.enabled, config: JSON.stringify(editing.config, null, 2), credentials: "", project_ids: editing.project_ids ?? [] });
    else { const a = ADAPTERS[0]; form.reset({ name: "", adapter_key: a.key, enabled: true, config: JSON.stringify(a.config, null, 2), credentials: JSON.stringify(a.credentials, null, 2), project_ids: [] }); }
  }, [open, editing, form]);
  const save = useMutationToast({
    mutationFn: (values: Values) => {
      const body: Record<string, unknown> = { name: values.name, enabled: values.enabled, config: JSON.parse(values.config), project_ids: values.project_ids };
      if (values.credentials.trim()) body.credentials = JSON.parse(values.credentials);
      if (!editing) body.adapter_key = values.adapter_key;
      return editing ? api.patch<DataSource>(`/api/v1/data-sources/${editing.id}`, { body }) : api.post<DataSource>("/api/v1/data-sources", { body });
    },
    invalidate: [queryKeys.dataSources],
    success: editing ? "Data source saved" : "Data source created",
    onSuccess: (source) => { setOpen(false); if (source.webhook_token) setToken({ token: source.webhook_token, url: source.webhook_url ?? null }); },
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const rotate = useMutationToast({ mutationFn: (id: string) => api.post<DataSource>(`/api/v1/data-sources/${id}/webhook-token`), invalidate: [queryKeys.dataSources], onSuccess: (source) => source.webhook_token && setToken({ token: source.webhook_token, url: source.webhook_url ?? null }) });
  const columns: ColumnDef<DataSource, unknown>[] = [
    { header: "Name", accessorKey: "name" },
    { header: "Adapter", accessorKey: "adapter_key" },
    { header: "Enabled", accessorKey: "enabled", cell: ({ getValue }) => (getValue<boolean>() ? "yes" : "no") },
    { header: "Credentials", accessorKey: "has_credentials", cell: ({ getValue }) => (getValue<boolean>() ? "stored" : "none") },
    { header: "Capabilities", id: "caps", cell: ({ row }) => <Capabilities source={row.original} /> },
    { header: "Projects", accessorFn: (s) => (s.project_ids ?? []).length || "all" },
    { header: "Updated", accessorKey: "updated_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { id: "token", header: "", cell: ({ row }) => (row.original.adapter_key === "generic_http" ? <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); rotate.mutate(row.original.id); }}><KeyRound className="size-4" /> New token</Button> : null) },
  ];
  return (
    <>
      <PageHeader title="Data sources" description="External platform accounts: network servers, brokers, webhooks" actions={<Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> New data source</Button>} />
      <Page><DataTable columns={columns} data={sources.data?.items} isLoading={sources.isPending} onRowClick={(s) => { setEditing(s); setOpen(true); }} /></Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{editing ? "Edit data source" : "New data source"}</DialogTitle><DialogDescription>Credentials are encrypted and never shown again.</DialogDescription></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <Field label="Name" htmlFor="ds-name" error={form.formState.errors.name?.message}><Input id="ds-name" {...form.register("name")} /></Field>
            <Field label="Adapter" htmlFor="ds-adapter">
              <Select value={adapterKey} disabled={Boolean(editing)} onValueChange={(v) => { form.setValue("adapter_key", v); const a = ADAPTERS.find((x) => x.key === v); if (a && !editing) { form.setValue("config", JSON.stringify(a.config, null, 2)); form.setValue("credentials", JSON.stringify(a.credentials, null, 2)); } }}>
                <SelectTrigger id="ds-adapter"><SelectValue /></SelectTrigger>
                <SelectContent>{ADAPTERS.map((a) => <SelectItem key={a.key} value={a.key}>{a.label}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="flex items-center gap-2"><Switch id="ds-enabled" checked={form.watch("enabled")} onCheckedChange={(v) => form.setValue("enabled", v)} /><label htmlFor="ds-enabled" className="text-sm">Enabled</label></div>
            <Field label="Configuration (JSON)" htmlFor="ds-config" error={form.formState.errors.config?.message}><Textarea id="ds-config" rows={6} className="font-mono text-xs" {...form.register("config")} /></Field>
            <Field label="Credentials (JSON)" htmlFor="ds-credentials" hint={editing ? "Leave empty to keep the stored credentials" : undefined} error={form.formState.errors.credentials?.message}><Textarea id="ds-credentials" rows={3} className="font-mono text-xs" {...form.register("credentials")} /></Field>
            <Field label="Project scope" htmlFor="ds-projects" hint="Optional. Leave empty for all projects.">
              <div className="flex flex-wrap gap-2">
                {projects.data?.items.map((p) => { const on = form.watch("project_ids").includes(p.id); return <Button key={p.id} type="button" size="sm" variant={on ? "default" : "outline"} onClick={() => form.setValue("project_ids", on ? form.getValues("project_ids").filter((x) => x !== p.id) : [...form.getValues("project_ids"), p.id])}>{p.name}</Button>; })}
              </div>
            </Field>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={save.isPending}>Save</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={token != null} onOpenChange={(o) => !o && setToken(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Webhook token</DialogTitle><DialogDescription>Shown once. Store it where the sending platform is configured.</DialogDescription></DialogHeader>
          {token && (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2"><code className="flex-1 break-all rounded bg-muted p-2 text-xs">{token.token}</code><Button variant="outline" size="icon" aria-label="Copy token" onClick={() => { void navigator.clipboard.writeText(token.token); toast.success("Token copied"); }}><Copy className="size-4" /></Button></div>
              {token.url && <div>POST JSON to <code className="rounded bg-muted px-1 text-xs">{token.url}</code> with header <code className="rounded bg-muted px-1 text-xs">Authorization: Bearer &lt;token&gt;</code></div>}
            </div>
          )}
          <DialogFooter><Button onClick={() => setToken(null)}>Done</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
