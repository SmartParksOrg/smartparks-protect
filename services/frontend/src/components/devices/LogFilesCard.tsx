import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Download, FileUp, RefreshCw, ScrollText } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { api, downloadFile } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, OffloadUpload } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TraceDialog } from "@/components/devices/ProvenancePanel";
import { ProgressBar } from "@/components/common/ProgressBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatAgo, formatTime } from "@/lib/format";

const CHANNEL_LABEL: Record<string, string> = {
  log_file: "uploaded file",
  webble: "browser sync",
  lp0: "station card",
};

/** A station's card: one JSONL file of the card, or a zip of its LOG folders (phase 42). */
function isStationUpload(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".jsonl") || name.endsWith(".zip");
}

/** How far the decoder is with a file: the frames done of the frames in the file, as a bar
 * with the percentage; the row is refetched every few seconds while it is processing. */
function Progress({ f }: { f: DeviceLogFile }) {
  const { t } = useTranslation();
  if (f.frames_total === 0)
    return (
      <span className="text-muted-foreground">{t("reading the file")}</span>
    );
  const percent = Math.min(
    100,
    Math.floor((f.frames_done / f.frames_total) * 100),
  );
  return (
    <div className="max-w-xs space-y-1">
      <div className="text-muted-foreground">
        {t("{{done}} of {{total}} frames decoded, {{percent}}%", {
          done: f.frames_done,
          total: f.frames_total,
          percent,
        })}
      </div>
      <ProgressBar percent={percent} />
    </div>
  );
}

function Counts({ f }: { f: DeviceLogFile }) {
  const { t } = useTranslation();
  if (f.status === "queued")
    return (
      <span className="text-muted-foreground">
        {t("waiting for the decoder")}
      </span>
    );
  if (f.status === "processing") return <Progress f={f} />;
  return (
    <span className="text-muted-foreground">
      {t(
        "{{frames}} frames, {{fresh}} new, {{known}} known through another path",
        {
          frames: f.frames_total,
          fresh: f.records_new,
          known: f.records_duplicate,
        },
      )}
      {f.frames_failed > 0
        ? t(", {{count}} malformed", { count: f.frames_failed })
        : ""}
      {f.period_start && f.period_end
        ? `, ${formatTime(f.period_start)} to ${formatTime(f.period_end)}`
        : ""}
      {f.firmware_version ? `, firmware ${f.firmware_version}` : ""}
      {f.acquisition_channel === "lp0" && <StationCounts f={f} />}
    </span>
  );
}

/** What a station's file adds to the counts: frames a station saved again, frames of trackers
 * nobody named yet, frames of a tracker without keys (phase 42, decision D321). */
function StationCounts({ f }: { f: DeviceLogFile }) {
  const { t } = useTranslation();
  const a = f.attributes as {
    frames_repeated?: number;
    frames_retained?: number;
    errors?: Record<string, number>;
    folder?: string;
  };
  const withoutKeys = a.errors?.CREDENTIALS_MISSING ?? 0;
  const unverified = a.errors?.PAYLOAD_DECODE_FAILED ?? 0;
  return (
    <>
      {a.frames_repeated
        ? t(", {{count}} repeated", { count: a.frames_repeated })
        : ""}
      {a.frames_retained
        ? t(", {{count}} of trackers not known yet", {
            count: a.frames_retained,
          })
        : ""}
      {withoutKeys
        ? t(", {{count}} of a tracker without keys", { count: withoutKeys })
        : ""}
      {unverified
        ? t(", {{count}} that did not verify", { count: unverified })
        : ""}
      {a.folder ? ` · ${a.folder}` : ""}
    </>
  );
}

/** Raw log files and browser syncs of a device as managed assets (architecture 25.6): upload,
 * status and counts, the original for download, decode again after a decoder update. */
