import * as React from "react";

import { cn } from "../utils";

/**
 * The heading block every page in the shell opens with.
 *
 * It is the kit's own page header, lifted from the top of
 * `src/features/tasks/index.tsx` and `src/features/users/index.tsx` in
 * `satnaing/shadcn-admin`: a title, a line saying what the page is for, and
 * the page's primary buttons pushed to the end of the row.
 *
 * The title stays an `h1` because the Playwright suite reads pages by their
 * headings; the kit uses `h2` on two of its pages and `h1` on the rest, and
 * one level for every page is the accessible reading of it.
 */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Buttons, at the end of the row on a wide screen and under it on a phone. */
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-end justify-between gap-2",
        className,
      )}
    >
      <div className="space-y-0.5">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && (
          <p className="text-muted-foreground text-sm">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
