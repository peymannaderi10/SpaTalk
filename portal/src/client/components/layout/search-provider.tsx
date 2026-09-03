import * as React from "react";

import { type NavContext } from "../../nav";
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
  actions = [],
  children,
}: {
  context: NavContext;
  /** Anything the page can do that is not a page: open request 412, say. */
  actions?: CommandAction[];
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((wasOpen) => !wasOpen);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const value = React.useMemo(() => ({ open, setOpen }), [open]);

  return (
    <SearchContext.Provider value={value}>
      {children}
      <CommandMenu
        open={open}
        onOpenChange={setOpen}
        context={context}
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
