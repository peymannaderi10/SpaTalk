import * as React from "react";

import { type NavContext, type NavSection } from "../../nav";
import { CommandMenu, type CommandAction } from "./command-menu";

/**
 * Adapted from `satnaing/shadcn-admin` (`src/context/search-provider.tsx`).
 *
 * Same context and the same Ctrl/Cmd-K binding. Two changes: the palette it
 * mounts is told who is looking and which extra commands the page offers,
 * rather than reading the kit's module of demo navigation; and the open state
 * is passed down as props instead of the palette reading this context back,
 * so the two files do not import each other.
 */
type SearchContextValue = {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
};

const SearchContext = React.createContext<SearchContextValue | null>(null);

export function SearchProvider({
  context,
  sections,
  actions = [],
  open: openProp,
  onOpenChange,
  children,
}: {
  context: NavContext;
  /** The pages to offer; by default, every one this viewer may see. */
  sections?: NavSection[];
  /** Anything the page can do that is not a page: open request 412, say. */
  actions?: CommandAction[];
  /**
   * Controlled open state, for a caller that has to know when the palette is
   * up — the shell only asks the runtime what it could offer once someone
   * opens it. Uncontrolled, and self-contained, when it is left out.
   */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const [uncontrolled, setUncontrolled] = React.useState(false);
  const open = openProp ?? uncontrolled;

  const setOpen = React.useCallback<
    React.Dispatch<React.SetStateAction<boolean>>
  >(
    (value) => {
      const next = typeof value === "function" ? value(open) : value;
      if (onOpenChange) {
        onOpenChange(next);
      }
      if (openProp === undefined) {
        setUncontrolled(next);
      }
    },
    [open, onOpenChange, openProp],
  );

  React.useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((wasOpen) => !wasOpen);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [setOpen]);

  const value = React.useMemo(() => ({ open, setOpen }), [open, setOpen]);

  return (
    <SearchContext.Provider value={value}>
      {children}
      <CommandMenu
        open={open}
        onOpenChange={setOpen}
        context={context}
        sections={sections}
        actions={actions}
      />
    </SearchContext.Provider>
  );
}

export function useSearch(): SearchContextValue {
  const value = React.useContext(SearchContext);
  if (!value) {
    throw new Error("useSearch has to be used within SearchProvider");
  }
  return value;
}
