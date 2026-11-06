import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { FileUp, ScrollText } from "lucide-react";
import { useRef } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile } from "@/api/types";
import { LogFilesExplorer, LogFilesViewSwitch } from "@/components/devices/LogFilesExplorer";
import { useLogFilesView } from "@/hooks/useLogFilesView";
import { LOG_FILE_ACCEPT, useLogFileUpload } from "@/hooks/useLogFileUpload";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Raw log files and browser syncs of a device as managed assets (architecture 25.6), shown as a
 * file explorer shows files (Tim, 2026-10-16: the rows of a card's 31 files ran to several
 * lines each): a list with one line per file, or tiles, switched at the top and remembered per
 * person; a click opens the file's properties, where the counts, the error, the trace, the
 * original and "decode again" live. Upload stays in the header, the same upload the page's
 * header button and the Devices list use (decision D367).
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
  const { uploadAll, isPending } = useLogFileUpload(deviceId);
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
                  multiple
                  accept={LOG_FILE_ACCEPT}
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files?.length) void uploadAll(e.target.files);
                    e.target.value = "";
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isPending}
                  onClick={() => input.current?.click()}
                >
                  <FileUp className="size-4" /> {isPending ? t("Uploading…") : t("Upload")}
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
