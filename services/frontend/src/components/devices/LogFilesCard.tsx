import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { FileUp, ScrollText } from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, OffloadUpload } from "@/api/types";
import { LogFilesExplorer, LogFilesViewSwitch } from "@/components/devices/LogFilesExplorer";
import { useLogFilesView } from "@/hooks/useLogFilesView";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMutationToast } from "@/hooks/useMutationToast";

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
  const [view, setView] = useLogFilesView();

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
            <LogFilesViewSwitch view={view} onView={setView} />
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
          <LogFilesExplorer files={files.data} isLoading={files.isPending} canWrite={canWrite} view={view} invalidate={[queryKeys.logFiles(deviceId)]} />
        </CardContent>
      </Card>
    </>
  );
}
