import { type ColumnDef, flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, type SortingState, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";

import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface Props<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[] | undefined;
  isLoading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
  footer?: ReactNode;
  /** Show a search box above the table that matches any column value (case-insensitive). */
  searchable?: boolean;
  /** Called (debounced) with the search text, for pages that also filter on the server. */
  onSearchChange?: (term: string) => void;
}

/** Below this many rows a search box is noise; it still appears once a term is typed. */
const SEARCH_FROM_ROWS = 6;

/** Wide tables scroll inside this container; the page never scrolls horizontally. */
export function DataTable<T>({ columns, data, isLoading, emptyMessage = "Nothing here yet.", onRowClick, rowClassName, footer, searchable, onSearchChange }: Props<T>) {
  const { t } = useTranslation();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [search, setSearch] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting, globalFilter: search },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    globalFilterFn: "includesString",
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const total = data?.length ?? 0;
  const shown = table.getRowModel().rows.length;
  const showSearch = searchable && (total >= SEARCH_FROM_ROWS || search !== "");
  const onSearch = (value: string) => {
    setSearch(value);
    if (!onSearchChange) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => onSearchChange(value.trim()), 300);
  };

  return (
    <div className="rounded-md border">
      {showSearch && (
        <div className="flex items-center gap-2 border-b px-3 py-2">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <Input value={search} onChange={(e) => onSearch(e.target.value)} placeholder={t("Search this list")} aria-label={t("Search this list")} className="h-8 max-w-sm" />
          {search !== "" && <span className="text-xs text-muted-foreground">{t("{{shown}} of {{total}}", { shown, total })}</span>}
        </div>
      )}
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead key={header.id} className={cn(header.column.getCanSort() && "cursor-pointer select-none")} onClick={header.column.getToggleSortingHandler()}>
                      <span className="inline-flex items-center gap-1">
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === "asc" && <ArrowUp className="size-3" />}
                        {sorted === "desc" && <ArrowDown className="size-3" />}
                      </span>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading &&
              Array.from({ length: 4 }).map((_, i) => (
                <TableRow key={`s${i}`}>
                  {columns.map((_, j) => (
                    <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                  ))}
                </TableRow>
              ))}
            {!isLoading && table.getRowModel().rows.length === 0 && (
              <TableRow><TableCell colSpan={columns.length} className="py-8 text-center text-muted-foreground">{search !== "" && total > 0 ? t("Nothing matches the search.") : emptyMessage}</TableCell></TableRow>
            )}
            {!isLoading &&
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} className={cn(onRowClick && "cursor-pointer", rowClassName?.(row.original))} onClick={() => onRowClick?.(row.original)}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
      {footer && <div className="border-t px-3 py-2 text-sm text-muted-foreground">{footer}</div>}
    </div>
  );
}
