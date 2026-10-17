import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { LogFilesExplorer, LogFilesViewSwitch } from "@/components/devices/LogFilesExplorer";
import { useLogFilesView } from "@/hooks/useLogFilesView";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePermissions } from "@/hooks/useProjects";

/**
 * The project's files in one place (Tim, 2026-10-17: the files explorer of Protect Go, here
 * for what was uploaded): every log file of the project's devices, the SD card files of the
 * offload stations among them, as the device page's explorer shows them, with the device as a
 * column and a filter, newest first. Uploading stays on the device's page, where the file
 * belongs to one device.
 */
export function FilesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const { can } = usePermissions(projectId);
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
    <>
      <PageHeader
        title={t("Files")}
        description={t(
          "Every file uploaded for the project's devices: the SD card files of the offload stations, the raw logs and the browser syncs, newest first. A click on a file opens its properties; the device's name opens its page, where files are uploaded.",
        )}
        actions={
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
        }
      />
      <Page>
        {files.error && <Callout kind="error">{files.error.message}</Callout>}
        <LogFilesExplorer
          files={shown}
          isLoading={files.isPending}
          canWrite={can("devices:control")}
          view={view}
          invalidate={[queryKeys.projectLogFiles(projectId)]}
          withDevice
          projectId={projectId}
          defaultHidden={["acquisition_channel", "records", "size_bytes"]}
        />
      </Page>
    </>
  );
}
