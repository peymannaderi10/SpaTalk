import {
  IconArrowDown,
  IconArrowUp,
  IconEyeOff,
  IconSelector,
} from "@tabler/icons-react";
import { type Column } from "@tanstack/react-table";
import * as React from "react";

import { cn } from "../../utils";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

/**
 * Vendored from `satnaing/shadcn-admin`
 * (`src/components/data-table/column-header.tsx`). The kit's Radix icons are
 * Tabler's here, which is the set the reskin standardises on and one fewer
 * dependency; everything else is the kit's.
 */
type DataTableColumnHeaderProps<TData, TValue> =
  React.HTMLAttributes<HTMLDivElement> & {
    column: Column<TData, TValue>;
    title: string;
  };

export function DataTableColumnHeader<TData, TValue>({
  column,
  title,
  className,
}: DataTableColumnHeaderProps<TData, TValue>) {
  if (!column.getCanSort()) {
    return <div className={cn(className)}>{title}</div>;
  }

  return (
    <div className={cn("flex items-center space-x-2", className)}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="data-[state=open]:bg-accent h-8"
          >
            <span>{title}</span>
            {column.getIsSorted() === "desc" ? (
              <IconArrowDown className="ms-2 h-4 w-4" />
            ) : column.getIsSorted() === "asc" ? (
              <IconArrowUp className="ms-2 h-4 w-4" />
            ) : (
              <IconSelector className="ms-2 h-4 w-4" />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onClick={() => column.toggleSorting(false)}>
            <IconArrowUp className="text-muted-foreground/70 size-3.5" />
            Asc
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => column.toggleSorting(true)}>
            <IconArrowDown className="text-muted-foreground/70 size-3.5" />
            Desc
          </DropdownMenuItem>
          {column.getCanHide() && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => column.toggleVisibility(false)}>
                <IconEyeOff className="text-muted-foreground/70 size-3.5" />
                Hide
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