export function LogFilesCard({
  deviceId,
  canWrite,
}: {
  deviceId: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [trace, setTrace] = useState<string | null>(null);
  const files = useQuery({
    queryKey: queryKeys.logFiles(deviceId),
    queryFn: () =>
      api.get<DeviceLogFile[]>(`/api/v1/devices/${deviceId}/log-files`),
    refetchInterval: (q) =>
      q.state.data?.some(
        (f) => f.status === "queued" || f.status === "processing",
      )
        ? 3_000
        : false,
  });
  const upload = useMutationToast({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      if (isStationUpload(file)) {
        // a station's card goes through its own endpoint: a zip becomes one row per file
        const result = await api.post<OffloadUpload>(
          `/api/v1/devices/${deviceId}/offload-files`,
          { body },
        );
        return {
          name: file.name,
          files: result.files.length,
          skipped: (result.skipped ?? []).length,
        };
      }
      const row = await api.post<DeviceLogFile>(
        `/api/v1/devices/${deviceId}/log-files`,
        { body },
      );
      return { name: row.original_filename, files: 1, skipped: 0 };
    },
    invalidate: [
      queryKeys.logFiles(deviceId),
      queryKeys.offloadStation(deviceId),
    ],
    success: (r) =>
      r.files === 1 && r.skipped === 0
        ? `${r.name} uploaded, decoding`
        : t(
            "{{name}}: {{files}} files uploaded, {{skipped}} skipped, decoding",
            r,
          ),
    onError: (error) =>
      toast.error(
        error.message.includes("uploaded before")
          ? t("This file was uploaded before for this device.")
          : error.message,
      ),
  });
  const redecode = useMutationToast({
    mutationFn: (id: string) =>
      api.post<DeviceLogFile>(`/api/v1/log-files/${id}/redecode`),
    invalidate: [queryKeys.logFiles(deviceId)],
    success: t("Decoding the stored frames again"),
  });
  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="size-4" /> {t("Log files")}
          </CardTitle>
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
                <FileUp className="size-4" />{" "}
                {upload.isPending ? t("Uploading…") : t("Upload raw log")}
              </Button>
            </>
          )}
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">
            {t(
              "Raw logs retrieved from the device: one frame per line as the OpenCollar BLE app exports them, the frames synced from this browser, or the files of an offload station's SD card (a .jsonl file, or a zip of its LOG folders). Every frame is a delivery; records already known from another path are recognised, not duplicated.",
            )}
          </p>
          {files.isSuccess && files.data.length === 0 && (
            <div className="text-muted-foreground">
              {t("No log files yet.")}
            </div>
          )}
          <ul className="divide-y">
            {files.data?.map((f) => (
              <li key={f.id} className="space-y-1 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{f.original_filename}</span>
                  <Badge variant="outline">
                    {CHANNEL_LABEL[f.acquisition_channel] ??
                      f.acquisition_channel}
                  </Badge>
                  <StatusBadge value={f.status} />
                  <span className="text-xs text-muted-foreground">
                    {t("{{size}} kB, {{ago}}", {
                      size: Math.round(f.size_bytes / 1024),
                      ago: formatAgo(f.uploaded_at),
                    })}
                    {f.ble_synced_at
                      ? t(", read from the device {{time}}", {
                          time: formatTime(f.ble_synced_at),
                        })
                      : ""}
                  </span>
                  <span className="ml-auto flex gap-1">
                    {f.trace_id && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setTrace(f.trace_id)}
                      >
                        {t("trace")}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        downloadFile(
                          `/api/v1/log-files/${f.id}/download`,
                          f.original_filename,
                        ).catch((e: Error) => toast.error(e.message))
                      }
                    >
                      <Download className="size-4" /> {t("original")}
                    </Button>
                    {canWrite && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={
                          f.status === "processing" || redecode.isPending
                        }
                        onClick={() => redecode.mutate(f.id)}
                      >
                        <RefreshCw className="size-4" /> {t("decode again")}
                      </Button>
                    )}
                  </span>
                </div>
                <div className="text-xs">
                  <Counts f={f} />
                </div>
                {f.error_message && (
                  <div className="text-xs text-destructive">
                    {f.error_code}: {f.error_message}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <TraceDialog traceId={trace} onClose={() => setTrace(null)} />
    </>
  );
}
