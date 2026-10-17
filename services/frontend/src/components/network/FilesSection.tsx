import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { FolderOpen } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { LogFilesExplorer, LogFilesViewSwitch } from "@/components/devices/LogFilesExplorer";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLogFilesView } from "@/hooks/useLogFilesView";

/**
 * The project's files, a section of the Offload page (Tim, 2026-10-17: the files explorer of
 * Protect Go, here for what was uploaded, and on the Offload page rather than a page of its
 * own): every log file of the project's devices, the SD card files of the offload stations
 * among them, as the device page's explorer shows them, newest first. The device is a column
 * and a filter, the search box matches any text of a row, and a click on a header sorts.
 * Uploading stays on the device's page, where a file belongs to one device.
 */
export function FilesSection({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { t } = useTranslation();
  const [view, setView] = useLogFilesView();
  const [deviceId, setDeviceId] = useState("");
  const files = useQuery({
    queryKey: queryKeys.projectLogFiles(projectId),
    queryFn: () => api.get<DeviceLogFile[]>(`/api/v1/projects/${projectId}/log-files`),
    refetchInterval: (q) =>
      q.state.data?.some((f) => f.status === "queued" || f.status === "processing")
        ? 3_000
        : false,
  });
  const devices = useMemo(() => {
    const seen = new Map<string, string>();
    for (const f of files.data ?? []) seen.set(f.device_id, f.device_name ?? f.device_id.slice(0, 8));
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [files.data]);
  const shown = useMemo(
    () => (files.data ?? []).filter((f) => !deviceId || f.device_id === deviceId),
    [files.data, deviceId],
  );
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <FolderOpen className="size-4" /> {t("Files")}
          {files.data && files.data.length > 0 && (
            <span className="text-sm font-normal text-muted-foreground">{shown.length}</span>
          )}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={deviceId || "all"} onValueChange={(v) => setDeviceId(v === "all" ? "" : v)}>
            <SelectTrigger className="h-8 w-48" aria-label={t("Device")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("All devices")}</SelectItem>
              {devices.map(([id, name]) => (
                <SelectItem key={id} value={id}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <LogFilesViewSwitch view={view} onView={setView} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {t(
          "Every file uploaded for the project's devices: the SD card files of the offload stations, the raw logs and the browser syncs, newest first. A click on a file opens its properties; the device's name opens its page, where files are uploaded.",
        )}
      </p>
      {files.error && <Callout kind="error">{files.error.message}</Callout>}
      <LogFilesExplorer
        files={shown}
        isLoading={files.isPending}
        canWrite={canWrite}
        view={view}
        invalidate={[queryKeys.projectLogFiles(projectId)]}
        withDevice
        projectId={projectId}
        defaultHidden={["acquisition_channel", "records", "size_bytes"]}
      />
    </section>
  );
}
