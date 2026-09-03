import { IconX } from "@tabler/icons-react";
import { type Table } from "@tanstack/react-table";

import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { DataTableFacetedFilter, type FacetOption } from "./faceted-filter";
import { DataTableViewOptions } from "./view-options";

/**
 * Vendored from `satnaing/shadcn-admin`
 * (`src/components/data-table/toolbar.tsx`), with the Radix icon swapped for
 * Tabler's and a testid on the search box so Playwright can find it.
 */
export type ToolbarFilter = {
  columnId: string;
  title: string;
  options: FacetOption[];
};

type DataTableToolbarProps<TData> = {
  table: Table<TData>;
  searchPlaceholder?: string;
  /** Filter one column; leave it out and the box filters every column. */
  searchKey?: string;
  filters?: ToolbarFilter[];
};

export function DataTableToolbar<TData>({
  table,
  searchPlaceholder = "Filter…",
  searchKey,
  filters = [],
}: DataTableToolbarProps<TData>) {
  const isFiltered =
    table.getState().columnFilters.length > 0 || table.getState().globalFilter;

  return (
    <div className="flex items-center justify-between" role="toolbar">
      <div className="flex flex-1 flex-col-reverse items-start gap-y-2 sm:flex-row sm:items-center sm:space-x-2">
        <Input
          placeholder={searchPlaceholder}
          data-testid="table-search"
          value={
            searchKey
              ? ((table.getColumn(searchKey)?.getFilterValue() as string) ?? "")
              : (table.getState().globalFilter ?? "")
          }
          onChange={(event) => {
            if (searchKey) {
              table.getColumn(searchKey)?.setFilterValue(event.target.value);
            } else {
              table.setGlobalFilter(event.target.value);
            }
          }}
          className="h-8 w-37.5 lg:w-62.5"
        />
        <div className="flex gap-x-2">
          {filters.map((filter) => {
            const column = table.getColumn(filter.columnId);
            if (!column) return null;
            return (
              <DataTableFacetedFilter
                key={filter.columnId}
                column={column}
                title={filter.title}
                options={filter.options}
              />
            );
          })}
        </div>
        {isFiltered && (
          <Button
            variant="ghost"
            data-testid="table-reset-filters"
            onClick={() => {
              table.resetColumnFilters();
              table.setGlobalFilter("");
            }}
            className="h-8 px-2 lg:px-3"
          >
            Reset
            <IconX className="ms-2 h-4 w-4" />
          </Button>
        )}
      </div>
      <DataTableViewOptions table={table} />
    </div>
  );
}
