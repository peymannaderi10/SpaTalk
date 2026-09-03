import { IconArrowRight, IconMoon, IconSun } from "@tabler/icons-react";
import * as React from "react";
import { useNavigate } from "react-router";

import { useColorMode } from "../../hooks/useColorMode";
import { navPath, visibleSections, type NavContext } from "../../nav";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "../ui/command";
import { ScrollArea } from "../ui/scroll-area";

/**
 * Adapted from `satnaing/shadcn-admin` (`src/components/command-menu.tsx`).
 *
 * The kit reads its demo sidebar data, navigates with TanStack Router and
 * flips its own theme provider. This one takes the sections `nav.ts` says this
 * viewer may see, navigates with react-router, and switches the portal's
 * `useColorMode`. `actions` is how a page adds the things that are not pages —
 * opening a request by number, a conversation by phone number — without this
 * file knowing what a request is.
 */
export type CommandAction = {
  /** The group the action is listed under. */
  group: string;
  label: string;
  /** What cmdk matches the typed text against, if not the label. */
  value?: string;
  icon?: React.ComponentType<{ className?: string }>;
  run: () => void;
};

export function CommandMenu({
  open,
  onOpenChange,
  context,
  actions = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  context: NavContext;
  actions?: CommandAction[];
}) {
  const navigate = useNavigate();
  const [, setColorMode] = useColorMode();

  const run = React.useCallback(
    (command: () => unknown) => {
      onOpenChange(false);
      command();
    },
    [onOpenChange],
  );

  const sections = visibleSections(context);
  const actionGroups = [...new Set(actions.map((action) => action.group))];

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <ScrollArea type="hover" className="h-72 pe-1">
          <CommandEmpty>No results found.</CommandEmpty>

          {sections.map((section) => (
            <CommandGroup key={section.title} heading={section.title}>
              {section.items.map((item) => (
                <CommandItem
                  key={item.testId}
                  value={`${section.title} ${item.label}`}
                  onSelect={() =>
                    run(() => navigate(navPath(item.to, context.orgSlug)))
                  }
                >
                  <div className="flex size-4 items-center justify-center">
                    <IconArrowRight className="text-muted-foreground/80 size-3" />
                  </div>
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}

          {actionGroups.map((group) => (
            <CommandGroup key={group} heading={group}>
              {actions
                .filter((action) => action.group === group)
                .map((action) => (
                  <CommandItem
                    key={`${group}-${action.label}`}
                    value={action.value ?? `${group} ${action.label}`}
                    onSelect={() => run(action.run)}
                  >
                    {action.icon ? (
                      <action.icon className="size-4" />
                    ) : (
                      <div className="flex size-4 items-center justify-center">
                        <IconArrowRight className="text-muted-foreground/80 size-3" />
                      </div>
                    )}
                    {action.label}
                  </CommandItem>
                ))}
            </CommandGroup>
          ))}

          <CommandSeparator />
          <CommandGroup heading="Theme">
            <CommandItem
              onSelect={() =>
                run(() => {
                  if (typeof setColorMode === "function") setColorMode("light");
                })
              }
            >
              <IconSun />
              <span>Light</span>
            </CommandItem>
            <CommandItem
              onSelect={() =>
                run(() => {
                  if (typeof setColorMode === "function") setColorMode("dark");
                })
              }
            >
              <IconMoon className="scale-90" />
              <span>Dark</span>
            </CommandItem>
          </CommandGroup>
        </ScrollArea>
      </CommandList>
    </CommandDialog>
  );
}
