import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { RecordRow, RecordsCount, RecordsPage } from "@/api/types";

export interface RecordsSelection {
  entities: string[];
  devices: string[];
  from: string;
  to: string;
  /** device (the default) or all: whether the network's locations join the rows (D163). */
  sources?: "device" | "all";
}

type Status = "idle" | "loading" | "stopped" | "done" | "error";

interface Run {
  key: string;
  rows: RecordRow[];
  status: Status;
  error: string | null;
}

/**
 * The records of a selection, loaded page after page (decision D143): every request stays
 * bounded, the person sees a progress bar against the count and can stop; a new selection starts
 * over. The rows stay in the order the server gives them, newest first. The run's state is keyed
 * on the selection, so a change shows an empty list at once without a state reset in an effect.
 */
export function useRecords(
  projectId: string,
  selection: RecordsSelection | null,
) {
  const params = selection
    ? {
        entity_id: selection.entities,
        device_id: selection.devices,
        from: selection.from,
        to: selection.to,
        sources: selection.sources ?? "device",
      }
    : null;
  const count = useQuery({
    queryKey: queryKeys.recordsCount(projectId, params ?? {}),
    queryFn: () =>
      api.get<RecordsCount>(`/api/v1/projects/${projectId}/records/count`, {
        query: params ?? {},
      }),
    enabled: params !== null,
  });
  const [generation, setGeneration] = useState(0);
  const key = params ? `${JSON.stringify(params)}#${generation}` : "";
  const [run, setRun] = useState<Run>({
    key: "",
    rows: [],
    status: "idle",
    error: null,
  });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!key || !params) return;
    const abort = new AbortController();
    controller.current = abort;
    let cursor: string | null = null;
    let collected: RecordRow[] = [];
    (async () => {
      try {
        do {
          const page: RecordsPage = await api.get<RecordsPage>(
            `/api/v1/projects/${projectId}/records`,
            {
              query: { ...params, limit: 1000, ...(cursor ? { cursor } : {}) },
              signal: abort.signal,
            },
          );
          if (abort.signal.aborted) return;
          collected = [...collected, ...page.items];
          cursor = page.next_cursor ?? null;
          setRun({
            key,
            rows: collected,
            status: cursor ? "loading" : "done",
            error: null,
          });
        } while (cursor);
      } catch (e) {
        if (abort.signal.aborted) return;
        setRun({
          key,
          rows: collected,
          status: "error",
          error: e instanceof Error ? e.message : String(e),
        });
      }
    })();
    return () => abort.abort();
    // the key carries the selection and the restart generation
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, key]);

  const current: Run =
    run.key === key
      ? run
      : { key, rows: [], status: key ? "loading" : "idle", error: null };
  const stop = () => {
    controller.current?.abort();
    setRun({ ...current, status: "stopped" });
  };
  const restart = () => setGeneration((g) => g + 1);

  return {
    rows: current.rows,
    status: current.status,
    error: current.error,
    total: count.data?.count ?? null,
    stop,
    restart,
  };
}
