import { useTranslation } from "react-i18next";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Bluetooth,
  Download,
  FileText,
  HardDrive,
  LayoutGrid,
  List,
  MoreHorizontal,
  RefreshCw,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Link } from "react-router";

import { api, downloadFile } from "@/api/client";
import type { DeviceLogFile } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { LogFileDialog } from "@/components/devices/LogFileDialog";
import { TraceDialog } from "@/components/devices/ProvenancePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMutationToast } from "@/hooks/useMutationToast";
import type { LogFilesView } from "@/hooks/useLogFilesView";
import { formatAgo, formatTime } from "@/lib/format";
import {
  folderOf,
  kindLabel,
  type LogFileKind,
  kindOf,
  percentDone,
  sizeLabel,
  summaryOf,
} from "@/lib/logFiles";

const KIND_ICON: Record<LogFileKind, typeof FileText> = {
  raw_log: FileText,
  browser_sync: Bluetooth,
  station_card: HardDrive,
  other: FileText,
};

/** The two view buttons, list or tiles, for the header of whatever holds the explorer. */
export function LogFilesViewSwitch({ view, onView }: { view: LogFilesView; onView: (view: LogFilesView) => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex rounded-md border p-0.5" role="group" aria-label={t("View")}>
      <Button
        type="button"
        variant={view === "list" ? "secondary" : "ghost"}
        size="icon"
        className="size-7"
        aria-pressed={view === "list"}
        aria-label={t("List")}
        onClick={() => onView("list")}
      >
        <List className="size-4" />
      </Button>
      <Button
        type="button"
        variant={view === "tiles" ? "secondary" : "ghost"}
        size="icon"
        className="size-7"
        aria-pressed={view === "tiles"}
        aria-label={t("Tiles")}
        onClick={() => onView("tiles")}
      >
        <LayoutGrid className="size-4" />
      </Button>
    </div>
  );
}

/**
 * The files as a file explorer shows them (Tim, 2026-10-16: the rows of a card's 31 files ran
 * to several lines each): a list with one line per file, or tiles; a click opens the file's
 * properties, where the counts, the error, the trace, the original and "decode again" live.
 * One component for a device's card and for the project's Files page (Tim, 2026-10-17), which
 * adds the device's name as a column and a link to its page.
 */
