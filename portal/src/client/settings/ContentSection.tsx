import { type ReactNode } from "react";

import { Separator } from "../components/ui/separator";

/**
 * One settings section, from the kit
 * (`src/features/settings/components/content-section.tsx` in
 * `satnaing/shadcn-admin`): a heading, a line saying what the section is for,
 * a rule, and the form scrolling under it with the kit's faded bottom edge.
 *
 * The kit's version has no room for an action beside the heading because each
 * of its forms carries its own submit. This tenant's configuration is saved
 * whole, once, whichever tab is open, so the save button lives in the section
 * header where it is in front of whoever is editing.
 */
export function ContentSection({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-none flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-medium">{title}</h2>
          <p className="text-muted-foreground text-sm">{description}</p>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      <Separator className="my-4 flex-none" />
      <div className="faded-bottom h-full w-full overflow-y-auto scroll-smooth pe-4 pb-12">
        <div className="-mx-1 space-y-6 px-1.5">{children}</div>
      </div>
    </div>
  );
}
