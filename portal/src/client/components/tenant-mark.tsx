import { IconBuilding } from "@tabler/icons-react";

import { cn } from "../utils";

/**
 * The clinic's mark: its logo once it has uploaded one, and until then the
 * first letter of its name on the primary colour — the kit's `size-8` avatar
 * idiom, the square the sidebar's team switcher draws (`team-switcher.tsx` in
 * `satnaing/shadcn-admin`).
 *
 * The Branding page stores the logo on the organisation as a `data:` URL and
 * the clinic shell hands it in as `logoUrl`; a clinic that has not uploaded
 * one gets the initial. The logo is fitted inside the square, not cropped to
 * it, because a wordmark is wider than it is tall. A name with no letter to
 * take gets the building the switcher always showed, so there is always a
 * mark.
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
        <img src={logoUrl} alt={name} className="size-full object-contain" />
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
