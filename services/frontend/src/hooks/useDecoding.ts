import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile } from "@/api/types";

/** How often a device's files are read while one is being decoded, and while none is: often
 * enough for the bar to move, and a new upload or browser sync shows within half a minute. */
const ACTIVE_MS = 3_000;
const IDLE_MS = 30_000;

export interface Decoding {
  deviceId: string;
  deviceName: string | null;
  file: DeviceLogFile;
}

const decoding = (f: DeviceLogFile) =>
  f.status === "queued" || f.status === "processing";

/** The files of these devices the decoder is working on (a log file upload, a browser sync, a
 * re-decode), for the notice at the top of the device and entity pages. Shares the query of the
 * Data tab's log files card, and when the last file finishes it refreshes what the page shows,
 * since those records are the new data. */
export function useDecoding(
  devices: { id: string; name?: string | null }[],
): Decoding[] {
  const client = useQueryClient();
  const results = useQueries({
    queries: devices.map((d) => ({
      queryKey: queryKeys.logFiles(d.id),
      queryFn: () =>
        api.get<DeviceLogFile[]>(`/api/v1/devices/${d.id}/log-files`),
      refetchInterval: (q: { state: { data?: DeviceLogFile[] } }) =>
        q.state.data?.some(decoding) ? ACTIVE_MS : IDLE_MS,
    })),
  });
  const active = results.flatMap((r, i) =>
    (r.data ?? []).filter(decoding).map((file) => ({
      deviceId: devices[i].id,
      deviceName: devices[i].name ?? null,
      file,
    })),
  );
  const busy = active.length > 0;
  const was = useRef(busy);
  useEffect(() => {
    // the decode just finished: the lists, the charts and the map hold new records now
    if (was.current && !busy) void client.invalidateQueries();
    was.current = busy;
  }, [busy, client]);
  return active;
}
