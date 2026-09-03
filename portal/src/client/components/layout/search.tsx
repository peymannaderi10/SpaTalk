import { IconSearch } from "@tabler/icons-react";
import * as React from "react";

import { cn } from "../../utils";
import { Button } from "../ui/button";
import { useSearch } from "./search-provider";

/**
 * Vendored from `satnaing/shadcn-admin` (`src/components/search.tsx`); the
 * only changes are the import paths and Lucide's icon for Tabler's. It is the
 * button in the header that opens the command palette, and it advertises the
 * keyboard shortcut so people find it without being told.
 */
export function Search({
  className = "",
  placeholder = "Search",
  ...props
}: React.ComponentProps<"button"> & { placeholder?: string }) {
  const { setOpen } = useSearch();

  return (
    <Button
      {...props}
      variant="outline"
      className={cn(
        "group bg-muted/25 text-muted-foreground hover:bg-accent relative h-8 w-full flex-1 justify-start rounded-md text-sm font-normal shadow-none sm:w-40 sm:pe-12 md:flex-none lg:w-52 xl:w-64",
        className,
      )}
      aria-keyshortcuts="Meta+K Control+K"
      data-testid="command-palette-open"
      onClick={() => setOpen(true)}
    >
      <IconSearch
        aria-hidden="true"
        className="absolute start-1.5 top-1/2 -translate-y-1/2"
        size={16}
      />
      <span className="ms-4">{placeholder}</span>
      <kbd className="bg-muted group-hover:bg-accent pointer-events-none absolute end-[0.3rem] top-[0.3rem] hidden h-5 items-center gap-1 rounded border px-1.5 font-mono text-[10px] font-medium opacity-100 select-none sm:flex">
        <span className="text-xs">⌘</span>K
      </kbd>
    </Button>
  );
}
