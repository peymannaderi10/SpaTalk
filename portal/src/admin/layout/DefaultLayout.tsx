import { IconUserCircle } from "@tabler/icons-react";
import { ReactNode } from "react";
import { Link, Navigate, useLocation } from "react-router";
import { type AuthUser } from "wasp/auth";
import { logout } from "wasp/client/auth";
import { routes } from "wasp/client/router";
import { BRAND } from "../../client/brand";
import { type Crumb } from "../../client/components/layout";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "../../client/components/ui/sidebar";
import { AppLayout } from "../../client/layout/AppLayout";
import {
  navRoute,
  platformSections,
  PLATFORM_SECTION,
  type NavContext,
} from "../../client/nav";

interface Props {
  user: AuthUser;
  children?: ReactNode;
}

/**
 * The agency's own pages, in the same shell the clinics see.
 *
 * It was a bespoke sidebar and a hamburger header of its own; it is now
 * `AppLayout` with the Platform section from `nav.ts` and nothing else, so
 * there is one shell in the portal rather than two that drift apart. The
 * refusal is unchanged and still only a courtesy: every operation behind these
 * pages refuses a non-admin on the server.
 */
export function DefaultLayout({ children, user }: Props) {
  const location = useLocation();

  if (!user.isAdmin) {
    return <Navigate to={routes.RootRoute.to} replace />;
  }

  // `/admin` is not about one organisation, so there is no slug to fill in and
  // no organisation switcher; the role is irrelevant to the Platform section.
  const context: NavContext = { orgSlug: "", role: "OWNER", isAdmin: true };

  return (
    <AppLayout
      context={context}
      sections={platformSections(context)}
      breadcrumbs={crumbsFor(location.pathname)}
      orgSwitcher={<PlatformMark />}
      profile={{
        name: user.username ?? user.email ?? "You",
        email: user.email,
        // No "your organisations" entry: `/app` is a resolver now and would
        // send an agency admin straight back here. A clinic is reached from
        // the Tenants page, which is where the agency's list of them is.
        items: [{ label: "Account", to: "/account", icon: IconUserCircle }],
        onSignOut: () => {
          void logout();
        },
      }}
      fluid
    >
      {children}
    </AppLayout>
  );
}

/**
 * What stands where an organisation's pages put the switcher: the mark, the
 * product's name, and a way back to the agency dashboard. There is nothing to
 * switch between here — `/admin` is about every tenant at once.
 */
function PlatformMark() {
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton size="lg" asChild data-testid="platform-mark">
          <Link to={routes.AdminRoute.to}>
            <img
              src={BRAND.logo.mark}
              alt=""
              className="size-8 shrink-0 rounded-lg"
            />
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-medium">{BRAND.name}</span>
              <span className="text-muted-foreground truncate text-xs">
                {PLATFORM_SECTION}
              </span>
            </div>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

/**
 * The trail, from the route. Every admin page but the new-tenant wizard is a
 * sidebar item, so the item's own label is the crumb; the wizard is named
 * where `nav.ts` says it is reached from.
 */
function crumbsFor(pathname: string): Crumb[] {
  const trail: Crumb[] = [{ label: PLATFORM_SECTION, to: routes.AdminRoute.to }];
  const section = platformSections({
    orgSlug: "",
    role: "OWNER",
    isAdmin: true,
  })[0];

  const item = section?.items.find((entry) => navRoute(entry.to) === pathname);
  if (item) {
    return [...trail, { label: item.label }];
  }
  if (pathname === "/admin/tenants/new") {
    return [
      ...trail,
      { label: "Tenants", to: "/admin/tenants" },
      { label: "New tenant" },
    ];
  }
  return trail;
}
