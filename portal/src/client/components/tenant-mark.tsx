import { IconBuilding } from "@tabler/icons-react";

import { cn } from "../utils";

/**
 * The clinic's mark: its logo once it has uploaded one, and until then the
 * first letter of its name on the primary colour — the kit's `size-8` avatar
 * idiom, the square the sidebar's team switcher draws (`team-switcher.tsx` in
 * `satnaing/shadcn-admin`).
 *
 * A Branding page will let the clinic set `logoUrl`; until then every shell
 * passes none and gets the initial. A name with no letter to take gets the
 * building the switcher always showed, so there is always a mark.
 */
export function TenantMark({
  name,
  logoUrl,
  className,
}: {
  name: string;
  logoUrl?: string | null;
  className?: string;
}) {
  const initial = name.trim().charAt(0).toUpperCase();

  return (
    <div
      data-testid="tenant-mark"
      className={cn(
        "bg-primary text-primary-foreground flex aspect-square size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg",
        className,
      )}
    >
      {logoUrl ? (
        <img src={logoUrl} alt={name} className="size-full object-cover" />
      ) : initial ? (
        <span className="text-sm font-semibold" aria-hidden="true">
          {initial}
        </span>
      ) : (
        <IconBuilding className="size-4" aria-hidden="true" />
      )}
    </div>
  );
}
