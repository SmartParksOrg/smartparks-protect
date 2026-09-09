import { useTranslation } from "react-i18next";

import type { RecordRow } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatInZone } from "@/lib/analytics";
import { cellOf, formatCell, type RecordColumn } from "@/lib/records";

/** A value that is a JSON object or list, laid out one field per line; null otherwise. */
function structured(value: unknown): string | null {
  if (typeof value !== "string" || !/^[[{]/.test(value.trim())) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed === null || typeof parsed !== "object") return null;
    return JSON.stringify(parsed, null, 1)
      .replace(/^[{[]\n|\n[}\]]$/g, "")
      .replace(/^ /gm, "");
  } catch {
    return null;
  }
}

/**
 * One record, plainly (Tim, 2026-09-09: a row click is not a traffic review): the moment, who
 * it belongs to, the position and the values of that moment, one line each. The source event
 * and its trace stay one link away for the rare look at the delivery itself.
 */
export function RecordDialog({
  row,
  columns,
  timezone,
  onClose,
  onSourceEvent,
}: {
  row: RecordRow | null;
  columns: RecordColumn[];
  timezone: string;
  onClose: () => void;
  onSourceEvent: (id: number, ingestedAt: string) => void;
}) {
  const { t } = useTranslation();
  const lines = row
    ? columns
        .filter((c) => c.key !== "time")
        .map((c) => ({ column: c, value: cellOf(row, c) }))
        .filter((l) => l.value !== null && l.value !== "")
    : [];
  return (
    <Dialog open={row !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {row
              ? formatInZone(row.time, timezone, { timeStyle: "medium" })
              : ""}
          </DialogTitle>
          <DialogDescription>
            {row?.entity_name ?? row?.device_name ?? ""}
            {row?.entity_name && row.device_name ? ` · ${row.device_name}` : ""}
          </DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-4 gap-y-1.5 text-sm">
          {lines.map(({ column, value }) => (
            <div key={column.key} className="contents">
              <dt className="truncate text-muted-foreground">{column.label}</dt>
              <dd className="min-w-0 text-right font-mono text-xs tabular-nums">
                {structured(value) ? (
                  <pre className="max-h-40 overflow-auto rounded bg-muted p-1.5 text-left whitespace-pre-wrap break-all">
                    {structured(value)}
                  </pre>
                ) : (
                  <span className="break-all">{formatCell(value)}</span>
                )}
                {column.unit && !structured(value) ? (
                  <span className="ml-1 font-sans text-muted-foreground">
                    {column.unit}
                  </span>
                ) : null}
              </dd>
            </div>
          ))}
        </dl>
        {row?.source_event_id != null && row.source_event_ingested_at && (
          <DialogFooter>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-muted-foreground"
              onClick={() =>
                onSourceEvent(
                  row.source_event_id!,
                  row.source_event_ingested_at!,
                )
              }
            >
              {t("Source event")}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
