import { useTranslation } from "react-i18next";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { TrafficRow } from "@/api/types";
import { TrafficTable } from "@/components/network/TrafficTable";
import { WindowSelect } from "@/components/network/WindowSelect";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { windowLabel } from "@/lib/windows";

const EVENT_TYPES = [
  "uplink",
  "join",
  "status",
  "downlink_ack",
  "downlink_transmitted",
  "log",
  "location",
];
const PAGE = 50;
/** The statuses "Problems only" narrows to: refused by the decoder, or of an identity no
 * device holds. A repeat is not a problem. */
const PROBLEM_STATUSES = ["failed", "unassigned"];

/**
 * One device's traffic on its Traffic tab (decision D352, Tim, 2026-10-21: the place to start
 * when something is going on with a device): the window presets of the Traffic page, a type
 * filter, "Problems only", and pages of fifty loaded on after one another with the count of
 * the window, refreshed every fifteen seconds. Every column stays on a phone, the time in
 * view while the rest scrolls sideways.
 */
export function DeviceTraffic({
  projectId,
  deviceId,
  onSelect,
}: {
  projectId: string;
  deviceId: string;
  onSelect: (row: TrafficRow) => void;
}) {
  const { t } = useTranslation();
  const [hours, setHours] = useState(168);
  const [eventType, setEventType] = useState("");
  const [problems, setProblems] = useState(false);
  // the window's start is fixed when the controls change, so the pages and the count agree
  const [anchor, setAnchor] = useState(() => Date.now());
  const from = new Date(anchor - hours * 3600_000).toISOString();
  const filters = {
    device_id: deviceId,
    from,
    event_type: eventType || undefined,
    status: problems ? PROBLEM_STATUSES : undefined,
  };
  const keyParams = { deviceId, hours, eventType, problems, anchor };
  const pages = useInfiniteQuery({
    queryKey: queryKeys.traffic(projectId, keyParams),
    queryFn: ({ pageParam }) =>
      api.get<TrafficRow[]>(`/api/v1/projects/${projectId}/traffic`, {
        query: {
          ...filters,
          limit: PAGE,
          before: pageParam?.before,
          before_id: pageParam?.id,
        },
      }),
    initialPageParam: undefined as { before: string; id: number } | undefined,
    getNextPageParam: (last) =>
      last.length < PAGE
        ? undefined
        : {
            before: last[last.length - 1].ingested_at,
            id: last[last.length - 1].source_event_id,
          },
    refetchInterval: 15_000,
  });
  const count = useQuery({
    queryKey: [...queryKeys.traffic(projectId, keyParams), "count"],
    queryFn: () =>
      api.get<{ count: number }>(`/api/v1/projects/${projectId}/traffic/count`, {
        query: filters,
      }),
    refetchInterval: 15_000,
  });
  const rows = pages.data?.pages.flat();
  const reset = () => setAnchor(Date.now());
  const footer =
    rows && count.data
      ? t("{{shown}} of {{count}} messages, {{window}}", {
          shown: rows.length,
          count: count.data.count,
          window: windowLabel(hours, t).toLowerCase(),
        })
      : undefined;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
        <Select
          value={eventType || "all"}
          onValueChange={(v) => {
            setEventType(v === "all" ? "" : v);
            reset();
          }}
        >
          <SelectTrigger className="w-full sm:w-44" aria-label={t("Type")}>
            <SelectValue placeholder={t("All types")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("All types")}</SelectItem>
            {EVENT_TYPES.map((type) => (
              <SelectItem key={type} value={type}>
                {type}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <WindowSelect
          hours={hours}
          onChange={(h) => {
            setHours(h);
            reset();
          }}
          className="w-full sm:w-40"
        />
        <Button
          type="button"
          size="sm"
          variant={problems ? "default" : "outline"}
          aria-pressed={problems}
          onClick={() => {
            setProblems((v) => !v);
            reset();
          }}
        >
          {t("Problems only")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            reset();
            void pages.refetch();
          }}
          aria-label={t("Refresh")}
        >
          <RefreshCw className="size-4" /> {t("Refresh")}
        </Button>
      </div>
      <TrafficTable
        rows={rows}
        isLoading={pages.isPending}
        emptyMessage={
          problems
            ? t("No failed or unassigned messages in this window.")
            : t("No messages in this window.")
        }
        onSelect={onSelect}
        footer={
          <span className="flex flex-wrap items-center gap-2">
            {footer}
            {pages.hasNextPage && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={pages.isFetchingNextPage}
                onClick={() => void pages.fetchNextPage()}
              >
                {pages.isFetchingNextPage ? t("Loading…") : t("Load more")}
              </Button>
            )}
          </span>
        }
      />
    </div>
  );
}
