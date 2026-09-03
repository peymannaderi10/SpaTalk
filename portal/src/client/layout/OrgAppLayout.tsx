import {
  IconBuildingStore,
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
import {
  OrgSwitcher,
  type CommandAction,
  type Crumb,
} from "../components/layout";
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
          onSelect={(slug) => navigate(`/app/${slug}`)}
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
    >
      {children}
    </AppLayout>
  );
}

function profileItems(isAdmin: boolean) {
  const items = [
    { label: "Your organisations", to: "/app", icon: IconBuildingStore },
    { label: "Account", to: "/account", icon: IconUserCircle },
  ];
  return isAdmin
    ? [...items, { label: "Platform", to: "/admin", icon: IconShieldLock }]
    : items;
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
        label: `${row.caller_masked ?? "no number"} · ${channelLabel(row.channel)}`,
        value: ["conversation", row.caller_masked ?? "", row.channel, row.id].join(
          " ",
        ),
        icon: IconMessages,
        run: () =>
          navigate(
            `${navPath("/app/:orgSlug/conversations", orgSlug)}?conversation=${encodeURIComponent(row.id)}`,
          ),
      });
    }

    return actions;
  }, [orgSlug, requests, conversations, navigate]);
}