export function LogFilesExplorer({
  files,
  isLoading,
  canWrite,
  view,
  invalidate,
  withDevice = false,
  projectId,
  defaultHidden = ["acquisition_channel", "records", "period", "size_bytes"],
}: {
  files: DeviceLogFile[] | undefined;
  isLoading: boolean;
  canWrite: boolean;
  view: LogFilesView;
  /** The query keys a redecode refreshes. */
  invalidate: readonly (readonly unknown[])[];
  withDevice?: boolean;
  projectId?: string;
  defaultHidden?: string[];
}) {
  const { t } = useTranslation();
  const [trace, setTrace] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const redecode = useMutationToast({
    mutationFn: (id: string) => api.post<DeviceLogFile>(`/api/v1/log-files/${id}/redecode`),
    invalidate: [...invalidate],
    success: t("Decoding the stored frames again"),
  });
  const download = (f: DeviceLogFile) =>
    downloadFile(`/api/v1/log-files/${f.id}/download`, f.original_filename).catch((e: Error) =>
      toast.error(e.message),
    );
  // the properties dialog reads the live row, so a processing file's bar moves while it is open
  const selected = files?.find((f) => f.id === selectedId) ?? null;

  const menu = (f: DeviceLogFile) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={t("Actions for {{name}}", { name: f.original_filename })}
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem onSelect={() => setSelectedId(f.id)}>{t("Properties")}</DropdownMenuItem>
        {f.trace_id && (
          <DropdownMenuItem onSelect={() => setTrace(f.trace_id)}>{t("Trace")}</DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => void download(f)}>
          <Download className="size-4" /> {t("Download the original")}
        </DropdownMenuItem>
        {canWrite && (
          <DropdownMenuItem
            disabled={f.status === "processing" || redecode.isPending}
            onSelect={() => redecode.mutate(f.id)}
          >
            <RefreshCw className="size-4" /> {t("Decode again")}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const name = (f: DeviceLogFile, className = "") => {
    const Icon = KIND_ICON[kindOf(f.acquisition_channel)];
    const folder = folderOf(f);
    return (
      <span className={`flex min-w-0 items-center gap-2 ${className}`}>
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 max-w-[14rem] truncate font-medium" title={f.original_filename}>
          {folder && <span className="font-normal text-muted-foreground">{folder}/</span>}
          {f.original_filename}
        </span>
      </span>
    );
  };
  const status = (f: DeviceLogFile) => {
    const percent = f.status === "processing" ? percentDone(f) : null;
    return (
      <span className="inline-flex items-center gap-1.5">
        <StatusBadge value={f.status} />
        {percent !== null && <span className="text-xs text-muted-foreground">{percent}%</span>}
      </span>
    );
  };


  const device = (f: DeviceLogFile) =>
    projectId ? (
      <Link
        className="underline-offset-4 hover:underline"
        to={`/projects/${projectId}/devices/${f.device_id}`}
        onClick={(e) => e.stopPropagation()}
      >
        {f.device_name ?? f.device_id.slice(0, 8)}
      </Link>
    ) : (
      <span>{f.device_name ?? f.device_id.slice(0, 8)}</span>
    );

  const columns: ColumnDef<DeviceLogFile, unknown>[] = [
    { header: t("Name"), accessorKey: "original_filename", cell: ({ row }) => name(row.original) },
    ...(withDevice
      ? [{ header: t("Device"), accessorKey: "device_name", cell: ({ row }: { row: { original: DeviceLogFile } }) => device(row.original) } satisfies ColumnDef<DeviceLogFile, unknown>]
      : []),
    {
      header: t("Kind"),
      accessorKey: "acquisition_channel",
      cell: ({ row }) => (
        <Badge variant="outline">{kindLabel(kindOf(row.original.acquisition_channel), t)}</Badge>
      ),
    },
    { header: t("Status"), accessorKey: "status", cell: ({ row }) => status(row.original) },
    {
      header: t("Frames"),
      accessorKey: "frames_total",
      cell: ({ row }) => (
        <span className="tabular-nums">
          {row.original.frames_total}
          {row.original.frames_failed > 0 && (
            <span className="text-destructive"> ({row.original.frames_failed})</span>
          )}
        </span>
      ),
    },
    {
      header: t("Records"),
      id: "records",
      cell: ({ row }) => (
        <span className="tabular-nums" title={t("new, known through another path")}>
          {row.original.records_new}
          <span className="text-muted-foreground"> / {row.original.records_duplicate}</span>
        </span>
      ),
    },
    {
      header: t("Period"),
      id: "period",
      cell: ({ row }) =>
        row.original.period_start && row.original.period_end ? (
          <span className="whitespace-nowrap text-xs">
            {formatTime(row.original.period_start)} {t("to")} {formatTime(row.original.period_end)}
          </span>
        ) : (
          ""
        ),
    },
    {
      header: t("Size"),
      accessorKey: "size_bytes",
      cell: ({ getValue }) => <span className="tabular-nums">{sizeLabel(getValue<number>())}</span>,
    },
    {
      header: t("Uploaded"),
      accessorKey: "uploaded_at",
      cell: ({ getValue }) => (
        <span className="whitespace-nowrap" title={formatTime(getValue<string>())}>
          {formatAgo(getValue<string>())}
        </span>
      ),
    },
    { header: "", id: "actions", cell: ({ row }) => menu(row.original) },
  ];


  const tiles = (rows: DeviceLogFile[]) => (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3 2xl:grid-cols-4">
      {rows.map((f) => {
        const Icon = KIND_ICON[kindOf(f.acquisition_channel)];
        const folder = folderOf(f);
        return (
          <div
            key={f.id}
            role="button"
            tabIndex={0}
            onClick={() => setSelectedId(f.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") setSelectedId(f.id);
            }}
            className="relative flex min-w-0 cursor-pointer flex-col gap-1 rounded-md border p-3 text-left hover:bg-muted/60"
          >
            <div className="absolute right-1 top-1">{menu(f)}</div>
            <Icon className="size-8 text-muted-foreground" />
            <div className="line-clamp-2 break-all text-sm font-medium" title={f.original_filename}>
              {folder && <span className="font-normal text-muted-foreground">{folder}/</span>}
              {f.original_filename}
            </div>
            <div>{status(f)}</div>
            <div className="line-clamp-2 text-xs text-muted-foreground">{summaryOf(f, t)}</div>
            <div className="text-xs text-muted-foreground">
              {sizeLabel(f.size_bytes)} · {formatAgo(f.uploaded_at)}
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <>
      {view === "tiles" && files && files.length > 0 ? (
        tiles(files)
      ) : (
        <DataTable
          columns={columns}
          data={files}
          isLoading={isLoading}
          defaultHidden={defaultHidden}
          defaultHiddenSmall={defaultHidden}
          onRowClick={(f) => setSelectedId(f.id)}
          emptyMessage={t("No log files yet.")}
          searchable={withDevice}
          cardOf={(f) => (
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1 space-y-1">
                {name(f)}
                {withDevice && <div className="text-xs text-muted-foreground">{device(f)}</div>}
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  {status(f)}
                  <span className="text-muted-foreground">
                    {sizeLabel(f.size_bytes)} · {formatAgo(f.uploaded_at)}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">{summaryOf(f, t)}</div>
              </div>
              {menu(f)}
            </div>
          )}
        />
      )}
      <LogFileDialog
        file={selected}
        canWrite={canWrite}
        onClose={() => setSelectedId(null)}
        onTrace={(id) => {
          setSelectedId(null);
          setTrace(id);
        }}
        onRedecode={(id) => redecode.mutate(id)}
        redecoding={redecode.isPending}
      />
      <TraceDialog traceId={trace} onClose={() => setTrace(null)} />
    </>
  );
}
