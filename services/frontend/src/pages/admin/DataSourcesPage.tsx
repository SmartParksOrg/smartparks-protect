import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Copy, KeyRound, Plus, RefreshCw, Trash2, Waypoints } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataSource, Page as PageType, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
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

interface AdapterInfo {
  key: string;
  label: string;
  push: boolean;
  can_send_commands: boolean;
  acquisition_channel: string;
  default_capabilities: Record<string, boolean>;
  config_schema: Record<string, unknown>;
  config_example: Record<string, unknown>;
  credentials_schema: Record<string, string>;
  setup_hint: string;
  polling: boolean;
  can_manage: boolean;
  builtin: boolean;
  webhook_token_in_query: boolean;
}

const credentialsTemplate = (a: AdapterInfo) => Object.fromEntries(Object.keys(a.credentials_schema).map((k) => [k, ""]));

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
  const { t } = useTranslation();
  const sources = useQuery({ queryKey: queryKeys.dataSources, queryFn: () => api.get<PageType<DataSource>>("/api/v1/data-sources", { query: { limit: 500 } }) });
  const adapters = useQuery({ queryKey: queryKeys.adapters, queryFn: () => api.get<AdapterInfo[]>("/api/v1/data-sources/adapters") });
  const ADAPTERS = adapters.data ?? [];
  // Built-in channel sources (WebBLE, log files) exist once per installation; nobody creates them.
  const CREATABLE = ADAPTERS.filter((a) => !a.builtin);
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<{ token: string; url: string | null } | null>(null);
  const [removing, setRemoving] = useState<DataSource | null>(null);
  const remove = useMutationToast({
    mutationFn: (s: DataSource) => api.delete(`/api/v1/data-sources/${s.id}`),
    invalidate: [queryKeys.dataSources],
    success: "Data source deleted",
    onSuccess: () => setRemoving(null),
  });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", adapter_key: "", enabled: true, config: "{}", credentials: "{}", project_ids: [] } });
  const adapterKey = form.watch("adapter_key");
  useEffect(() => {
    if (!open) return;
    if (editing) form.reset({ name: editing.name, adapter_key: editing.adapter_key, enabled: editing.enabled, config: JSON.stringify(editing.config, null, 2), credentials: "", project_ids: editing.project_ids ?? [] });
    else { const a = CREATABLE[0]; form.reset({ name: "", adapter_key: a?.key ?? "", enabled: true, config: JSON.stringify(a?.config_example ?? {}, null, 2), credentials: JSON.stringify(a ? credentialsTemplate(a) : {}, null, 2), project_ids: [] }); }
  }, [open, editing, form, ADAPTERS]);
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
  const [rescanning, setRescanning] = useState<DataSource | null>(null);
  const [since, setSince] = useState("");
  const rescan = useMutationToast({ mutationFn: (s: DataSource) => api.post<Record<string, unknown>>(`/api/v1/data-sources/${s.id}/cursor`, { body: { since: since ? new Date(since).toISOString() : null } }), invalidate: [queryKeys.dataSources], success: t("Cursor reset; the connector rescans at its next poll"), onSuccess: () => setRescanning(null) });
  const syncGateways = useMutationToast({ mutationFn: (s: DataSource) => api.post<{ synced: number }>(`/api/v1/data-sources/${s.id}/sync-gateways`), invalidate: [queryKeys.dataSources], success: (r) => `${r.synced} gateways synced` });
  const rotate = useMutationToast({ mutationFn: (id: string) => api.post<DataSource>(`/api/v1/data-sources/${id}/webhook-token`), invalidate: [queryKeys.dataSources], onSuccess: (source) => source.webhook_token && setToken({ token: source.webhook_token, url: source.webhook_url ?? null }) });
  const columns: ColumnDef<DataSource, unknown>[] = [
    { header: t("Name"), accessorKey: "name" },
    { header: t("Adapter"), accessorKey: "adapter_key", cell: ({ getValue }) => ADAPTERS.find((a) => a.key === getValue<string>())?.label ?? getValue<string>() },
    { header: t("Enabled"), accessorKey: "enabled", cell: ({ getValue }) => (getValue<boolean>() ? "yes" : "no") },
    { header: t("Credentials"), accessorKey: "has_credentials", cell: ({ getValue }) => (getValue<boolean>() ? "stored" : "none") },
    { header: t("Capabilities"), id: "caps", cell: ({ row }) => <Capabilities source={row.original} /> },
    { header: t("Projects"), accessorFn: (s) => (s.project_ids ?? []).length || "all" },
    { header: t("Updated"), accessorKey: "updated_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { id: "token", header: "", cell: ({ row }) => { const a = ADAPTERS.find((x) => x.key === row.original.adapter_key); const caps = row.original.capabilities as Record<string, boolean>; return <span className="flex gap-1" onClick={(e) => e.stopPropagation()}>
      {(row.original.has_webhook_token || ADAPTERS.find((x) => x.key === row.original.adapter_key)?.push) && <Button variant="ghost" size="sm" onClick={() => rotate.mutate(row.original.id)}><KeyRound className="size-4" /> {row.original.has_webhook_token ? t("New token") : t("Create webhook token")}</Button>}
      {a?.polling && <Button variant="ghost" size="sm" onClick={() => { setSince(""); setRescanning(row.original); }}><RefreshCw className="size-4" /> {t("Rescan")}</Button>}
      {a?.can_manage && caps.gateway_management && <Button variant="ghost" size="sm" disabled={syncGateways.isPending} onClick={() => syncGateways.mutate(row.original)}><Waypoints className="size-4" /> {t("Sync gateways")}</Button>}
      {!a?.builtin && <Button variant="ghost" size="sm" aria-label={t("Delete data source")} onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button>}
    </span>; } },
  ];
  return (
    <>
      <PageHeader title={t("Data sources")} description={t("External platform accounts: network servers, brokers, webhooks")} actions={<Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> {t("New data source")}</Button>} />
      <Page><DataTable columns={columns} data={sources.data?.items} isLoading={sources.isPending} onRowClick={(s) => { setEditing(s); setOpen(true); }} /></Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{editing ? "Edit data source" : "New data source"}</DialogTitle><DialogDescription>{t("Credentials are encrypted and never shown again.")}</DialogDescription></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <Field label={t("Name")} htmlFor="ds-name" error={form.formState.errors.name?.message}><Input id="ds-name" {...form.register("name")} /></Field>
            <Field label={t("Adapter")} htmlFor="ds-adapter">
              <Select value={adapterKey} disabled={Boolean(editing)} onValueChange={(v) => { form.setValue("adapter_key", v); const a = ADAPTERS.find((x) => x.key === v); if (a && !editing) { form.setValue("config", JSON.stringify(a.config_example, null, 2)); form.setValue("credentials", JSON.stringify(credentialsTemplate(a), null, 2)); } }}>
                <SelectTrigger id="ds-adapter"><SelectValue /></SelectTrigger>
                <SelectContent>{(editing ? ADAPTERS : CREATABLE).map((a) => <SelectItem key={a.key} value={a.key}>{a.label}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            {(() => { const a = ADAPTERS.find((x) => x.key === adapterKey); return a?.setup_hint ? <Callout kind="info">{a.setup_hint}{a.push ? (a.webhook_token_in_query ? " The webhook URL with its token is shown after saving; the platform posts to that URL as is." : " The webhook URL and its bearer token are shown after saving.") : ""}</Callout> : null; })()}
            <div className="flex items-start gap-2"><Switch id="ds-enabled" checked={form.watch("enabled")} onCheckedChange={(v) => form.setValue("enabled", v)} /><label htmlFor="ds-enabled" className="text-sm">{t("Enabled")}<span className="block text-xs text-muted-foreground">{t("Receives events: the webhook answers and the connector runs. Switch off to pause the source without deleting it.")}</span></label></div>
            <Field label={t("Configuration (JSON)")} htmlFor="ds-config" error={form.formState.errors.config?.message}><Textarea id="ds-config" rows={6} className="font-mono text-xs" {...form.register("config")} /></Field>
            <Field label={t("Credentials (JSON)")} htmlFor="ds-credentials" hint={editing ? "Leave empty to keep the stored credentials" : undefined} error={form.formState.errors.credentials?.message}><Textarea id="ds-credentials" rows={3} className="font-mono text-xs" {...form.register("credentials")} /></Field>
            <Field label={t("Project scope")} htmlFor="ds-projects" hint={t("Optional. Leave empty for all projects.")}>
              <div className="flex flex-wrap gap-2">
                {projects.data?.items.map((p) => { const on = form.watch("project_ids").includes(p.id); return <Button key={p.id} type="button" size="sm" variant={on ? "default" : "outline"} onClick={() => form.setValue("project_ids", on ? form.getValues("project_ids").filter((x) => x !== p.id) : [...form.getValues("project_ids"), p.id])}>{p.name}</Button>; })}
              </div>
            </Field>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending}>{t("Save")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={rescanning != null} onOpenChange={(o) => !o && setRescanning(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("Rescan")} {rescanning?.name}</DialogTitle><DialogDescription>{t("The connector reads everything again from this instant at its next poll. Records it stored before are recognised by their canonical keys, so nothing is duplicated. Leave empty for the adapter's default window.")}</DialogDescription></DialogHeader>
          <Field label={t("Rescan from")} htmlFor="ds-since"><Input id="ds-since" type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} /></Field>
          <DialogFooter><Button variant="outline" onClick={() => setRescanning(null)}>{t("Cancel")}</Button><Button disabled={rescan.isPending} onClick={() => rescanning && rescan.mutate(rescanning)}>{t("Reset cursor")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={token != null} onOpenChange={(o) => !o && setToken(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("Webhook token")}</DialogTitle><DialogDescription>{t("Shown once. Store it where the sending platform is configured.")}</DialogDescription></DialogHeader>
          {token && (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2"><code className="flex-1 break-all rounded bg-muted p-2 text-xs">{token.token}</code><Button variant="outline" size="icon" aria-label={t("Copy token")} onClick={() => { void navigator.clipboard.writeText(token.token); toast.success("Token copied"); }}><Copy className="size-4" /></Button></div>
              {token.url && <div>{t("POST JSON to")} <code className="rounded bg-muted px-1 text-xs">{token.url}</code> {t("with header")} <code className="rounded bg-muted px-1 text-xs">{"Authorization: Bearer <token>"}</code></div>}
            </div>
          )}
          <DialogFooter><Button onClick={() => setToken(null)}>{t("Done")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={removing !== null} onOpenChange={(open) => { if (!open) setRemoving(null); }} title={t("Delete data source")} description={removing ? t("{{name}} is removed with its webhook token and its external identities; devices and their data stay.", { name: removing.name }) : ""} confirmLabel={t("Delete")} onConfirm={() => { if (removing) remove.mutate(removing); }} />
    </>
  );
}
