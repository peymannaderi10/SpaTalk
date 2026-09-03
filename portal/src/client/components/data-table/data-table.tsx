import {
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnFiltersState,
  type PaginationState,
  type Row,
  type SortingState,
  type VisibilityState,
} from "@tanstack/react-table";
import * as React from "react";

import { cn } from "../../utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import { DataTablePagination } from "./pagination";
import { DataTableToolbar, type ToolbarFilter } from "./toolbar";

/**
 * One table for the whole portal, assembled from the kit's table page
 * (`src/features/tasks/components/tasks-table.tsx` in `satnaing/shadcn-admin`)
 * with its toolbar, header and pagination.
 *
 * Two departures from the kit. Its table keeps sorting, filters and the page
 * number in the URL through `use-table-url-state`, which is written against
 * TanStack Router's typed search params; that has no react-router equivalent
 * to copy, so the state is local here and a page that wants it in the URL can
 * lift it with the `state` props. And the kit's bulk-actions bar is not
 * vendored: nothing in this portal selects rows to act on them in bulk.
 */
export type DataTableProps<TData, TValue> = {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  /** Shown above the table; leave `toolbar` false for a table nobody filters. */
  toolbar?: boolean;
  searchPlaceholder?: string;
  /** Filter one column by name; omitted, the search box filters every column. */
  searchKey?: string;
  filters?: ToolbarFilter[];
  /** Hidden when there is one page and nobody is choosing a page size. */
  pagination?: boolean;
  pageSize?: number;
  /** What the body says when there is nothing to show. */
  empty?: React.ReactNode;
  onRowClick?: (row: Row<TData>) => void;
  className?: string;
  tableClassName?: string;
  /** For Playwright; the rows get `<testId>-row`. */
  testId?: string;
};

export function DataTable<TData, TValue>({
  columns,
  data,
  toolbar = true,
  searchPlaceholder,
  searchKey,
  filters = [],
  pagination = true,
  pageSize = 10,
  empty = "No results.",
  onRowClick,
  className,
  tableClassName,
  testId,
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] =
    React.useState<VisibilityState>({});
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>(
    [],
  );
  const [globalFilter, setGlobalFilter] = React.useState("");
  const [paginationState, setPaginationState] = React.useState<PaginationState>(
    { pageIndex: 0, pageSize },
  );

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      columnVisibility,
      columnFilters,
      globalFilter,
      pagination: paginationState,
    },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onPaginationChange: setPaginationState,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
  });

  return (
    <div className={cn("flex flex-1 flex-col gap-4", className)}>
      {toolbar && (
        <DataTableToolbar
          table={table}
          searchPlaceholder={searchPlaceholder}
          searchKey={searchKey}
          filters={filters}
        />
      )}

      <div className="overflow-hidden rounded-md border">
        <Table className={tableClassName} data-testid={testId}>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    colSpan={header.colSpan}
                    className={cn(
                      header.column.columnDef.meta?.className,
                      header.column.columnDef.meta?.thClassName,
                    )}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-testid={testId ? `${testId}-row` : undefined}
                  data-state={row.getIsSelected() && "selected"}
                  className={onRowClick ? "cursor-pointer" : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cn(
                        cell.column.columnDef.meta?.className,
                        cell.column.columnDef.meta?.tdClassName,
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center">
                  {empty}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {pagination && <DataTablePagination table={table} className="mt-auto" />}
    </div>
  );
}
