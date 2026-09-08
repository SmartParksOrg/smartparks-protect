import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Link2,
  Activity,
  Copy,
  Cpu,
  KeyRound,
  Plug,
  Plus,
  Radio,
  RefreshCw,
  Trash2,
  Waypoints,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  ConnectApplicationsResult,
  DataSource,
  Page as PageType,
  ProjectWithRole,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import {
  DataSourceForm,
  type AdapterInfo,
} from "@/components/admin/DataSourceForm";
import { formatAgo, formatTime } from "@/lib/format";

/** The capability inspector shows what the adapter supports for this account (architecture 8.2). */
function Capabilities({ source }: { source: DataSource }) {
  const entries = Object.entries(
    source.capabilities as Record<string, boolean>,
  );
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className={`rounded px-1.5 py-0.5 text-[11px] ${v ? "bg-brand-green-light/40" : "bg-muted text-muted-foreground line-through"}`}
        >
          {k}
        </span>
      ))}
    </div>
  );
}

export function DataSourcesPage() {
  const { t } = useTranslation();
  const sources = useQuery({
    queryKey: queryKeys.dataSources,
    queryFn: () =>
      api.get<PageType<DataSource>>("/api/v1/data-sources", {
        query: { limit: 500 },
      }),
  });
  const adapters = useQuery({
    queryKey: queryKeys.adapters,
    queryFn: () => api.get<AdapterInfo[]>("/api/v1/data-sources/adapters"),
  });
  const ADAPTERS = adapters.data ?? [];
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: () =>
      api.get<PageType<ProjectWithRole>>("/api/v1/projects", {
        query: { limit: 500 },
      }),
  });
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [open, setOpen] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const [token, setToken] = useState<{
    token: string;
    url: string | null;
    source?: DataSource;
  } | null>(null);
  const [removing, setRemoving] = useState<DataSource | null>(null);
  const [statusOf, setStatusOf] = useState<DataSource | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [connectResult, setConnectResult] = useState<{
    source: DataSource;
    result: ConnectApplicationsResult;
  } | null>(null);
  const navigate = useNavigate();
  const remove = useMutationToast({
    mutationFn: (s: DataSource) => api.delete(`/api/v1/data-sources/${s.id}`),
    invalidate: [queryKeys.dataSources],
    success: "Data source deleted",
    onSuccess: () => setRemoving(null),
  });
  const [rescanning, setRescanning] = useState<DataSource | null>(null);
  const [since, setSince] = useState("");
  const rescan = useMutationToast({
    mutationFn: (s: DataSource) =>
      api.post<Record<string, unknown>>(`/api/v1/data-sources/${s.id}/cursor`, {
        body: { since: since ? new Date(since).toISOString() : null },
      }),
    invalidate: [queryKeys.dataSources],
    success: t("Cursor reset; the connector rescans at its next poll"),
    onSuccess: () => setRescanning(null),
  });
  const testConnection = useMutationToast({
    mutationFn: (s: DataSource) =>
      api.post<{
        ok: boolean;
        detail: string;
        result?: { applications?: unknown[]; connected?: number };
      }>(`/api/v1/data-sources/${s.id}/test`),
    success: (r) =>
      r.ok
        ? `Connection ok: ${r.detail}${r.result?.applications ? ` ${t("{{connected}} of {{total}} applications post to this source", { connected: r.result.connected ?? 0, total: r.result.applications.length })}` : ""}`
        : `Connection failed: ${r.detail}`,
  });
  const syncDevices = useMutationToast({
    mutationFn: (s: DataSource) =>
      api.post<{ listed: number; created: number; updated: number }>(
        `/api/v1/data-sources/${s.id}/sync-devices`,
      ),
    invalidate: [queryKeys.dataSources],
    success: (r) =>
      `${r.listed} devices listed, ${r.created} new identities (see Needs attention), ${r.updated} refreshed`,
  });
  // Connect applications previews first (a dry run, decision D129); Apply writes.
  const previewApplications = useMutationToast({
    mutationFn: (s: DataSource) =>
      api.post<ConnectApplicationsResult>(
        `/api/v1/data-sources/${s.id}/connect-applications`,
        { query: { dry_run: true } },
      ),
    onSuccess: (result, source) => {
      setToken(null);
      setTicked(
        new Set(
          result.applications
            .filter((a) => a.outcome === "connected" || a.outcome === "updated")
            .map((a) => a.application_id),
        ),
      );
      setConnectResult({ source, result });
    },
  });
  const connectApplications = useMutationToast({
    mutationFn: (s: DataSource) =>
      api.post<ConnectApplicationsResult>(
        `/api/v1/data-sources/${s.id}/connect-applications`,
        { body: { application_ids: [...ticked] } },
      ),
    invalidate: [queryKeys.dataSources],
    success: (r) =>
      t(
        "{{connected}} applications connected, {{updated}} updated, {{already}} already, {{failed}} failed",
        r,
      ),
    onSuccess: (result, source) => setConnectResult({ source, result }),
  });
  const syncGateways = useMutationToast({
    mutationFn: (s: DataSource) =>
      api.post<{ synced: number }>(
        `/api/v1/data-sources/${s.id}/sync-gateways`,
      ),
    invalidate: [queryKeys.dataSources],
    success: (r) => `${r.synced} gateways synced`,
  });
  const rotate = useMutationToast({
    mutationFn: (id: string) =>
      api.post<DataSource>(`/api/v1/data-sources/${id}/webhook-token`),
    invalidate: [queryKeys.dataSources],
    onSuccess: (source) =>
      source.webhook_token &&
      setToken({
        token: source.webhook_token,
        url: source.webhook_url ?? null,
        source,
      }),
  });
  const columns: ColumnDef<DataSource, unknown>[] = [
    { header: t("Name"), accessorKey: "name" },
    {
      header: t("Adapter"),
      accessorKey: "adapter_key",
      cell: ({ getValue }) =>
        ADAPTERS.find((a) => a.key === getValue<string>())?.label ??
        getValue<string>(),
    },
    {
      header: t("Enabled"),
      accessorKey: "enabled",
      cell: ({ getValue }) => (getValue<boolean>() ? "yes" : "no"),
    },
    {
      header: t("Credentials"),
      accessorKey: "has_credentials",
      cell: ({ getValue }) => (getValue<boolean>() ? "stored" : "none"),
    },
    {
      header: t("Capabilities"),
      id: "caps",
      cell: ({ row }) => <Capabilities source={row.original} />,
    },
    {
      header: t("Projects"),
      accessorFn: (s) => (s.project_ids ?? []).length || "all",
    },
    {
      header: t("Updated"),
      accessorKey: "updated_at",
      cell: ({ getValue }) => formatTime(getValue<string>()),
    },
    {
      id: "token",
      header: "",
      cell: ({ row }) => {
        const a = ADAPTERS.find((x) => x.key === row.original.adapter_key);
        const caps = row.original.capabilities as Record<string, boolean>;
        return (
          <span className="flex gap-1" onClick={(e) => e.stopPropagation()}>
            {(row.original.has_webhook_token ||
              ADAPTERS.find((x) => x.key === row.original.adapter_key)
                ?.push) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => rotate.mutate(row.original.id)}
              >
                <KeyRound className="size-4" />{" "}
                {row.original.has_webhook_token
                  ? t("New token")
                  : t("Create webhook token")}
              </Button>
            )}
            {a?.polling && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSince("");
                  setRescanning(row.original);
                }}
              >
                <RefreshCw className="size-4" /> {t("Rescan")}
              </Button>
            )}
            {a?.can_manage && (
              <Button
                variant="ghost"
                size="sm"
                disabled={testConnection.isPending}
                onClick={() => testConnection.mutate(row.original)}
              >
                <Plug className="size-4" /> {t("Test connection")}
              </Button>
            )}
            {a?.can_manage && caps.device_management && (
              <Button
                variant="ghost"
                size="sm"
                disabled={syncDevices.isPending}
                onClick={() => syncDevices.mutate(row.original)}
              >
                <Cpu className="size-4" /> {t("Sync devices")}
              </Button>
            )}
            {a?.can_manage && caps.gateway_management && (
              <Button
                variant="ghost"
                size="sm"
                disabled={syncGateways.isPending}
                onClick={() => syncGateways.mutate(row.original)}
              >
                <Waypoints className="size-4" /> {t("Sync gateways")}
              </Button>
            )}
            {a?.connects_applications && (
              <Button
                variant="ghost"
                size="sm"
                disabled={previewApplications.isPending}
                onClick={() => previewApplications.mutate(row.original)}
              >
                <Link2 className="size-4" /> {t("Connect applications")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setStatusOf(row.original)}
            >
              <Activity className="size-4" /> {t("Status")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                navigate(`/admin/data-sources/${row.original.id}/traffic`)
              }
            >
              <Radio className="size-4" /> {t("Traffic")}
            </Button>
            {!a?.builtin && (
              <Button
                variant="ghost"
                size="sm"
                aria-label={t("Delete data source")}
                onClick={() => setRemoving(row.original)}
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </span>
        );
      },
    },
  ];
  return (
    <>
      <PageHeader
        title={t("Data sources")}
        description={t(
          "External platform accounts: network servers, brokers, webhooks",
        )}
        actions={
          <Button
            onClick={() => {
              setEditing(null);
              setFormKey((k) => k + 1);
              setOpen(true);
            }}
          >
            <Plus className="size-4" /> {t("New data source")}
          </Button>
        }
      />
      <Page>
        <DataTable
          columns={columns}
          data={sources.data?.items}
          searchable
          isLoading={sources.isPending}
          onRowClick={(s) => {
            setEditing(s);
            setFormKey((k) => k + 1);
            setOpen(true);
          }}
        />
      </Page>
      <DataSourceForm
        key={`${editing?.id ?? "new"}-${formKey}`}
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        adapters={ADAPTERS}
        projects={projects.data?.items ?? []}
        onSaved={(source) => {
          if (source.webhook_token)
            setToken({
              token: source.webhook_token,
              url: source.webhook_url ?? null,
              source,
            });
        }}
      />
      <Dialog
        open={rescanning != null}
        onOpenChange={(o) => !o && setRescanning(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("Rescan")} {rescanning?.name}
            </DialogTitle>
            <DialogDescription>
              {t(
                "The connector reads everything again from this instant at its next poll. Records it stored before are recognised by their canonical keys, so nothing is duplicated. Leave empty for the adapter's default window.",
              )}
            </DialogDescription>
          </DialogHeader>
          <Field label={t("Rescan from")} htmlFor="ds-since">
            <Input
              id="ds-since"
              type="datetime-local"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </Field>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRescanning(null)}>
              {t("Cancel")}
            </Button>
            <Button
              disabled={rescan.isPending}
              onClick={() => rescanning && rescan.mutate(rescanning)}
            >
              {t("Reset cursor")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={token != null} onOpenChange={(o) => !o && setToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("Webhook token")}</DialogTitle>
            <DialogDescription>
              {t(
                "Shown once. Store it where the sending platform is configured.",
              )}
            </DialogDescription>
          </DialogHeader>
          {token && (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <code className="flex-1 break-all rounded bg-muted p-2 text-xs">
                  {token.token}
                </code>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label={t("Copy token")}
                  onClick={() => {
                    void navigator.clipboard.writeText(token.token);
                    toast.success("Token copied");
                  }}
                >
                  <Copy className="size-4" />
                </Button>
              </div>
              {token.url && (
                <div>
                  {t("POST JSON to")}{" "}
                  <code className="rounded bg-muted px-1 text-xs">
                    {token.url}
                  </code>{" "}
                  {t("with header")}{" "}
                  <code className="rounded bg-muted px-1 text-xs">
                    {"Authorization: Bearer <token>"}
                  </code>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            {token?.source &&
              ADAPTERS.find((x) => x.key === token.source?.adapter_key)
                ?.connects_applications && (
                <Button
                  variant="outline"
                  disabled={previewApplications.isPending}
                  onClick={() =>
                    token.source && previewApplications.mutate(token.source)
                  }
                >
                  <Link2 className="size-4" /> {t("Connect applications")}
                </Button>
              )}
            <Button onClick={() => setToken(null)}>{t("Done")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={connectResult != null}
        onOpenChange={(o) => !o && setConnectResult(null)}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {t("Applications of {{name}}", {
                name: connectResult?.source.name,
              })}
            </DialogTitle>
            <DialogDescription>
              {connectResult?.result.dry_run
                ? t(
                    "Nothing is changed yet. This is what Apply would do on each application's HTTP integration; other URLs and headers stay as they are.",
                  )
                : t(
                    "Every application of the tenant posts its events to this source's webhook from now on; other URLs and headers on the integrations were left as they were.",
                  )}
            </DialogDescription>
          </DialogHeader>
          {connectResult && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  {connectResult.result.dry_run && <th className="w-6 py-1" />}
                  <th className="py-1">{t("Application")}</th>
                  <th>
                    {connectResult.result.dry_run ? t("Would") : t("Outcome")}
                  </th>
                  <th>{t("Kept")}</th>
                </tr>
              </thead>
              <tbody>
                {connectResult.result.applications.map((a) => {
                  const others = (a.urls ?? []).filter(
                    (u) => !u.includes("/api/v1/ingest/http/"),
                  ).length;
                  const changeable =
                    a.outcome === "connected" || a.outcome === "updated";
                  return (
                    <tr key={a.application_id} className="border-t align-top">
                      {connectResult.result.dry_run && (
                        <td className="py-1">
                          <input
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={t("Connect {{name}}", { name: a.name })}
                            disabled={!changeable}
                            checked={changeable && ticked.has(a.application_id)}
                            onChange={(e) =>
                              setTicked((s) => {
                                const next = new Set(s);
                                if (e.target.checked)
                                  next.add(a.application_id);
                                else next.delete(a.application_id);
                                return next;
                              })
                            }
                          />
                        </td>
                      )}
                      <td className="py-1">{a.name}</td>
                      <td className="py-1">
                        {a.outcome === "failed" ? (
                          <span className="text-destructive">
                            {t("failed")}: {a.error}
                          </span>
                        ) : a.outcome === "already" ? (
                          t("already connected")
                        ) : a.outcome === "updated" ? (
                          t("our entry updated to the new token")
                        ) : (a.before ?? []).length > 0 ? (
                          t("ours added to the URL list")
                        ) : (
                          t("HTTP integration created")
                        )}
                      </td>
                      <td className="py-1 text-xs text-muted-foreground">
                        {others > 0
                          ? t("{{count}} other URL", { count: others })
                          : t("no other URL")}
                        {(a.headers ?? []).length > 0
                          ? `, ${t("{{count}} header", { count: (a.headers ?? []).length })}`
                          : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <DialogFooter>
            {connectResult?.result.dry_run &&
              connectResult.result.connected + connectResult.result.updated >
                0 && (
                <Button
                  disabled={connectApplications.isPending || ticked.size === 0}
                  onClick={() =>
                    connectResult &&
                    connectApplications.mutate(connectResult.source)
                  }
                >
                  {t("Apply to {{count}} applications", { count: ticked.size })}
                </Button>
              )}
            <Button
              variant={connectResult?.result.dry_run ? "outline" : "default"}
              onClick={() => setConnectResult(null)}
            >
              {connectResult?.result.dry_run ? t("Cancel") : t("Done")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <StatusDialog source={statusOf} onClose={() => setStatusOf(null)} />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("Delete data source")}
        description={
          removing
            ? t(
                "{{name}} is removed with its webhook token and its external identities; devices and their data stay.",
                { name: removing.name },
              )
            : ""
        }
        confirmLabel={t("Delete")}
        onConfirm={() => {
          if (removing) remove.mutate(removing);
        }}
      />
    </>
  );
}

type ChannelStatus = {
  key: string;
  label: string;
  direction: string;
  purpose: string;
  hint?: string | null;
  configured: boolean;
  missing: string[];
  state: string;
  detail?: string | null;
  last_at?: string | null;
  count_24h: number;
};
type SourceStatus = {
  channels: ChannelStatus[];
  effective_capabilities: Record<string, boolean>;
  limited_capabilities: string[];
};

/** Per channel: configured or not, and working or not, refreshed every five seconds. */
function StatusDialog({
  source,
  onClose,
}: {
  source: DataSource | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const status = useQuery({
    queryKey: queryKeys.dataSourceStatus(source?.id ?? ""),
    queryFn: () =>
      api.get<SourceStatus>(`/api/v1/data-sources/${source?.id}/status`),
    enabled: source !== null,
    refetchInterval: source ? 5_000 : false,
  });
  return (
    <Dialog open={source !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {source
              ? t("Status of {{name}}", { name: source.name })
              : t("Status")}
          </DialogTitle>
          <DialogDescription>
            {t(
              "Each channel of this source: whether it is configured and whether it works, from what arrived, the live connection and the last API answer.",
            )}
          </DialogDescription>
        </DialogHeader>
        {status.error && <Callout kind="error">{status.error.message}</Callout>}
        {status.data && (
          <div className="space-y-3 text-sm">
            <ul className="divide-y rounded-md border">
              {status.data.channels.map((c) => (
                <li key={c.key} className="flex items-start gap-3 px-3 py-2">
                  <StatusBadge value={c.state} />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">
                      {c.label}{" "}
                      <span className="text-xs font-normal text-muted-foreground">
                        {c.direction === "in" ? t("inbound") : t("outbound")}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {c.purpose}
                    </div>
                    {c.detail && <div className="text-xs">{c.detail}</div>}
                    {c.last_at && (
                      <div className="text-xs text-muted-foreground">
                        {t("last {{ago}}", { ago: formatAgo(c.last_at) })}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            {status.data.limited_capabilities.length > 0 && (
              <Callout kind="warning">
                {t("Held back until their channel is configured: {{list}}", {
                  list: status.data.limited_capabilities.join(", "),
                })}
              </Callout>
            )}
            <div className="text-xs text-muted-foreground">
              {t("Effective capabilities: {{list}}", {
                list:
                  Object.entries(status.data.effective_capabilities)
                    .filter(([, v]) => v)
                    .map(([k]) => k)
                    .join(", ") || t("none"),
              })}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("Close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
