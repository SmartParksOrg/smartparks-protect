import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Bluetooth,
  Download,
  FileText,
  FileUp,
  HardDrive,
  LayoutGrid,
  List,
  MoreHorizontal,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { api, downloadFile } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, OffloadUpload } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { LogFileDialog } from "@/components/devices/LogFileDialog";
import { TraceDialog } from "@/components/devices/ProvenancePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePreference } from "@/hooks/usePreference";
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

type View = "list" | "tiles";

/** A station's card: one JSONL file of the card, or a zip of its LOG folders (phase 42). */
function isStationUpload(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".jsonl") || name.endsWith(".zip");
}

/**
 * Raw log files and browser syncs of a device as managed assets (architecture 25.6), shown as a
 * file explorer shows files (Tim, 2026-10-16: the rows of a card's 31 files ran to several
 * lines each): a list with one line per file, or tiles, switched at the top and remembered per
 * person; a click opens the file's properties, where the counts, the error, the trace, the
 * original and "decode again" live. Upload stays in the header.
 */
export function LogFilesCard({ deviceId, canWrite }: { deviceId: string; canWrite: boolean }) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [trace, setTrace] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = usePreference<View>("log_files_view", "list");
  const files = useQuery({
    queryKey: queryKeys.logFiles(deviceId),
    queryFn: () => api.get<DeviceLogFile[]>(`/api/v1/devices/${deviceId}/log-files`),
    refetchInterval: (q) =>
      q.state.data?.some((f) => f.status === "queued" || f.status === "processing")
        ? 3_000
        : false,
  });
  const upload = useMutationToast({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      if (isStationUpload(file)) {
        // a station's card goes through its own endpoint: a zip becomes one row per file
        const result = await api.post<OffloadUpload>(`/api/v1/devices/${deviceId}/offload-files`, {
          body,
        });
        return { name: file.name, files: result.files.length, skipped: (result.skipped ?? []).length };
      }
      const row = await api.post<DeviceLogFile>(`/api/v1/devices/${deviceId}/log-files`, { body });
      return { name: row.original_filename, files: 1, skipped: 0 };
    },
    invalidate: [queryKeys.logFiles(deviceId), queryKeys.offloadStation(deviceId)],
    success: (r) =>
      r.files === 1 && r.skipped === 0
        ? `${r.name} uploaded, decoding`
        : t("{{name}}: {{files}} files uploaded, {{skipped}} skipped, decoding", r),
    onError: (error) =>
      toast.error(
        error.message.includes("uploaded before")
          ? t("This file was uploaded before for this device.")
          : error.message,
      ),
  });
  const redecode = useMutationToast({
    mutationFn: (id: string) => api.post<DeviceLogFile>(`/api/v1/log-files/${id}/redecode`),
    invalidate: [queryKeys.logFiles(deviceId)],
    success: t("Decoding the stored frames again"),
  });
  const download = (f: DeviceLogFile) =>
    downloadFile(`/api/v1/log-files/${f.id}/download`, f.original_filename).catch((e: Error) =>
      toast.error(e.message),
    );
  // the properties dialog reads the live row, so a processing file's bar moves while it is open
  const selected = files.data?.find((f) => f.id === selectedId) ?? null;

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

  const columns: ColumnDef<DeviceLogFile, unknown>[] = [
    { header: t("Name"), accessorKey: "original_filename", cell: ({ row }) => name(row.original) },
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
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="size-4" /> {t("Log files")}
            {files.data && files.data.length > 0 && (
              <span className="text-sm font-normal text-muted-foreground">{files.data.length}</span>
            )}
          </CardTitle>
          <div className="flex items-center gap-1">
            <div className="flex rounded-md border p-0.5" role="group" aria-label={t("View")}>
              <Button
                type="button"
                variant={view === "list" ? "secondary" : "ghost"}
                size="icon"
                className="size-7"
                aria-pressed={view === "list"}
                aria-label={t("List")}
                onClick={() => setView("list")}
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
                onClick={() => setView("tiles")}
              >
                <LayoutGrid className="size-4" />
              </Button>
            </div>
            {canWrite && (
              <>
                <input
                  ref={input}
                  type="file"
                  accept=".txt,.log,.jsonl,.zip,text/plain,application/zip"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) upload.mutate(file);
                    e.target.value = "";
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={upload.isPending}
                  onClick={() => input.current?.click()}
                >
                  <FileUp className="size-4" /> {upload.isPending ? t("Uploading…") : t("Upload")}
                </Button>
              </>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">
            {t(
              "Raw logs retrieved from the device: one frame per line as the OpenCollar BLE app exports them, the frames synced from this browser, or the files of an offload station's SD card (a .jsonl file, or a zip of its LOG folders). Every frame is a delivery; records already known from another path are recognised, not duplicated. A click on a file opens its properties.",
            )}
          </p>
          {view === "tiles" && files.data && files.data.length > 0 ? (
            tiles(files.data)
          ) : (
            <DataTable
              columns={columns}
              data={files.data}
              isLoading={files.isPending}
              // the card shares its row with another on a desktop: the kind is the icon, the
              // records, the period and the size are in the properties, the Columns menu
              // shows them
              defaultHidden={["acquisition_channel", "records", "period", "size_bytes"]}
              defaultHiddenSmall={["acquisition_channel", "records", "period", "size_bytes"]}
              onRowClick={(f) => setSelectedId(f.id)}
              emptyMessage={t("No log files yet.")}
              cardOf={(f) => (
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1 space-y-1">
                    {name(f)}
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
        </CardContent>
      </Card>
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
