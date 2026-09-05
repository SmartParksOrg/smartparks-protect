import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Activity, Copy, Cpu, KeyRound, Plug, Plus, Radio, RefreshCw, Trash2, Waypoints } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataSource, Page as PageType, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { DataSourceForm, type AdapterInfo } from "@/components/admin/DataSourceForm";
import { formatAgo, formatTime } from "@/lib/format";



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
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [open, setOpen] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const [token, setToken] = useState<{ token: string; url: string | null } | null>(null);
  const [removing, setRemoving] = useState<DataSource | null>(null);
  const [statusOf, setStatusOf] = useState<DataSource | null>(null);
  const navigate = useNavigate();
  const remove = useMutationToast({
    mutationFn: (s: DataSource) => api.delete(`/api/v1/data-sources/${s.id}`),
    invalidate: [queryKeys.dataSources],
    success: "Data source deleted",
    onSuccess: () => setRemoving(null),
  });
  const [rescanning, setRescanning] = useState<DataSource | null>(null);
  const [since, setSince] = useState("");
  const rescan = useMutationToast({ mutationFn: (s: DataSource) => api.post<Record<string, unknown>>(`/api/v1/data-sources/${s.id}/cursor`, { body: { since: since ? new Date(since).toISOString() : null } }), invalidate: [queryKeys.dataSources], success: t("Cursor reset; the connector rescans at its next poll"), onSuccess: () => setRescanning(null) });
  const testConnection = useMutationToast({ mutationFn: (s: DataSource) => api.post<{ ok: boolean; detail: string }>(`/api/v1/data-sources/${s.id}/test`), success: (r) => (r.ok ? `Connection ok: ${r.detail}` : `Connection failed: ${r.detail}`) });
  const syncDevices = useMutationToast({ mutationFn: (s: DataSource) => api.post<{ listed: number; created: number; updated: number }>(`/api/v1/data-sources/${s.id}/sync-devices`), invalidate: [queryKeys.dataSources], success: (r) => `${r.listed} devices listed, ${r.created} new identities (see Needs attention), ${r.updated} refreshed` });
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
      {a?.can_manage && <Button variant="ghost" size="sm" disabled={testConnection.isPending} onClick={() => testConnection.mutate(row.original)}><Plug className="size-4" /> {t("Test connection")}</Button>}
      {a?.can_manage && caps.device_management && <Button variant="ghost" size="sm" disabled={syncDevices.isPending} onClick={() => syncDevices.mutate(row.original)}><Cpu className="size-4" /> {t("Sync devices")}</Button>}
      {a?.can_manage && caps.gateway_management && <Button variant="ghost" size="sm" disabled={syncGateways.isPending} onClick={() => syncGateways.mutate(row.original)}><Waypoints className="size-4" /> {t("Sync gateways")}</Button>}
      <Button variant="ghost" size="sm" onClick={() => setStatusOf(row.original)}><Activity className="size-4" /> {t("Status")}</Button>
      <Button variant="ghost" size="sm" onClick={() => navigate(`/admin/data-sources/${row.original.id}/traffic`)}><Radio className="size-4" /> {t("Traffic")}</Button>
      {!a?.builtin && <Button variant="ghost" size="sm" aria-label={t("Delete data source")} onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button>}
    </span>; } },
  ];
  return (
    <>
      <PageHeader title={t("Data sources")} description={t("External platform accounts: network servers, brokers, webhooks")} actions={<Button onClick={() => { setEditing(null); setFormKey((k) => k + 1); setOpen(true); }}><Plus className="size-4" /> {t("New data source")}</Button>} />
      <Page><DataTable columns={columns} data={sources.data?.items} isLoading={sources.isPending} onRowClick={(s) => { setEditing(s); setFormKey((k) => k + 1); setOpen(true); }} /></Page>
      <DataSourceForm key={`${editing?.id ?? "new"}-${formKey}`} open={open} onOpenChange={setOpen} editing={editing} adapters={ADAPTERS} projects={projects.data?.items ?? []} onSaved={(source) => { if (source.webhook_token) setToken({ token: source.webhook_token, url: source.webhook_url ?? null }); }} />
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
      <StatusDialog source={statusOf} onClose={() => setStatusOf(null)} />
      <ConfirmDialog open={removing !== null} onOpenChange={(open) => { if (!open) setRemoving(null); }} title={t("Delete data source")} description={removing ? t("{{name}} is removed with its webhook token and its external identities; devices and their data stay.", { name: removing.name }) : ""} confirmLabel={t("Delete")} onConfirm={() => { if (removing) remove.mutate(removing); }} />
    </>
  );
}

type ChannelStatus = { key: string; label: string; direction: string; purpose: string; hint?: string | null; configured: boolean; missing: string[]; state: string; detail?: string | null; last_at?: string | null; count_24h: number };
type SourceStatus = { channels: ChannelStatus[]; effective_capabilities: Record<string, boolean>; limited_capabilities: string[] };

/** Per channel: configured or not, and working or not, refreshed every five seconds. */
function StatusDialog({ source, onClose }: { source: DataSource | null; onClose: () => void }) {
  const { t } = useTranslation();
  const status = useQuery({ queryKey: queryKeys.dataSourceStatus(source?.id ?? ""), queryFn: () => api.get<SourceStatus>(`/api/v1/data-sources/${source?.id}/status`), enabled: source !== null, refetchInterval: source ? 5_000 : false });
  return (
    <Dialog open={source !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>{source ? t("Status of {{name}}", { name: source.name }) : t("Status")}</DialogTitle><DialogDescription>{t("Each channel of this source: whether it is configured and whether it works, from what arrived, the live connection and the last API answer.")}</DialogDescription></DialogHeader>
        {status.error && <Callout kind="error">{status.error.message}</Callout>}
        {status.data && (
          <div className="space-y-3 text-sm">
            <ul className="divide-y rounded-md border">
              {status.data.channels.map((c) => (
                <li key={c.key} className="flex items-start gap-3 px-3 py-2">
                  <StatusBadge value={c.state} />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{c.label} <span className="text-xs font-normal text-muted-foreground">{c.direction === "in" ? t("inbound") : t("outbound")}</span></div>
                    <div className="text-xs text-muted-foreground">{c.purpose}</div>
                    {c.detail && <div className="text-xs">{c.detail}</div>}
                    {c.last_at && <div className="text-xs text-muted-foreground">{t("last {{ago}}", { ago: formatAgo(c.last_at) })}</div>}
                  </div>
                </li>
              ))}
            </ul>
            {status.data.limited_capabilities.length > 0 && <Callout kind="warning">{t("Held back until their channel is configured: {{list}}", { list: status.data.limited_capabilities.join(", ") })}</Callout>}
            <div className="text-xs text-muted-foreground">{t("Effective capabilities: {{list}}", { list: Object.entries(status.data.effective_capabilities).filter(([, v]) => v).map(([k]) => k).join(", ") || t("none") })}</div>
          </div>
        )}
        <DialogFooter><Button variant="outline" onClick={onClose}>{t("Close")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
