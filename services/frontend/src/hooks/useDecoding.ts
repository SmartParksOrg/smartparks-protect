import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, DeviceWalk } from "@/api/types";

/** How often a device's files and walks are read while one is being decoded, and while none
 * is: often enough for the bar to move, and a new upload, browser sync or walk shows within
 * half a minute. */
const ACTIVE_MS = 3_000;
const IDLE_MS = 30_000;

/** One thing the decoder is working on for a device: a file (a log file upload, a browser
 * sync, a re-decode) or a walk over the retained events of an identity that got the device
 * (decision D121). */
export type Decoding =
  | {
      kind: "file";
      deviceId: string;
      deviceName: string | null;
      file: DeviceLogFile;
    }
  | {
      kind: "walk";
      deviceId: string;
      deviceName: string | null;
      walk: DeviceWalk;
    };

const decoding = (f: DeviceLogFile) =>
  f.status === "queued" || f.status === "processing";

/** What the decoder is working on for these devices, for the notice at the top of the device
 * and entity pages. Shares the query of the Data tab's log files card, and when the last file
 * or walk finishes it refreshes what the page shows, since those records are the new data. */
export function useDecoding(
  devices: { id: string; name?: string | null }[],
): Decoding[] {
  const client = useQueryClient();
  const files = useQueries({
    queries: devices.map((d) => ({
      queryKey: queryKeys.logFiles(d.id),
      queryFn: () =>
        api.get<DeviceLogFile[]>(`/api/v1/devices/${d.id}/log-files`),
      refetchInterval: (q: { state: { data?: DeviceLogFile[] } }) =>
        q.state.data?.some(decoding) ? ACTIVE_MS : IDLE_MS,
    })),
  });
  const walks = useQueries({
    queries: devices.map((d) => ({
      queryKey: queryKeys.deviceWalks(d.id),
      queryFn: () => api.get<DeviceWalk[]>(`/api/v1/devices/${d.id}/walks`),
      refetchInterval: (q: { state: { data?: DeviceWalk[] } }) =>
        q.state.data?.length ? ACTIVE_MS : IDLE_MS,
    })),
  });
  const active: Decoding[] = [
    ...files.flatMap((r, i) =>
      (r.data ?? []).filter(decoding).map((file): Decoding => ({
        kind: "file",
        deviceId: devices[i].id,
        deviceName: devices[i].name ?? null,
        file,
      })),
    ),
    ...walks.flatMap((r, i) =>
      (r.data ?? []).map((walk): Decoding => ({
        kind: "walk",
        deviceId: devices[i].id,
        deviceName: devices[i].name ?? null,
        walk,
      })),
    ),
  ];
  const busy = active.length > 0;
  const was = useRef(busy);
  useEffect(() => {
    // the decode just finished: the lists, the charts and the map hold new records now
    if (was.current && !busy) void client.invalidateQueries();
    was.current = busy;
  }, [busy, client]);
  return active;
}
