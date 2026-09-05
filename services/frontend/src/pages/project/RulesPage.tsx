import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Page as PageType, Rule } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { RuleEditor } from "@/components/rules/RuleEditor";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatAgo } from "@/lib/format";
import { describeDocument } from "@/lib/rules";

/** Rules of the project (architecture 15): list, enable and disable, editor with versions and replay. */
export function RulesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const role = useProjectRole(projectId);
  const admin = canAdmin(role);
  const base = `/api/v1/projects/${projectId}/rules`;
  const rules = useQuery({ queryKey: queryKeys.rules(projectId), queryFn: () => api.get<PageType<Rule>>(base, { query: { limit: 500 } }) });
  const [editing, setEditing] = useState<Rule | null>(null);
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState<Rule | null>(null);
  const toggle = useMutationToast({
    mutationFn: ({ rule, enabled }: { rule: Rule; enabled: boolean }) => api.patch<Rule>(`${base}/${rule.id}`, { body: { enabled } }),
    invalidate: [queryKeys.rules(projectId)],
    success: (rule) => (rule.enabled ? "Rule enabled" : "Rule disabled"),
  });
  const remove = useMutationToast({
    mutationFn: (rule: Rule) => api.delete<void>(`${base}/${rule.id}`),
    invalidate: [queryKeys.rules(projectId)],
    success: t("Rule deleted"),
    onSuccess: () => setRemoving(null),
  });

  const columns: ColumnDef<Rule, unknown>[] = [
    { header: t("Enabled"), accessorKey: "enabled", cell: ({ row }) => <span onClick={(e) => e.stopPropagation()}><Switch checked={row.original.enabled} disabled={!admin || (row.original.reserved_types ?? []).length > 0} aria-label={`Enable ${row.original.name}`} onCheckedChange={(v) => toggle.mutate({ rule: row.original, enabled: v })} /></span> },
    { header: t("Name"), accessorKey: "name", cell: ({ row }) => <div><div className="font-medium">{row.original.name}</div><div className="text-xs text-muted-foreground">{describeDocument(row.original.document as Record<string, unknown>)}</div></div> },
    { header: t("Event"), accessorFn: (r) => String((r.document as { event?: { event_type?: string } }).event?.event_type ?? ""), cell: ({ row }) => { const ev = (row.original.document as { event?: { event_type?: string; severity?: string; create_alert?: boolean } }).event; return <span className="inline-flex items-center gap-2"><code className="text-xs">{ev?.event_type}</code><StatusBadge value={ev?.severity} />{ev?.create_alert && <span className="text-xs text-muted-foreground">{t("alert")}</span>}</span>; } },
    { header: t("Version"), accessorKey: "current_version" },
    { header: t("Last fired"), accessorKey: "last_fired_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("State"), id: "state", cell: ({ row }) => ((row.original.reserved_types ?? []).length > 0 ? <span className="text-xs text-brand-sand">{t("uses {{types}} (later phase)", { types: (row.original.reserved_types ?? []).join(", ") })}</span> : row.original.last_error ? <span className="text-xs text-destructive" title={row.original.last_error}>{t("failed: {{error}}", { error: row.original.last_error.slice(0, 60) })}</span> : <StatusBadge value={row.original.enabled ? "active" : "inactive"} />) },
    { id: "actions", header: "", cell: ({ row }) => admin && <span onClick={(e) => e.stopPropagation()}><Button variant="ghost" size="icon" aria-label={t("Delete rule")} onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button></span> },
  ];

  return (
    <>
      <PageHeader title={t("Rules")} description={t("Versioned rules turn positions, measurements and silence into events and alerts")} actions={admin && <Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> {t("New rule")}</Button>} />
      <Page>
        {rules.error && <Callout kind="error">{rules.error.message}</Callout>}
        <DataTable columns={columns} data={rules.data?.items} searchable isLoading={rules.isPending} emptyMessage={t("No rules yet. Start from a template: geofence exit, speed limit, no data, battery low.")} onRowClick={(r) => { setEditing(r); setOpen(true); }} />
      </Page>
      <RuleEditor projectId={projectId} rule={editing} open={open} onOpenChange={setOpen} />
      <ConfirmDialog open={removing !== null} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete rule ${removing?.name ?? ""}?`} description={t("Events created by this rule keep their reference to it, but the rule and its versions are gone.")} confirmLabel={t("Delete")} pending={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </>
  );
}
