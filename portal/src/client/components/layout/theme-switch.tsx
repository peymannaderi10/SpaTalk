import { IconCheck, IconMoon, IconSun } from "@tabler/icons-react";

import { useColorMode } from "../../hooks/useColorMode";
import { cn } from "../../utils";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

/**
 * Adapted from `satnaing/shadcn-admin` (`src/components/theme-switch.tsx`).
 *
 * The kit ships its own cookie-backed theme provider with a third, "system"
 * choice. The portal already has one — `useColorMode`, which writes
 * `color-theme` to local storage and toggles `.dark` on the body — so this
 * reads that instead of adding a second source of truth, and offers the two
 * modes it knows about. Lucide's icons are swapped for Tabler's, the set the
 * reskin is standardising on.
 */
export function ThemeSwitch({ className }: { className?: string }) {
  const [colorMode, setColorMode] = useColorMode();
  const isDark = colorMode === "dark";

  const set = (mode: "light" | "dark") => {
    if (typeof setColorMode === "function") {
      setColorMode(mode);
    }
  };

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("scale-95 rounded-full", className)}
          data-testid="theme-switch"
        >
          <IconSun className="size-[1.2rem] scale-100 rotate-0 transition-all dark:scale-0 dark:-rotate-90" />
          <IconMoon className="absolute size-[1.2rem] scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0" />
          <span className="sr-only">Toggle theme</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => set("light")}>
          Light
          <IconCheck size={14} className={cn("ms-auto", isDark && "hidden")} />
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => set("dark")}>
          Dark
          <IconCheck size={14} className={cn("ms-auto", !isDark && "hidden")} />
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
