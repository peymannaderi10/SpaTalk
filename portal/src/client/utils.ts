import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * The page buttons a pager shows, with ellipses where it skips.
 *
 * Vendored from `satnaing/shadcn-admin` (`src/lib/utils.ts`), because
 * `DataTablePagination` came from the same place and expects exactly this
 * shape. Five pages or fewer are all listed; beyond that the first and last
 * are always there and the middle is a window around the current page.
 */
export function getPageNumbers(
  currentPage: number,
  totalPages: number,
): (number | string)[] {
  const maxVisiblePages = 5;
  const rangeWithDots: (number | string)[] = [];

  if (totalPages <= maxVisiblePages) {
    for (let i = 1; i <= totalPages; i += 1) {
      rangeWithDots.push(i);
    }
    return rangeWithDots;
  }

  rangeWithDots.push(1);

  if (currentPage <= 3) {
    for (let i = 2; i <= 4; i += 1) {
      rangeWithDots.push(i);
    }
    rangeWithDots.push("...", totalPages);
  } else if (currentPage >= totalPages - 2) {
    rangeWithDots.push("...");
    for (let i = totalPages - 3; i <= totalPages; i += 1) {
      rangeWithDots.push(i);
    }
  } else {
    rangeWithDots.push("...");
    for (let i = currentPage - 1; i <= currentPage + 1; i += 1) {
      rangeWithDots.push(i);
    }
    rangeWithDots.push("...", totalPages);
  }

  return rangeWithDots;
}
