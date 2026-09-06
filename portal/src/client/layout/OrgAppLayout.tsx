import {
  IconClipboardList,
  IconMessages,
  IconShieldLock,
  IconUserCircle,
} from "@tabler/icons-react";
import { useMemo, useState, type ReactNode } from "react";
import { useNavigate, type NavigateFunction } from "react-router";
import { logout, useAuth } from "wasp/client/auth";
import {
  getTenantConversations,
  getTenantRequests,
  listMyOrganizations,
  useQuery,
} from "wasp/client/operations";
import { type Branding } from "../branding/themes";
import {
  OrgSwitcher,
  type CommandAction,
  type Crumb,
  type SwitcherLink,
} from "../components/layout";
import { orgHomePath, PLATFORM_HOME } from "../entry";
import { channelLabel, itemTypeLabel } from "../formatting";
import { navPath, type NavContext } from "../nav";
import { AppLayout } from "./AppLayout";

/**
 * `AppLayout` with the portal plugged into it.
 *
 * `AppLayout` may not import Wasp — that is what makes the shell testable —
 * so this is the one file that knows who is signed in, which organisations
 * they belong to and how to sign out. Every page under `/app/:orgSlug`
 * renders inside it, most of them through `OrgShell`.
 */

export function OrgAppLayout({
  orgSlug,
  orgName,
  role,
  breadcrumbs = [],
  fixed,
  fluid,
  branding,
  children,
}: {
  orgSlug: string;
  /** The organisation's name, when the caller already fetched it. */
  orgName?: string;
  /** This viewer's role here, when the caller already knows it. */
  role?: "OWNER" | "STAFF";
  /** The trail after the organisation, which this file adds itself. */
  breadcrumbs?: Crumb[];
  fixed?: boolean;
  fluid?: boolean;
  /**
   * The organisation's branding, when the caller fetched it: the logo goes to
   * the switcher's mark, the preset and accent to the shell's tokens.
   */
  branding?: Branding | null;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const { data: user } = useAuth();
  const { data: organizations } = useQuery(listMyOrganizations);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const mine = organizations ?? [];
  const here = mine.find((org) => org.slug === orgSlug);
  const context: NavContext = {
    orgSlug,
    role: role ?? here?.role ?? "STAFF",
    isAdmin: Boolean(user?.isAdmin),
  };

  const actions = usePaletteActions(orgSlug, paletteOpen, navigate);

  return (
    <AppLayout
      context={context}
      breadcrumbs={[
        { label: orgName ?? here?.name ?? orgSlug, to: `/app/${orgSlug}` },
        ...breadcrumbs,
      ]}
      orgSwitcher={
        <OrgSwitcher
          orgs={mine}
          currentSlug={orgSlug}
          logoUrl={branding?.logoDataUrl}
          onSelect={(slug) => navigate(orgHomePath(slug))}
          links={switcherLinks(Boolean(user?.isAdmin))}
        />
      }
      profile={{
        name: user?.username ?? user?.email ?? "You",
        email: user?.email,
        items: profileItems(Boolean(user?.isAdmin)),
        onSignOut: () => {
          void logout();
        },
      }}
      actions={actions}
      paletteOpen={paletteOpen}
      onPaletteOpenChange={setPaletteOpen}
      fixed={fixed}
      fluid={fluid}
      branding={branding}
    >
      {children}
    </AppLayout>
  );
}

/** What the label says, in both places an admin can read it. */
const PLATFORM_DASHBOARD = "Platform dashboard";

/**
 * The user menu. There is no "your organisations" entry any more: `/app` is a
 * resolver, not a list, so for almost everybody that link led straight back to
 * the page they were already on. Moving between organisations is the switcher
 * at the top of the sidebar, which is where the organisations are.
 *
 * An agency admin gets the one way out of a clinic's shell that is not a
 * clinic: the platform's own dashboard.
 */
function profileItems(isAdmin: boolean) {
  const items = [{ label: "Account", to: "/account", icon: IconUserCircle }];
  return isAdmin
    ? [
        ...items,
        {
          label: PLATFORM_DASHBOARD,
          to: PLATFORM_HOME,
          icon: IconShieldLock,
        },
      ]
    : items;
}

/**
 * The switcher's last entry, for an agency admin only: the other shell. It
 * sits under a rule, below the organisations, because it is not one of them.
 */
function switcherLinks(isAdmin: boolean): SwitcherLink[] {
  return isAdmin
    ? [
        {
          label: PLATFORM_DASHBOARD,
          to: PLATFORM_HOME,
          testId: "org-switcher-platform",
          icon: IconShieldLock,
        },
      ]
    : [];
}

/**
 * What the palette can open that is not a page: a request by its number, a
 * conversation by the digits of the number it came from.
 *
 * Both lists come from the operations the requests and conversations pages
 * already use — no new ones — and neither is asked for until someone opens the
 * palette, so the pages that have nothing to do with either cost nothing. The
 * entries name only what exists: a number no request carries offers nothing to
 * select, rather than a link that would go nowhere. Selecting one lands on the
 * page that shows it, with the thing itself named in the query string.
 */
function usePaletteActions(
  orgSlug: string,
  enabled: boolean,
  navigate: NavigateFunction,
): CommandAction[] {
  const { data: requests } = useQuery(
    getTenantRequests,
    { slug: orgSlug },
    { enabled },
  );
  const { data: conversations } = useQuery(
    getTenantConversations,
    { slug: orgSlug, channel: undefined, band: undefined, page: 1 },
    { enabled },
  );

  return useMemo(() => {
    const actions: CommandAction[] = [];

    for (const item of [
      ...(requests?.open ?? []),
      ...(requests?.resolved ?? []),
    ]) {
      actions.push({
        group: "Requests",
        label: `#${item.id} · ${item.summary || itemTypeLabel(item.type)}`,
        value: [
          "request",
          item.id,
          item.summary ?? "",
          item.contact_name ?? "",
          item.contact_phone ?? "",
        ].join(" "),
        icon: IconClipboardList,
        run: () =>
          navigate(
            `${navPath("/app/:orgSlug/requests", orgSlug)}?item=${item.id}`,
          ),
      });
    }

    for (const row of conversations?.items ?? []) {
      actions.push({
        group: "Conversations",
        label: `${row.caller_masked ?? "no number"} · ${channelLabel(
          row.channel,
        )}`,
        value: [
          "conversation",
          row.caller_masked ?? "",
          row.channel,
          row.id,
        ].join(" "),
        icon: IconMessages,
        run: () =>
          navigate(
            `${navPath(
              "/app/:orgSlug/conversations",
              orgSlug,
            )}?conversation=${encodeURIComponent(row.id)}`,
          ),
      });
    }

    return actions;
  }, [orgSlug, requests, conversations, navigate]);
}
