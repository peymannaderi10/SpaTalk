import { type ReactNode } from "react";

import {
  AppSidebar,
  Breadcrumbs,
  Header,
  Main,
  ProfileDropdown,
  Search,
  SearchProvider,
  type CommandAction,
  type Crumb,
  type ProfileMenuItem,
} from "../components/layout";
import { type Branding } from "../branding/themes";
import { useBrandingStyle } from "../branding/useBrandingStyle";
import { DarkModeSwitcher } from "../components/DarkModeSwitcher";
import { SidebarInset, SidebarProvider } from "../components/ui/sidebar";
import { type NavContext, type NavSection } from "../nav";

/**
 * The shell every page inside an organisation sits in, and — with the
 * platform section instead of an organisation's — every agency page too.
 *
 * The arrangement is the kit's `AuthenticatedLayout`
 * (`satnaing/shadcn-admin`, `src/components/layout/authenticated-layout.tsx`)
 * with its header row: sidebar, then an inset that carries the header and the
 * page. `@container/content` on the inset is what makes the kit's
 * `@7xl/content:` widths in `Main` and `@2xl/content:` in the data table
 * pagination mean anything.
 *
 * It imports nothing from Wasp on purpose. Everything that knows about a user,
 * an organisation or an operation arrives as a prop, which is what lets
 * `AppLayout.test.tsx` render the whole shell in jsdom, and what keeps the two
 * shells — this one and the admin's — the same component.
 */

export type AppLayoutProfile = {
  name: string;
  email?: string | null;
  avatarUrl?: string | null;
  items?: ProfileMenuItem[];
  onSignOut: () => void;
};

export type AppLayoutProps = {
  /** Who is looking and at which organisation; decides what the sidebar holds. */
  context: NavContext;
  /** Narrower than the viewer's role allows, for a shell that shows less. */
  sections?: NavSection[];
  /** The trail in the header. The caller knows the names; the shell does not. */
  breadcrumbs?: Crumb[];
  /** The organisation switcher, at the top of the sidebar. */
  orgSwitcher?: ReactNode;
  /** The person in the header's user menu. */
  profile?: AppLayoutProfile;
  /** Things the command palette can do that are not pages. */
  actions?: CommandAction[];
  /**
   * Controlled palette state. The organisation shell holds it so it can wait
   * until someone opens the palette before asking the runtime for anything.
   */
  paletteOpen?: boolean;
  onPaletteOpenChange?: (open: boolean) => void;
  /** The page fills the shell and scrolls inside itself: what a table wants. */
  fixed?: boolean;
  /** Drop the reading-width cap: what a wall of cards wants. */
  fluid?: boolean;
  /**
   * The organisation's chosen look. Its resolved tokens go inline on the
   * shell's root, so everything under it wears them; nothing is set when it
   * is absent, which is how the admin shell keeps the kit's own look.
   */
  branding?: Pick<Branding, "themePreset" | "accentHex"> | null;
  children: ReactNode;
};

export function AppLayout({
  context,
  sections,
  breadcrumbs = [],
  orgSwitcher,
  profile,
  actions = [],
  paletteOpen,
  onPaletteOpenChange,
  fixed,
  fluid,
  branding,
  children,
}: AppLayoutProps) {
  const brandingStyle = useBrandingStyle(branding);

  return (
    <SidebarProvider style={brandingStyle}>
      <SearchProvider
        context={context}
        sections={sections}
        actions={actions}
        open={paletteOpen}
        onOpenChange={onPaletteOpenChange}
      >
        <AppSidebar
          context={context}
          sections={sections}
          header={orgSwitcher}
        />
        <SidebarInset
          className={
            // `@container/content` is the container the kit's widths measure
            // against; `has-[[data-layout=fixed]]:h-svh` lets a fixed page
            // scroll inside the shell instead of scrolling the shell.
            "@container/content has-[[data-layout=fixed]]:h-svh"
          }
        >
          <Header fixed>
            <Breadcrumbs items={breadcrumbs} />
            <div className="ms-auto flex items-center gap-2 sm:gap-4">
              <Search />
              <span data-testid="theme-switch" className="flex items-center">
                <DarkModeSwitcher />
              </span>
              {profile && <ProfileDropdown {...profile} />}
            </div>
          </Header>
          <Main fixed={fixed} fluid={fluid}>
            {children}
          </Main>
        </SidebarInset>
      </SearchProvider>
    </SidebarProvider>
  );
}
