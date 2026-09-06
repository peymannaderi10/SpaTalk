import {
  IconCheck,
  IconChevronDown,
  type TablerIcon,
} from "@tabler/icons-react";
import { Link } from "react-router";

import { TenantMark } from "../tenant-mark";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "../ui/sidebar";

/**
 * The organisation switcher, in the shape of the kit's team switcher
 * (`satnaing/shadcn-admin`, `src/components/layout/team-switcher.tsx`): a
 * large sidebar menu button that opens a list, and that collapses to the mark
 * alone when the sidebar is a rail.
 *
 * The kit hard-codes its teams. Here the organisations are a prop, so this
 * file knows nothing about Wasp and the shell stays renderable in a unit test.
 * Choosing one is a navigation, not a mutation: the organisation lives in the
 * URL, so the caller navigates and the URL becomes the truth.
 *
 * The button is the clinic's mark and its name in one row, and nothing under
 * the name: the kit's "plan" subtext, which here read "Organisation", said
 * nothing a person needed. The mark is `TenantMark`: the logo the Branding
 * page stored, handed in as `logoUrl` by the shell that fetched the
 * organisation, and the initial until there is one. `aria-label` stays
 * "Organisation" because that is the accessible name the browser suite
 * selects the trigger by.
 */
export type SwitchableOrg = {
  id: string;
  name: string;
  slug: string;
};

/**
 * Somewhere to go that is not one of the organisations: the platform's own
 * dashboard, for an agency admin. The caller decides whether there is one.
 */
export type SwitcherLink = {
  label: string;
  to: string;
  testId: string;
  icon?: TablerIcon;
};

export function OrgSwitcher({
  orgs,
  currentSlug,
  logoUrl,
  onSelect,
  emptyLabel = "No organisation",
  links = [],
}: {
  orgs: SwitchableOrg[];
  currentSlug?: string | null;
  /** The current organisation's logo, when it has one. */
  logoUrl?: string | null;
  onSelect: (slug: string) => void;
  /** Shown while the list is still loading, or when there is nothing to pick. */
  emptyLabel?: string;
  /** Appended under the organisations, after a rule. */
  links?: SwitcherLink[];
}) {
  const { isMobile, setOpenMobile } = useSidebar();
  const current = orgs.find((org) => org.slug === currentSlug);

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              data-testid="org-switcher"
              aria-label="Organisation"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <TenantMark
                name={current?.name ?? currentSlug ?? emptyLabel}
                logoUrl={logoUrl}
              />
              <span className="flex-1 truncate text-left text-sm font-medium">
                {current?.name ?? currentSlug ?? emptyLabel}
              </span>
              <IconChevronDown className="ms-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            align="start"
            side={isMobile ? "bottom" : "right"}
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-muted-foreground text-xs">
              Organisations
            </DropdownMenuLabel>
            {orgs.length === 0 && (
              <DropdownMenuItem disabled>{emptyLabel}</DropdownMenuItem>
            )}
            {orgs.map((org) => (
              <DropdownMenuItem
                key={org.id}
                data-testid={`org-switcher-${org.slug}`}
                onClick={() => {
                  setOpenMobile(false);
                  onSelect(org.slug);
                }}
                className="gap-2 p-2"
              >
                <span className="truncate">{org.name}</span>
                {org.slug === currentSlug && (
                  <IconCheck className="ms-auto size-4" />
                )}
              </DropdownMenuItem>
            ))}
            {links.length > 0 && <DropdownMenuSeparator />}
            {links.map((link) => (
              <DropdownMenuItem
                key={link.to}
                data-testid={link.testId}
                asChild
                className="gap-2 p-2"
              >
                <Link to={link.to} onClick={() => setOpenMobile(false)}>
                  {link.icon && <link.icon className="size-4" />}
                  <span className="truncate">{link.label}</span>
                </Link>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
