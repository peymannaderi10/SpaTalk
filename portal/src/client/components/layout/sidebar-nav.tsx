import { Link, useLocation } from "react-router";

import { navPath, navRoute, type NavItem, type NavSection } from "../../nav";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "../ui/sidebar";

/**
 * One section of the sidebar, rendered from `nav.ts`.
 *
 * Adapted from `satnaing/shadcn-admin` (`src/components/layout/nav-group.tsx`):
 * the kit's `Link` and `useLocation` come from TanStack Router, so both are
 * swapped for react-router's, and `checkIsActive` compares
 * `location.pathname` and `location.search` instead of the kit's single `href`
 * string. The kit's collapsible and collapsed-dropdown branches are gone with
 * the nested items they served: this portal's sidebar model is flat, and the
 * settings tabs that would have been children are their own section.
 */
export function SidebarNav({
  section,
  orgSlug,
}: {
  section: NavSection;
  orgSlug: string;
}) {
  const location = useLocation();
  const { setOpenMobile } = useSidebar();

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{section.title}</SidebarGroupLabel>
      <SidebarMenu>
        {section.items.map((item) => (
          <SidebarMenuItem key={item.testId}>
            <SidebarMenuButton
              asChild
              isActive={isActive(item, orgSlug, location.pathname, location.search)}
              tooltip={item.label}
            >
              <Link
                to={navPath(item.to, orgSlug)}
                data-testid={item.testId}
                onClick={() => setOpenMobile(false)}
              >
                <item.icon />
                <span>{item.label}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}

/**
 * An item is current when the path matches. Where several items share a path
 * and differ only by query — the settings tabs — the query has to match too,
 * and the item with no query is current while the page carries none.
 */
export function isActive(
  item: NavItem,
  orgSlug: string,
  pathname: string,
  search: string,
): boolean {
  const href = navPath(item.to, orgSlug);
  const [itemPath, itemQuery = ""] = href.split("?");

  if (pathname !== navPath(navRoute(item.to), orgSlug) && pathname !== itemPath) {
    return false;
  }

  if (!itemQuery) {
    return true;
  }

  const current = new URLSearchParams(search);
  const wanted = new URLSearchParams(itemQuery);
  for (const [key, value] of wanted) {
    if (current.get(key) !== value) {
      return false;
    }
  }
  return true;
}
