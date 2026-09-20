import { useTranslation } from "react-i18next";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";

import type { RecordRow } from "@/api/types";
import { formatInZone } from "@/lib/analytics";
import { formatDuration } from "@/lib/format";
import {
  cellOf,
  formatCell,
  type RecordColumn,
  type RecordSort,
} from "@/lib/records";

const ROW_HEIGHT = 32;
const FILTER_HEIGHT = 30;

function cellWidth(c: RecordColumn): number {
  return c.key === "time"
    ? 170
    : c.key === "entity" || c.key === "device" || c.key === "data_source"
      ? 150
      : c.key === "kinds" || c.key === "device_type"
        ? 140
        : 110;
}

/** The records table, virtualized (decision D143): only the rows in view render, so a year of
 * a device scrolls as one list. Wide content scrolls inside the container. */
export function VirtualTable({
  rows,
  columns,
  timezone,
  onRowClick,
  onRowHover,
  highlightTime = null,
  follow = true,
  height = 480,
  sort,
  onSort,
  filters,
  onFilter,
}: {
  rows: RecordRow[];
  columns: RecordColumn[];
  timezone: string;
  /** The column the rows are ordered by; a click on a header sorts by it, again reverses. */
  sort?: RecordSort;
  onSort?: (sort: RecordSort) => void;
  /** A filter per column, typed under its header (Tim, 2026-09-20). */
  filters?: Record<string, string>;
  onFilter?: (key: string, text: string) => void;
  onRowClick?: (row: RecordRow) => void;
  /** The pointer over a row, or over none (decision D154). */
  onRowHover?: (row: RecordRow | null) => void;
  /** The marked moment: its row is marked and, with `follow`, scrolled into view. */
  highlightTime?: string | null;
  follow?: boolean;
  height?: number | string;
}) {
  const { t } = useTranslation();
  const parent = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parent.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });
  const highlightMs = highlightTime ? Date.parse(highlightTime) : NaN;
  const highlightIndex = Number.isFinite(highlightMs)
    ? rows.findIndex((r) => Date.parse(r.time) === highlightMs)
    : -1;
  const scrolledFor = useRef<number | null>(null);
  useEffect(() => {
    if (!follow || highlightIndex < 0 || scrolledFor.current === highlightMs)
      return;
    scrolledFor.current = highlightMs;
    virtualizer.scrollToIndex(highlightIndex, { align: "center" });
  }, [follow, highlightIndex, highlightMs, virtualizer]);
  const width = columns.reduce((n, c) => n + cellWidth(c), 0);
  return (
    <div
      ref={parent}
      className="touch-pan-x touch-pan-y overscroll-contain overflow-auto rounded-md border"
      style={{ height }}
      onMouseLeave={() => onRowHover?.(null)}
    >
      <div style={{ minWidth: width }}>
        <div className="sticky top-0 z-10 border-b bg-muted text-xs">
          <div className="flex font-medium" style={{ height: ROW_HEIGHT }}>
            {columns.map((c) => (
              <button
                key={c.key}
                type="button"
                className="flex shrink-0 items-center truncate px-2 text-left hover:text-primary"
                style={{ width: cellWidth(c) }}
                title={
                  onSort
                    ? t("Sort by {{column}}", { column: t(c.label) })
                    : c.unit
                      ? `${t(c.label)} (${c.unit})`
                      : t(c.label)
                }
                onClick={() =>
                  onSort?.({
                    key: c.key,
                    direction:
                      sort?.key === c.key && sort.direction === "desc"
                        ? "asc"
                        : "desc",
                  })
                }
                aria-sort={
                  sort?.key === c.key
                    ? sort.direction === "asc"
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                {t(c.label)}
                {c.unit ? (
                  <span className="ml-1 text-muted-foreground">{c.unit}</span>
                ) : null}
                {sort?.key === c.key && (
                  <span className="ml-1 text-muted-foreground" aria-hidden>
                    {sort.direction === "asc" ? "▲" : "▼"}
                  </span>
                )}
              </button>
            ))}
          </div>
          {onFilter && (
            <div className="flex" style={{ height: FILTER_HEIGHT }}>
              {columns.map((c) => (
                <div
                  key={c.key}
                  className="shrink-0 px-1 py-0.5"
                  style={{ width: cellWidth(c) }}
                >
                  <input
                    type="text"
                    className="h-6 w-full rounded border bg-background px-1 font-normal"
                    value={filters?.[c.key] ?? ""}
                    placeholder={c.numeric ? "> 3.5" : t("filter")}
                    aria-label={t("Filter {{column}}", { column: t(c.label) })}
                    title={
                      c.numeric
                        ? t("> 3.5, <= 2, 3.5-4, or a number")
                        : t("A piece of the text")
                    }
                    onChange={(e) => onFilter(c.key, e.target.value)}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        <div
          className="relative"
          style={{ height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map((item) => {
            const row = rows[item.index];
            return (
              <div
                key={item.key}
                className={`absolute left-0 flex w-full border-b text-sm ${onRowClick ? "cursor-pointer hover:bg-muted/50" : ""} ${item.index === highlightIndex ? "bg-primary/10 font-medium" : ""}`}
                aria-current={
                  item.index === highlightIndex ? "true" : undefined
                }
                style={{
                  transform: `translateY(${item.start}px)`,
                  height: ROW_HEIGHT,
                }}
                onClick={() => onRowClick?.(row)}
                onMouseEnter={() => onRowHover?.(row)}
              >
                {columns.map((c) => (
                  <div
                    key={c.key}
                    className={`flex shrink-0 items-center truncate px-2 ${c.numeric ? "justify-end font-mono text-xs" : ""}`}
                    style={{ width: cellWidth(c) }}
                  >
                    {c.key === "time"
                      ? formatInZone(row.time, timezone)
                      : c.unit === "s" && typeof cellOf(row, c) === "number"
                        ? formatDuration(cellOf(row, c) as number)
                        : formatCell(cellOf(row, c))}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
