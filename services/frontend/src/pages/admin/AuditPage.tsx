import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AuditEntry } from "@/api/types";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { formatTime } from "@/lib/format";

export function AuditPage() {
  const { t } = useTranslation();
  const audit = useQuery({ queryKey: queryKeys.audit(null), queryFn: () => api.get<AuditEntry[]>("/api/v1/admin/audit", { query: { limit: 200 } }) });
  const columns: ColumnDef<AuditEntry, unknown>[] = [
    { header: t("Time"), accessorKey: "time", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Action"), accessorKey: "action" },
    { header: t("Object"), accessorFn: (e) => `${e.object_type} ${e.object_id?.slice(0, 8) ?? ""}` },
    { header: t("User"), accessorKey: "user_id", cell: ({ getValue }) => <span className="font-mono text-xs">{getValue<string | null>()?.slice(0, 8)}</span> },
    { header: t("Project"), accessorKey: "project_id", cell: ({ getValue }) => <span className="font-mono text-xs">{getValue<string | null>()?.slice(0, 8)}</span> },
    { header: t("Details"), accessorKey: "details", cell: ({ getValue }) => { const v = getValue<Record<string, unknown>>(); return Object.keys(v).length ? <JsonView value={v} className="max-h-24 max-w-md p-2" /> : null; } },
  ];
  return (
    <>
      <PageHeader title={t("Audit log")} description={t("Newest 200 changes across the server")} />
      <Page><DataTable columns={columns} data={audit.data} searchable isLoading={audit.isPending} /></Page>
    </>
  );
}
