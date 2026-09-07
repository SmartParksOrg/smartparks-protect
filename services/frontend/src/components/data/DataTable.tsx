import {
  type ColumnDef,
  type ColumnFiltersState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Columns3, Search, X } from "lucide-react";
import { type ReactNode, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIsPhone } from "@/hooks/useMediaQuery";
import { usePreference } from "@/hooks/usePreference";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    /** The column's filter when the table shows filters: a choice of its values, a text
     * match, or none (dates and counts). Without it: a choice up to a dozen values, else text. */
    filter?: false | "text" | "select";
  }
}

/** Distinct values up to this many make a choice; more make a text match. */
const SELECT_UP_TO = 12;

/** A choice filter holds the whole value; a text filter holds the text to look for. */
type Filter = string | { eq: string };

function passes(cell: unknown, filter: Filter): boolean {
  const text = cell === null || cell === undefined ? "" : String(cell);
  if (typeof filter === "string") return text.toLowerCase().includes(filter.toLowerCase());
  return text === filter.eq;
}

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
  /** A checkbox column: the header box selects every row of the current filter. */
  selection?: {
    selected: Set<string>;
    onChange: (next: Set<string>) => void;
    rowId: (row: T) => string;
  };
  /** With a key, a column picker appears and the choice is kept per user under that key. */
  columnsKey?: string;
  /** Column ids hidden until the person shows them (the picker lists them). */
  defaultHidden?: string[];
  /** Column ids hidden by default on a phone as well, so the operational columns fit. */
  defaultHiddenSmall?: string[];
  /** A filter row under the header: a choice or a text match per column, so a selection
   * (the header box takes every row that passes) can be organised in bulk. */
  columnFilters?: boolean;
}

/** Below this many rows a search box is noise; it still appears once a term is typed. */
const SEARCH_FROM_ROWS = 6;

