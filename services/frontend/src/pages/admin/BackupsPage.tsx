import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { BackupRun, BackupStatus } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatAgo, formatTime } from "@/lib/format";

function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  if (seconds < 90) return `${seconds} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function size(bytes: number | null | undefined): string {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const kindLabels: Record<string, string> = {
  database_full: "Database full",
  database_incr: "Database incremental",
  object_mirror: "Object mirror",
  integrity_check: "Integrity check",
  restore_test: "Restore test",
};

/** Backup and recovery health for server admins (architecture 28.11): the items an operator
 * needs without shell access, the recovery point against the objectives, and the run history. */
export function BackupsPage() {
  const { t } = useTranslation();
  const status = useQuery({ queryKey: queryKeys.backupStatus, queryFn: () => api.get<BackupStatus>("/api/v1/admin/backups/status"), refetchInterval: 60_000 });
  const runs = useQuery({ queryKey: queryKeys.backupRuns, queryFn: () => api.get<BackupRun[]>("/api/v1/admin/backups/runs", { query: { limit: 100 } }), refetchInterval: 60_000 });
  const s = status.data;
  const columns: ColumnDef<BackupRun, unknown>[] = [
    { header: t("Started"), accessorKey: "started_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Job"), accessorKey: "kind", cell: ({ getValue }) => kindLabels[getValue<string>()] ?? getValue<string>() },
    { header: t("Result"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Duration"), accessorKey: "duration_seconds", cell: ({ getValue }) => duration(getValue<number>()) },
    { header: t("Size"), accessorKey: "size_bytes", cell: ({ getValue }) => size(getValue<number | null>()) },
    { header: t("Label"), accessorKey: "label", cell: ({ getValue }) => <span className="font-mono text-xs">{getValue<string | null>() ?? ""}</span> },
    { header: t("Host"), accessorKey: "host" },
    { header: t("Error"), accessorKey: "error", cell: ({ getValue }) => <span className="text-xs text-destructive">{(getValue<string | null>() ?? "").slice(0, 160)}</span> },
  ];
  return (
    <>
      <PageHeader title={t("Backup and recovery")} description={t("Off-server copies of the database, the WAL archive and the objects, and whether they were proven to restore")} actions={s && <StatusBadge value={s.overall} />} />
      <Page>
        {status.isError && <Callout kind="error">{status.error.message}</Callout>}
        {s && !s.enabled && <Callout kind="warning">{t("Backups are not enabled on this server. A production deployment is not complete until automated off-server backups are configured and visible here as healthy. See the backup and recovery guide in the documentation.")}</Callout>}
        {s && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {s.items.map((item) => (
              <Card key={item.key} className={item.status === "failed" ? "border-destructive/60" : item.status === "stale" ? "border-brand-sand" : undefined}>
                <CardContent className="pt-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs text-muted-foreground">{item.label}</div>
                    <StatusBadge value={item.status} />
                  </div>
                  <div className="mt-1 text-sm">{item.detail}</div>
                  {item.at && <div className="mt-1 text-xs text-muted-foreground">{formatAgo(item.at)}</div>}
                </CardContent>
              </Card>
            ))}
            <Card>
              <CardContent className="pt-4">
                <div className="text-xs text-muted-foreground">{t("Recovery objectives")}</div>
                <div className="mt-1 text-sm">{t("Estimated recovery point")} {s.recovery_point_seconds != null ? duration(s.recovery_point_seconds) + " ago" : "unknown"} {t("(target under")} {duration(s.rpo_seconds)})</div>
                <div className="text-sm">{t("Recovery target under {{duration}}, proven by the restore test", { duration: duration(s.rto_seconds) })}</div>
                {s.wal.last_archived_wal ? <div className="mt-1 text-xs text-muted-foreground">{t("Last WAL segment {{segment}}, {{archived}} archived, {{failed}} failed", { segment: String(s.wal.last_archived_wal), archived: String(s.wal.archived_count), failed: String(s.wal.failed_count) })}</div> : null}
              </CardContent>
            </Card>
          </div>
        )}
        <Card>
          <CardHeader><CardTitle>{t("Runs")}</CardTitle></CardHeader>
          <CardContent>
            <DataTable columns={columns} data={runs.data} searchable isLoading={runs.isPending} emptyMessage={t("No backup run recorded yet.")} />
          </CardContent>
        </Card>
      </Page>
    </>
  );
}
