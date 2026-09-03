import { IconInbox, type TablerIcon } from "@tabler/icons-react";
import * as React from "react";

import { cn } from "../utils";

/**
 * What a list says when it holds nothing.
 *
 * The kit has no empty state — its lists are always full of seed data — so
 * this is written in the kit's idiom rather than copied: its `ComingSoon`
 * block's centred icon, heading and muted line, sized for a panel instead of
 * the whole viewport, with room for one action.
 *
 * It says what is missing and, where there is one, what to do about it. It
 * never claims something is on its way.
 */
export function EmptyState({
  title,
  description,
  icon: Icon = IconInbox,
  action,
  className,
  testId,
}: {
  title: string;
  description?: string;
  icon?: TablerIcon;
  /** A button, usually. */
  action?: React.ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "border-border flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center",
        className,
      )}
    >
      <Icon className="text-muted-foreground size-10" stroke={1.5} />
      <h3 className="text-foreground text-base font-medium">{title}</h3>
      {description && (
        <p className="text-muted-foreground max-w-prose text-sm">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