/** Wide tables scroll inside this container; the page never scrolls horizontally. */
export function DataTable<T>({
  columns,
  data,
  isLoading,
  emptyMessage = "Nothing here yet.",
  onRowClick,
  rowClassName,
  footer,
  searchable,
  onSearchChange,
  selection,
  columnsKey,
  defaultHidden = [],
  defaultHiddenSmall = [],
  columnFilters: withFilters,
}: Props<T>) {
  const { t } = useTranslation();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filters, setFilters] = useState<ColumnFiltersState>([]);
  const [search, setSearch] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const allColumns = useMemo<ColumnDef<T, unknown>[]>(() => {
    if (!selection) return columns;
    const toggle = (ids: string[], on: boolean) => {
      const next = new Set(selection.selected);
      for (const id of ids)
        if (on) next.add(id);
        else next.delete(id);
      selection.onChange(next);
    };
    const box: ColumnDef<T, unknown> = {
      id: "select",
      enableSorting: false,
      header: ({ table }) => {
        const ids = table
          .getRowModel()
          .rows.map((r) => selection.rowId(r.original));
        const all =
          ids.length > 0 && ids.every((id) => selection.selected.has(id));
        return (
          <input
            type="checkbox"
            className="size-4 accent-primary"
            aria-label={t("Select all rows shown")}
            checked={all}
            onChange={(e) => toggle(ids, e.target.checked)}
          />
        );
      },
      cell: ({ row }) => {
        const id = selection.rowId(row.original);
        return (
          <input
            type="checkbox"
            className="size-4 accent-primary"
            aria-label={t("Select row")}
            checked={selection.selected.has(id)}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => toggle([id], e.target.checked)}
          />
        );
      },
    };
    return [box, ...columns];
  }, [columns, selection, t]);
  const [allChoices, setChoices] = usePreference<
    Record<string, Record<string, boolean>>
  >("table_columns", {});
  const chosen = useMemo(
    () => (columnsKey ? (allChoices[columnsKey] ?? {}) : {}),
    [allChoices, columnsKey],
  );
  const phone = useIsPhone();
  const columnVisibility = useMemo(() => {
    const visibility: Record<string, boolean> = {};
    for (const id of defaultHidden) visibility[id] = false;
    if (phone) for (const id of defaultHiddenSmall) visibility[id] = false;
    return { ...visibility, ...chosen };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chosen, phone, defaultHidden.join("|"), defaultHiddenSmall.join("|")]);
  const table = useReactTable({
    data: data ?? [],
    columns: allColumns,
    state: { sorting, globalFilter: search, columnVisibility, columnFilters: filters },
    onColumnFiltersChange: setFilters,
    defaultColumn: {
      filterFn: (row, id, filter: Filter) => passes(row.getValue(id), filter),
    },
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    onColumnVisibilityChange: (updater) => {
      if (!columnsKey) return;
      const next =
        typeof updater === "function" ? updater(columnVisibility) : updater;
      setChoices({ ...allChoices, [columnsKey]: next });
    },
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
  const filtering = filters.length > 0;
  const onSearch = (value: string) => {
    setSearch(value);
    if (!onSearchChange) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => onSearchChange(value.trim()), 300);
  };

  return (
    <div className="rounded-md border">
      {(showSearch || columnsKey || filtering) && (
        <div className="flex items-center gap-2 border-b px-3 py-2">
          {filtering && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1 text-muted-foreground"
              onClick={() => setFilters([])}
            >
              <X className="size-4" />
              {t("Clear filters ({{shown}} of {{total}})", { shown, total })}
            </Button>
          )}
          {showSearch && (
            <>
              <Search
                className="size-4 shrink-0 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(e) => onSearch(e.target.value)}
                placeholder={t("Search this list")}
                aria-label={t("Search this list")}
                className="h-8 max-w-sm"
              />
              {search !== "" && (
                <span className="text-xs text-muted-foreground">
                  {t("{{shown}} of {{total}}", { shown, total })}
                </span>
              )}
            </>
          )}
          {columnsKey && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto h-8 gap-1 text-muted-foreground"
                >
                  <Columns3 className="size-4" /> {t("Columns")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuLabel>{t("Show columns")}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {table
                  .getAllLeafColumns()
                  .filter(
                    (c) =>
                      c.id !== "select" &&
                      typeof c.columnDef.header === "string" &&
                      c.columnDef.header,
                  )
                  .map((c) => (
                    <DropdownMenuCheckboxItem
                      key={c.id}
                      checked={c.getIsVisible()}
                      onCheckedChange={(v) => c.toggleVisibility(Boolean(v))}
                      onSelect={(e) => e.preventDefault()}
                    >
                      {c.columnDef.header as string}
                    </DropdownMenuCheckboxItem>
                  ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
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
                    <TableHead
                      key={header.id}
                      className={cn(
                        header.column.getCanSort() &&
                          "cursor-pointer select-none",
                      )}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      <span className="inline-flex items-center gap-1">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        {sorted === "asc" && <ArrowUp className="size-3" />}
                        {sorted === "desc" && <ArrowDown className="size-3" />}
                      </span>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
            {withFilters && table.getHeaderGroups().map((group) => (
              <TableRow key={`${group.id}-filters`} className="hover:bg-transparent">
                {group.headers.map((header) => {
                  const column = header.column;
                  const meta = column.columnDef.meta;
                  const filterable =
                    column.id !== "select" &&
                    column.id !== "actions" &&
                    meta?.filter !== false &&
                    typeof column.columnDef.header === "string" &&
                    column.columnDef.header !== "";
                  if (!filterable)
                    return <TableHead key={`${header.id}-filter`} className="h-8" />;
                  const values = [...column.getFacetedUniqueValues().keys()]
                    .filter((v) => v !== null && v !== undefined && v !== "")
                    .map(String)
                    .sort();
                  const kind =
                    meta?.filter ??
                    (values.length <= SELECT_UP_TO ? "select" : "text");
                  const filter = column.getFilterValue() as Filter | undefined;
                  const current =
                    filter === undefined ? "" : typeof filter === "string" ? filter : filter.eq;
                  return (
                    <TableHead key={`${header.id}-filter`} className="h-8 py-1">
                      {kind === "select" ? (
                        <Select
                          value={current || "__all"}
                          onValueChange={(v) =>
                            column.setFilterValue(v === "__all" ? undefined : { eq: v })
                          }
                        >
                          <SelectTrigger
                            className="h-7 min-w-24 text-xs font-normal"
                            aria-label={t("Filter {{column}}", {
                              column: column.columnDef.header as string,
                            })}
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__all">{t("All")}</SelectItem>
                            {values.map((v) => (
                              <SelectItem key={v} value={v}>
                                {v}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input
                          value={current}
                          onChange={(e) =>
                            column.setFilterValue(e.target.value || undefined)
                          }
                          placeholder={t("Filter…")}
                          aria-label={t("Filter {{column}}", {
                            column: column.columnDef.header as string,
                          })}
                          className="h-7 min-w-24 text-xs font-normal"
                        />
                      )}
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
                  {table.getVisibleLeafColumns().map((c) => (
                    <TableCell key={c.id}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            {!isLoading && table.getRowModel().rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={table.getVisibleLeafColumns().length}
                  className="py-8 text-center text-muted-foreground"
                >
                  {search !== "" && total > 0
                    ? t("Nothing matches the search.")
                    : emptyMessage}
                </TableCell>
              </TableRow>
            )}
            {!isLoading &&
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className={cn(
                    onRowClick && "cursor-pointer",
                    rowClassName?.(row.original),
                  )}
                  onClick={() => onRowClick?.(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
      {footer && (
        <div className="border-t px-3 py-2 text-sm text-muted-foreground">
          {footer}
        </div>
      )}
    </div>
  );
}
