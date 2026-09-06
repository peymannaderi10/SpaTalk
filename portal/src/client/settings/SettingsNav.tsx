import { type TablerIcon } from "@tabler/icons-react";

import { ScrollArea } from "../components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { buttonVariants } from "../components/ui/button";
import { cn } from "../utils";

/**
 * The settings side navigation, from the kit
 * (`src/features/settings/components/sidebar-nav.tsx` in
 * `satnaing/shadcn-admin`): a select on a phone, a column of ghost buttons
 * from `md` up, with the tab you are on painted `bg-muted`.
 *
 * The kit's items are router links because each of its settings tabs is a
 * route. Ours are one route with a `?tab=` on it, and the Playwright suite
 * reaches them as buttons, so these are buttons that set the tab — which also
 * writes the query string, so a deep link and a click end up the same. This is
 * the only way between sections: the sidebar carries one Settings entry. The
 * current section says so with `aria-current`, for readers and for the suite.
 */
export type SettingsNavItem = {
  value: string;
  title: string;
  icon: TablerIcon;
  testId?: string;
};

export function SettingsNav({
  items,
  value,
  onSelect,
  className,
}: {
  items: SettingsNavItem[];
  value: string;
  onSelect: (value: string) => void;
  className?: string;
}) {
  return (
    <>
      <div className="p-1 md:hidden">
        <Select value={value} onValueChange={onSelect}>
          <SelectTrigger
            className="h-12 sm:w-48"
            data-testid="settings-tab-select"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                <div className="flex gap-x-4 px-2 py-1">
                  <span className="scale-125">
                    <item.icon size={18} />
                  </span>
                  <span className="text-md">{item.title}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <ScrollArea
        type="always"
        className="bg-background hidden w-full min-w-40 px-1 py-2 md:block"
      >
        <nav
          className={cn(
            "flex space-x-2 py-1 lg:flex-col lg:space-y-1 lg:space-x-0",
            className,
          )}
        >
          {items.map((item) => (
            <button
              key={item.value}
              type="button"
              data-testid={item.testId}
              aria-current={value === item.value ? "page" : undefined}
              onClick={() => onSelect(item.value)}
              className={cn(
                buttonVariants({ variant: "ghost" }),
                value === item.value
                  ? "bg-muted hover:bg-accent"
                  : "hover:bg-accent hover:underline",
                "justify-start",
              )}
            >
              <span className="me-2">
                <item.icon size={18} />
              </span>
              {item.title}
            </button>
          ))}
        </nav>
      </ScrollArea>
    </>
  );
}
