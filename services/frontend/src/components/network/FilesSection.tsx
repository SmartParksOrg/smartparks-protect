import { useTranslation } from "react-i18next";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { FolderOpen } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, OffloadOverview } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { LogFilesExplorer, LogFilesViewSwitch } from "@/components/devices/LogFilesExplorer";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLogFilesView } from "@/hooks/useLogFilesView";

const PAGE = 200;

/**
 * The project's files, a section of the Offload page (Tim, 2026-10-17: the files explorer of
 * Protect Go, here for what was uploaded, and on the Offload page rather than a page of its
 * own): every log file of the project's devices, the SD card files of the offload stations
 * among them, as the device page's explorer shows them, newest first. A page of 200 at a time
 * and "Load more" for the next (Protect's decision D143: never a wall), the device a filter the
 * server applies, the search box over the loaded rows, a click on a header to sort them.
 * Uploading stays on the device's page, where a file belongs to one device.
 */
export function FilesSection({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { t } = useTranslation();
  const [view, setView] = useLogFilesView();
  const [deviceId, setDeviceId] = useState("");
  // the devices to filter by come from the Offload overview, so every station and tracker is
  // offered, not only those whose files are loaded yet
  const overview = useQuery({
    queryKey: queryKeys.projectOffload(projectId),
    queryFn: () => api.get<OffloadOverview>(`/api/v1/projects/${projectId}/offload`),
  });
  const devices = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of overview.data?.stations ?? []) seen.set(s.device_id, s.device_name);
    for (const tr of overview.data?.trackers ?? []) seen.set(tr.device_id, tr.device_name);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [overview.data]);
  const files = useInfiniteQuery({
    queryKey: queryKeys.projectLogFiles(projectId, deviceId || null),
    queryFn: ({ pageParam }) =>
      api.get<DeviceLogFile[]>(`/api/v1/projects/${projectId}/log-files`, {
        query: {
          limit: PAGE,
          ...(pageParam ? { before: pageParam } : {}),
          ...(deviceId ? { device_id: deviceId } : {}),
        },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.length === PAGE ? lastPage[lastPage.length - 1].uploaded_at : null,
    refetchInterval: (q) =>
      q.state.data?.pages.some((page) =>
        page.some((f) => f.status === "queued" || f.status === "processing"),
      )
        ? 3_000
        : false,
  });
  const rows = useMemo(() => files.data?.pages.flat() ?? [], [files.data]);
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <FolderOpen className="size-4" /> {t("Files")}
          {rows.length > 0 && (
            <span className="text-sm font-normal text-muted-foreground">
              {files.hasNextPage ? t("{{count}} loaded", { count: rows.length }) : rows.length}
            </span>
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
        files={files.isPending ? undefined : rows}
        isLoading={files.isPending}
        canWrite={canWrite}
        view={view}
        invalidate={[queryKeys.projectLogFiles(projectId, deviceId || null)]}
        withDevice
        projectId={projectId}
        defaultHidden={["acquisition_channel", "records", "size_bytes"]}
      />
      {files.hasNextPage && (
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={files.isFetchingNextPage}
            onClick={() => void files.fetchNextPage()}
          >
            {files.isFetchingNextPage ? t("Loading…") : t("Load {{count}} more", { count: PAGE })}
          </Button>
        </div>
      )}
    </section>
  );
}
