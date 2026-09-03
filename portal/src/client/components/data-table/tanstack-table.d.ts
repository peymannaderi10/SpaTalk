import "@tanstack/react-table";

/**
 * Vendored from `satnaing/shadcn-admin` (`src/tanstack-table.d.ts`). It lets a
 * column definition carry the classes its header and its cells wear, which is
 * how the kit keeps a column's width and alignment in one place.
 */
declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends unknown, TValue> {
    /** Applied to both the `th` and the `td`. */
    className?: string;
    tdClassName?: string;
    thClassName?: string;
  }
}
