import { useTranslation } from "react-i18next";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "@/components/data/DataTable";
import type { ResultDocument, ResultTable } from "@/lib/analyses";
import { tripKey, useAnalysisHighlight } from "@/stores/analysisHighlight";

/** The trips of a vehicle run, linked to the map (Tim, 2026-09-27): the row under the pointer
 * lights its trip up on the map, a click pins it and fits the map to it, a second click lets
 * go. The key the map reads is the subject's id and the trip's number, which the rows carry
 * as the subject's name and the number. */
export function TripsTable({
  table,
  document,
  labels,
}: {
  table: ResultTable;
  document: ResultDocument;
  labels: Record<string, string>;
}) {
  const { t } = useTranslation();
  const hover = useAnalysisHighlight((s) => s.hover);
  const pin = useAnalysisHighlight((s) => s.pin);
  const current = useAnalysisHighlight((s) => s.key);
  const idOf = new Map(document.subjects.map((s) => [s.name, s.id]));
  const keyOf = (row: Record<string, unknown>): string | null => {
    const id = idOf.get(String(row.subject));
    return id ? tripKey(id, String(row.trip)) : null;
  };
  const columns: ColumnDef<Record<string, unknown>, unknown>[] =
    table.columns.map((c) => ({
      header: labels[c] ?? c,
      accessorKey: c,
      cell: ({ getValue }) => {
        const v = getValue<unknown>();
        if (c === "period" && typeof v === "string") return labels[v] ?? v;
        return typeof v === "number"
          ? Number.isInteger(v)
            ? v
            : v.toFixed(2)
          : v == null
            ? ""
            : String(v);
      },
    }));
  const rows = table.rows.map((r) =>
    Object.fromEntries(table.columns.map((c, i) => [c, r[i]])),
  );
  return (
    <DataTable
      columns={columns}
      data={rows}
      emptyMessage={t("Nothing to show.")}
      onRowHover={(row) => hover(row ? keyOf(row) : null)}
      onRowClick={(row) => pin(keyOf(row))}
      rowClassName={(row) =>
        current !== null && keyOf(row) === current ? "bg-primary/10" : undefined
      }
    />
  );
}
