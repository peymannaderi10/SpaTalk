import { IconBuilding, IconCheck, IconChevronDown } from "@tabler/icons-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
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
 */
export type SwitchableOrg = {
  id: string;
  name: string;
  slug: string;
};

export function OrgSwitcher({
  orgs,
  currentSlug,
  onSelect,
  emptyLabel = "No organisation",
}: {
  orgs: SwitchableOrg[];
  currentSlug?: string | null;
  onSelect: (slug: string) => void;
  /** Shown while the list is still loading, or when there is nothing to pick. */
  emptyLabel?: string;
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
              <div className="bg-sidebar-primary text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg">
                <IconBuilding className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">
                  {current?.name ?? currentSlug ?? emptyLabel}
                </span>
                <span className="text-muted-foreground truncate text-xs">
                  {orgs.length > 1 ? "Switch organisation" : "Organisation"}
                </span>
              </div>
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
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
