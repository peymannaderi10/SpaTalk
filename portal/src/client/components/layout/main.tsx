import * as React from "react";

import { cn } from "../../utils";

/**
 * Vendored from `satnaing/shadcn-admin` (`src/components/layout/main.tsx`),
 * unchanged apart from the import path. See `THIRD_PARTY_NOTICES.md`.
 *
 * `fixed` makes the page fill the shell and scroll inside itself, which is
 * what a table page wants; `fluid` drops the reading-width cap, which a
 * dashboard of cards wants. The container queries need the shell to have
 * `@container/content` on it, which `AppLayout` does in Task R1.
 */
type MainProps = React.HTMLAttributes<HTMLElement> & {
  fixed?: boolean;
  fluid?: boolean;
  ref?: React.Ref<HTMLElement>;
};

export function Main({ fixed, className, fluid, ...props }: MainProps) {
  return (
    <main
      data-layout={fixed ? "fixed" : "auto"}
      className={cn(
        "px-4 py-6",
        fixed && "flex grow flex-col overflow-hidden",
        !fluid &&
          "@7xl/content:mx-auto @7xl/content:w-full @7xl/content:max-w-7xl",
        className,
      )}
      {...props}
    />
  );
}
