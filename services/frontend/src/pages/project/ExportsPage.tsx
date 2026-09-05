import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Download, Plus, RefreshCw, Repeat } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router";
import { toast } from "sonner";

import { api, downloadFile } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { ExportJob, Page as PageType } from "@/api/types";
import { ExportDialog } from "@/components/analytics/ExportDialog";
import { Callout } from "@/components/common/Callout";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatInZone } from "@/lib/analytics";
import { DATASETS } from "@/lib/exports";
import { formatTime } from "@/lib/format";

/** Export jobs of the project: progress while they run, download and reproduce when done. */
export function ExportsPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<ExportJob | null>(null);
  const jobs = useQuery({
    queryKey: queryKeys.exports(projectId),
    queryFn: () => api.get<PageType<ExportJob>>(`/api/v1/projects/${projectId}/exports`, { query: { limit: 200 } }),
    refetchInterval: (query) => (query.state.data?.items.some((j) => j.status === "queued" || j.status === "running") ? 3_000 : false),
  });
  const reproduce = useMutationToast({
    mutationFn: (id: string) => api.post<ExportJob>(`/api/v1/projects/${projectId}/exports/${id}/reproduce`, {}),
    invalidate: [queryKeys.exports(projectId)],
    success: t("Queued again with the same parameters"),
  });

  async function download(job: ExportJob) {
    try {
      await downloadFile(`/api/v1/projects/${projectId}/exports/${job.id}/download`, `${job.dataset}.${job.format}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const sorted = [...(jobs.data?.items ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const columns: ColumnDef<ExportJob, unknown>[] = [
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Data"), accessorKey: "dataset", cell: ({ getValue }) => DATASETS[getValue<keyof typeof DATASETS>()]?.label ?? getValue<string>() },
    { header: t("Format"), accessorKey: "format", cell: ({ getValue }) => getValue<string>().toUpperCase() },
    { header: t("Range"), accessorFn: (j) => String(j.parameters.time_from), cell: ({ row }) => { const p = row.original.parameters as { time_from: string; time_to: string; timezone: string }; return <span className="whitespace-nowrap text-xs">{t("{{from}} to {{to}}", { from: formatInZone(p.time_from, p.timezone, { timeStyle: undefined }), to: formatInZone(p.time_to, p.timezone, { timeStyle: undefined }) })}</span>; } },
    { header: t("Status"), accessorKey: "status", cell: ({ row }) => <span className="inline-flex items-center gap-2"><StatusBadge value={row.original.status} />{row.original.status === "running" && <span className="text-xs text-muted-foreground">{row.original.progress_rows.toLocaleString()} {t("rows")}</span>}</span> },
    { header: t("Rows"), accessorKey: "row_count", cell: ({ getValue }) => getValue<number | null>()?.toLocaleString() ?? "" },
    { header: t("Size"), accessorKey: "size_bytes", cell: ({ getValue }) => { const b = getValue<number | null>(); return b ? `${(b / 1e6).toFixed(b < 1e6 ? 2 : 1)} MB` : ""; } },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {row.original.status === "done" && <Button variant="outline" size="sm" onClick={() => void download(row.original)}><Download className="size-4" /> {t("Download")}</Button>}
          <Button variant="ghost" size="sm" aria-label={t("Reproduce")} onClick={() => reproduce.mutate(row.original.id)}><Repeat className="size-4" /></Button>
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("Exports")}
        description={t("Files generated on the server from explicit parameters; large ones run as jobs and stay available for seven days")}
        actions={<>
          <Button variant="outline" size="icon" onClick={() => jobs.refetch()} aria-label={t("Refresh")}><RefreshCw className="size-4" /></Button>
          <Button onClick={() => setOpen(true)}><Plus className="size-4" /> {t("New export")}</Button>
        </>}
      />
      <Page>
        {jobs.error && <Callout kind="error">{jobs.error.message}</Callout>}
        <DataTable columns={columns} data={sorted} searchable isLoading={jobs.isPending} emptyMessage={t("No exports yet. Small selections download at once from the Data explorer, larger ones become jobs here.")} onRowClick={setSelected} footer={jobs.data && `${jobs.data.items.length} exports`} />
      </Page>
      <ExportDialog projectId={projectId} open={open} onOpenChange={setOpen} />
      <Dialog open={selected !== null} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("Export")} {selected?.id.slice(0, 8)}</DialogTitle>
            <DialogDescription>{t("Parameters and, when done, the metadata that makes the file reproducible.")}</DialogDescription>
          </DialogHeader>
          {selected?.status === "failed" && <Callout kind="error">{selected.error_message ?? selected.error_code}</Callout>}
          {selected && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2">
                <div><span className="text-muted-foreground">{t("Status")}</span><div><StatusBadge value={selected.status} /></div></div>
                <div><span className="text-muted-foreground">{t("SHA-256")}</span><div className="truncate font-mono text-xs">{selected.sha256 ?? ""}</div></div>
                <div><span className="text-muted-foreground">{t("Started")}</span><div>{formatTime(selected.started_at)}</div></div>
                <div><span className="text-muted-foreground">{t("Finished")}</span><div>{formatTime(selected.finished_at)}</div></div>
                {selected.source_job_id && <div className="col-span-2"><span className="text-muted-foreground">{t("Reproduced from")}</span><div className="font-mono text-xs">{selected.source_job_id}</div></div>}
              </div>
              <div><div className="mb-1 font-medium">{t("Parameters")}</div><JsonView value={selected.parameters} /></div>
              {Object.keys(selected.metadata).length > 0 && <div><div className="mb-1 font-medium">{t("Metadata")}</div><JsonView value={selected.metadata} /></div>}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
