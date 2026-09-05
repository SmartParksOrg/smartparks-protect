import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { TraceSummary } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { TraceDialog } from "@/components/devices/ProvenancePanel";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatTime } from "@/lib/format";

const STATUSES = ["pending", "processing", "success", "skipped", "duplicate", "retrying", "failed", "dead_letter"];

/** Trace explorer (architecture 26.3). */
export function TracesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const externalId = params.get("eui") ?? "";
  const hours = Number(params.get("hours") ?? 24);
  const [selected, setSelected] = useState<string | null>(params.get("trace"));
  const traces = useQuery({
    queryKey: queryKeys.traces(projectId, { status, externalId, hours }),
    queryFn: () => api.get<TraceSummary[]>(`/api/v1/projects/${projectId}/traces`, { query: { status: status || undefined, external_id: externalId || undefined, from: new Date(Date.now() - hours * 3600_000).toISOString(), limit: 200 } }),
  });

  const columns: ColumnDef<TraceSummary, unknown>[] = [
    { header: t("Started"), accessorKey: "started_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Object"), accessorFn: (t) => `${t.root_object_type} ${t.root_object_id}` },
    { header: t("Class"), accessorKey: "trace_class" },
    { header: t("Error"), accessorKey: "error_code", cell: ({ getValue }) => <span className="text-xs text-destructive">{getValue<string | null>()}</span> },
    { header: t("Trace id"), accessorKey: "id", cell: ({ getValue }) => <span className="font-mono text-xs">{getValue<string>().slice(0, 8)}</span> },
  ];

  return (
    <>
      <PageHeader
        title={t("Trace explorer")}
        description={t("Where each message, command or import went and where it stopped")}
        actions={<>
          <Input placeholder={t("DevEUI or external id")} className="w-56 font-mono" value={externalId} onChange={(e) => setParams((p) => { if (e.target.value) p.set("eui", e.target.value); else p.delete("eui"); return p; })} />
          <Select value={status || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("status"); else p.set("status", v); return p; })}>
            <SelectTrigger className="w-40"><SelectValue placeholder={t("All statuses")} /></SelectTrigger>
            <SelectContent><SelectItem value="all">{t("All statuses")}</SelectItem>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
          </Select>
          <Input type="number" min={1} max={720} className="w-24" value={hours} onChange={(e) => setParams((p) => { p.set("hours", e.target.value); return p; })} aria-label={t("Hours back")} />
        </>}
      />
      <Page>
        <DataTable columns={columns} data={traces.data} searchable isLoading={traces.isPending} emptyMessage={t("No traces in this window.")} onRowClick={(t) => setSelected(t.id)} rowClassName={(t) => (t.status === "failed" || t.status === "dead_letter" ? "bg-destructive/5" : undefined)} />
      </Page>
      <TraceDialog traceId={selected} onClose={() => setSelected(null)} />
    </>
  );
}
