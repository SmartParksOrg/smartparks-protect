import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";

import type { RecordRow } from "@/api/types";
import { formatInZone } from "@/lib/analytics";
import { cellOf, formatCell, type RecordColumn } from "@/lib/records";

const ROW_HEIGHT = 32;

function cellWidth(c: RecordColumn): number {
  return c.key === "time"
    ? 170
    : c.key === "entity" || c.key === "device"
      ? 150
      : 110;
}

/** The records table, virtualized (decision D143): only the rows in view render, so a year of
 * a collar scrolls as one list. Wide content scrolls inside the container. */
export function VirtualTable({
  rows,
  columns,
  timezone,
  onRowClick,
  highlightTime = null,
  height = 480,
}: {
  rows: RecordRow[];
  columns: RecordColumn[];
  timezone: string;
  onRowClick?: (row: RecordRow) => void;
  /** The moment a link came from: its row is marked and scrolled into view once it loads. */
  highlightTime?: string | null;
  height?: number;
}) {
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
    if (highlightIndex < 0 || scrolledFor.current === highlightMs) return;
    scrolledFor.current = highlightMs;
    virtualizer.scrollToIndex(highlightIndex, { align: "center" });
  }, [highlightIndex, highlightMs, virtualizer]);
  const width = columns.reduce((n, c) => n + cellWidth(c), 0);
  return (
    <div
      ref={parent}
      className="overflow-auto rounded-md border"
      style={{ height }}
    >
      <div style={{ minWidth: width }}>
        <div
          className="sticky top-0 z-10 flex border-b bg-muted text-xs font-medium"
          style={{ height: ROW_HEIGHT }}
        >
          {columns.map((c) => (
            <div
              key={c.key}
              className="flex shrink-0 items-center truncate px-2"
              style={{ width: cellWidth(c) }}
              title={c.unit ? `${c.label} (${c.unit})` : c.label}
            >
              {c.label}
              {c.unit ? (
                <span className="ml-1 text-muted-foreground">{c.unit}</span>
              ) : null}
            </div>
          ))}
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
              >
                {columns.map((c) => (
                  <div
                    key={c.key}
                    className={`flex shrink-0 items-center truncate px-2 ${c.numeric ? "justify-end font-mono text-xs" : ""}`}
                    style={{ width: cellWidth(c) }}
                  >
                    {c.key === "time"
                      ? formatInZone(row.time, timezone)
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
