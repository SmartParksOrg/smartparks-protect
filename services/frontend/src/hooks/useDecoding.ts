import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AttributionJob, DecodingRead, DeviceLogFile, DeviceWalk } from "@/api/types";

/** How often a device's decoding read is polled while something runs, and while nothing
 * does: often enough for the bar to move, and a new upload, browser sync or walk shows within
 * half a minute. */
const ACTIVE_MS = 3_000;
const IDLE_MS = 30_000;

/** One thing being processed for a device (decision D366): a file (a log file upload, a
 * browser sync, a re-decode, or an offload station's card whose frames name the device), a
 * walk over the retained events of an identity that got the device (decision D121), or the
 * attribution job giving its records their project and entity (decision D206). */
export type Decoding =
  | {
      kind: "file";
      deviceId: string;
      /** The device the file belongs to: the device itself, or the station whose card it is. */
      deviceName: string | null;
      file: DeviceLogFile;
    }
  | {
      kind: "walk";
      deviceId: string;
      deviceName: string | null;
      walk: DeviceWalk;
    }
  | {
      kind: "attribution";
      deviceId: string;
      deviceName: string | null;
      job: AttributionJob;
    };

const busy = (read: DecodingRead | undefined) =>
  Boolean(read && (read.files.length || read.walks.length || read.attribution_job));

/** What is being processed for these devices: one read per device (decision D366), shared by
 * the live map's panels and the notice at the top of the device and entity pages. When the
 * last item finishes it refreshes what the page shows, since those records are the new data. */
export function useDecoding(
  devices: { id: string; name?: string | null }[],
  options: { enabled?: boolean } = {},
): Decoding[] {
  const client = useQueryClient();
  const reads = useQueries({
    queries: devices.map((d) => ({
      queryKey: queryKeys.decoding(d.id),
      queryFn: () => api.get<DecodingRead>(`/api/v1/devices/${d.id}/decoding`),
      enabled: options.enabled ?? true,
      refetchInterval: (q: { state: { data?: DecodingRead } }) =>
        busy(q.state.data) ? ACTIVE_MS : IDLE_MS,
    })),
  });
  const active: Decoding[] = reads.flatMap((r, i) => {
    const read = r.data;
    if (!read) return [];
    const device = devices[i];
    const name = device.name ?? null;
    return [
      ...read.files.map(
        (file): Decoding => ({
          kind: "file",
          deviceId: device.id,
          deviceName: file.device_name ?? name,
          file,
        }),
      ),
      ...read.walks.map(
        (walk): Decoding => ({ kind: "walk", deviceId: device.id, deviceName: name, walk }),
      ),
      ...(read.attribution_job
        ? [
            {
              kind: "attribution" as const,
              deviceId: device.id,
              deviceName: name,
              job: read.attribution_job,
            },
          ]
        : []),
    ];
  });
  const running = active.length > 0;
  const was = useRef(running);
  useEffect(() => {
    // the work just finished: the lists, the charts and the map hold new records now
    if (was.current && !running) void client.invalidateQueries();
    was.current = running;
  }, [running, client]);
  return active;
}

/** The share done of one item, 0 to 100, or null while nothing says how far it is. */
export function decodingPercent(item: Decoding): number | null {
  if (item.kind === "walk")
    return item.walk.total > 0 ? Math.min(100, (item.walk.done / item.walk.total) * 100) : 0;
  if (item.kind === "attribution")
    return item.job.records_total > 0
      ? Math.min(100, (item.job.records_done / item.job.records_total) * 100)
      : 0;
  if (item.file.status !== "processing" || item.file.frames_total === 0) return null;
  return Math.min(100, (item.file.frames_done / item.file.frames_total) * 100);
}
