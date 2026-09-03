import {
  IconBook,
  IconBuildingStore,
  IconChartBar,
  IconClipboardList,
  IconClock,
  IconCreditCard,
  IconHeartbeat,
  IconHistory,
  IconLayoutDashboard,
  IconMessages,
  IconPhone,
  IconPlug,
  IconScript,
  IconSend,
  IconSparkles,
  IconUserCog,
  IconUsers,
  type TablerIcon,
} from "@tabler/icons-react";

/**
 * The sidebar, as data. Nothing here renders; Task R1 mounts it.
 *
 * `to` is the route pattern exactly as the Wasp spec declares it, `:orgSlug`
 * and all, plus a query string where one page holds several sidebar items.
 * `navPath` turns a pattern into the href for one organisation.
 *
 * `nav.test.ts` reads the routes out of the Wasp spec files and fails unless
 * every route under `/app/:orgSlug` or `/admin` is either in a section here or
 * named, with a reason, in `ROUTES_OFF_THE_SIDEBAR`. A new page therefore
 * cannot be added without someone deciding where a person finds it.
 */

export type NavContext = {
  /** The organisation whose pages the sidebar is showing. */
  orgSlug: string;
  /** This viewer's role in that organisation. */
  role: "OWNER" | "STAFF";
  /** Whether this viewer is an agency admin. */
  isAdmin: boolean;
};

export type NavItem = {
  /** What the person reads. */
  label: string;
  /** The route pattern, with `:orgSlug` unsubstituted, plus any query string. */
  to: string;
  icon: TablerIcon;
  /** For Playwright, in the style the portal already uses. */
  testId: string;
  /** Whether this viewer may see the item at all. */
  visible: (ctx: NavContext) => boolean;
};

export type NavSection = {
  title: string;
  items: NavItem[];
};

const anyone = () => true;
const owners = (ctx: NavContext) => ctx.role === "OWNER";
const admins = (ctx: NavContext) => ctx.isAdmin;

/**
 * The eight tabs the settings page holds in React state today. They become
 * eight sidebar items, so the route carries the tab in `?tab=`; wiring
 * `SettingsPage` to read and write that parameter is Task R1's, and until it
 * does, every one of these opens the page on its first tab.
 */
const SETTINGS_TABS: { label: string; tab: string; icon: TablerIcon }[] = [
  { label: "Hours", tab: "hours", icon: IconClock },
  { label: "Services", tab: "services", icon: IconSparkles },
  { label: "Knowledge", tab: "knowledge", icon: IconBook },
  { label: "Scripts", tab: "scripts", icon: IconScript },
  { label: "Delivery", tab: "delivery", icon: IconSend },
  { label: "Numbers", tab: "numbers", icon: IconPhone },
  { label: "Integrations", tab: "integrations", icon: IconPlug },
  { label: "Versions", tab: "versions", icon: IconHistory },
];

export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Front desk",
    items: [
      {
        label: "Overview",
        to: "/app/:orgSlug/overview",
        icon: IconLayoutDashboard,
        testId: "nav-overview",
        visible: anyone,
      },
      {
        label: "Conversations",
        to: "/app/:orgSlug/conversations",
        icon: IconMessages,
        testId: "nav-conversations",
        visible: anyone,
      },
      {
        label: "Requests",
        to: "/app/:orgSlug/requests",
        icon: IconClipboardList,
        testId: "nav-requests",
        visible: anyone,
      },
    ],
  },
  {
    title: "Setup",
    items: SETTINGS_TABS.map(({ label, tab, icon }) => ({
      label,
      to: `/app/:orgSlug/settings?tab=${tab}`,
      icon,
      testId: `nav-settings-${tab}`,
      visible: anyone,
    })),
  },
  {
    title: "Account",
    items: [
      {
        label: "Billing",
        to: "/app/:orgSlug/billing",
        icon: IconCreditCard,
        testId: "nav-billing",
        visible: owners,
      },
      {
        label: "People",
        to: "/app/:orgSlug/settings/people",
        icon: IconUsers,
        testId: "nav-people",
        visible: owners,
      },
    ],
  },
  {
    title: "Platform",
    items: [
      {
        label: "Dashboard",
        to: "/admin",
        icon: IconChartBar,
        testId: "nav-admin-dashboard",
        visible: admins,
      },
      {
        label: "Users",
        to: "/admin/users",
        icon: IconUserCog,
        testId: "nav-admin-users",
        visible: admins,
      },
      {
        label: "Tenants",
        to: "/admin/tenants",
        icon: IconBuildingStore,
        testId: "nav-admin-tenants",
        visible: admins,
      },
      {
        label: "Health",
        to: "/admin/health",
        icon: IconHeartbeat,
        testId: "nav-admin-health",
        visible: admins,
      },
    ],
  },
];

/**
 * Routes a person reaches some other way. Each one is a decision, not an
 * oversight, which is why the test insists on the reason being written down.
 */
export const ROUTES_OFF_THE_SIDEBAR: { route: string; reason: string }[] = [
  {
    route: "/app/:orgSlug",
    reason:
      "The organisation's own root. The sidebar's organisation switcher is the way in, and the root page only offers the links the sidebar already carries.",
  },
  {
    route: "/admin/tenants/new",
    reason:
      "Reached from the Tenants page, which is where someone is when they decide to add one.",
  },
];

/** The path part of a nav `to`, with the query string dropped. */
export function navRoute(to: string): string {
  const [path] = to.split("?");
  return path;
}

/** The href for one organisation: `:orgSlug` filled in, query kept. */
export function navPath(to: string, orgSlug: string): string {
  return to.replace(":orgSlug", encodeURIComponent(orgSlug));
}

/** The sections this viewer may see, with the items they may see, empty ones dropped. */
export function visibleSections(ctx: NavContext): NavSection[] {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => item.visible(ctx)),
  })).filter((section) => section.items.length > 0);
}

/** Every item in every section, in sidebar order. */
export function allNavItems(): NavItem[] {
  return NAV_SECTIONS.flatMap((section) => section.items);
}
