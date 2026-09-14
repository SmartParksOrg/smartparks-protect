import { useTranslation } from "react-i18next";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "@/components/data/DataTable";
import type { ResultTable as ResultTableData } from "@/lib/analyses";

/** One table of a result document as the page's table; the first column stays on a phone. */
export function ResultTable({
  table,
  labels,
}: {
  table: ResultTableData;
  labels?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const columns: ColumnDef<Record<string, unknown>, unknown>[] =
    table.columns.map((c) => ({
      header: labels?.[c] ?? c,
      accessorKey: c,
      cell: ({ getValue }) => {
        const v = getValue<unknown>();
        // a period or a herd key reads by its label
        if (
          (c === "period" || c === "herd" || c === "metric") &&
          typeof v === "string"
        )
          return labels?.[v] ?? v;
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
      defaultHiddenSmall={table.columns.slice(3)}
    />
  );
}
