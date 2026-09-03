import * as React from "react";

import { cn } from "../../utils";
import { Separator } from "../ui/separator";
import { SidebarTrigger } from "../ui/sidebar";

/**
 * Vendored from `satnaing/shadcn-admin` (`src/components/layout/header.tsx`),
 * unchanged apart from the import paths. See `THIRD_PARTY_NOTICES.md`.
 *
 * The sidebar trigger and a divider on the left; whatever the page puts in
 * `children` — breadcrumbs, the search button, the theme switch, the profile
 * menu — after it. `fixed` sticks it to the top and fades a blur in behind it
 * once the page has scrolled.
 */
type HeaderProps = React.HTMLAttributes<HTMLElement> & {
  fixed?: boolean;
  ref?: React.Ref<HTMLElement>;
};

export function Header({ className, fixed, children, ...props }: HeaderProps) {
  const [offset, setOffset] = React.useState(0);

  React.useEffect(() => {
    const onScroll = () => {
      setOffset(document.body.scrollTop || document.documentElement.scrollTop);
    };

    document.addEventListener("scroll", onScroll, { passive: true });
    return () => document.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "z-50 h-16",
        fixed && "header-fixed peer/header sticky top-0 w-[inherit]",
        offset > 10 && fixed ? "shadow" : "shadow-none",
        className,
      )}
      {...props}
    >
      <div
        className={cn(
          "relative flex h-full items-center gap-3 p-4 sm:gap-4",
          offset > 10 &&
            fixed &&
            "after:bg-background/20 after:absolute after:inset-0 after:-z-10 after:backdrop-blur-lg",
        )}
      >
        <SidebarTrigger
          variant="outline"
          className="max-md:scale-125"
          data-testid="sidebar-toggle"
        />
        <Separator orientation="vertical" className="h-6" />
        {children}
      </div>
    </header>
  );
}
