import * as React from "react";

import { visibleSections, type NavContext, type NavSection } from "../../nav";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from "../ui/sidebar";
import { SidebarNav } from "./sidebar-nav";

/**
 * The app shell's sidebar, adapted from `satnaing/shadcn-admin`
 * (`src/components/layout/app-sidebar.tsx`).
 *
 * The kit reads a module of hard-coded demo data and a layout context that
 * lets the reader change the sidebar's variant at runtime. Here the sections
 * come from `nav.ts`, filtered by who is looking, and the two slots the
 * portal fills differently — the organisation switcher at the top, the user
 * menu at the bottom — are props, so this file knows nothing about Wasp.
 *
 * `sections` overrides that filtering for a shell that shows a narrower list
 * than the viewer's role allows: the admin shell shows the agency's section
 * and nothing about any one organisation.
 */
export function AppSidebar({
  context,
  sections,
  header,
  footer,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  context: NavContext;
  /** The sections to show; by default, every one this viewer may see. */
  sections?: NavSection[];
  /** The organisation switcher. */
  header?: React.ReactNode;
  /** The user menu. */
  footer?: React.ReactNode;
}) {
  const shown = sections ?? visibleSections(context);

  return (
    <Sidebar collapsible="icon" variant="inset" {...props}>
      {header && <SidebarHeader>{header}</SidebarHeader>}
      <SidebarContent>
        {shown.map((section) => (
          <SidebarNav
            key={section.title}
            section={section}
            orgSlug={context.orgSlug}
          />
        ))}
      </SidebarContent>
      {footer && <SidebarFooter>{footer}</SidebarFooter>}
      <SidebarRail />
    </Sidebar>
  );
}
