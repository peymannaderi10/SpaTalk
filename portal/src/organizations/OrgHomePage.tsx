import {
  IconArrowRight,
  IconClipboardList,
  IconMessages,
  IconServerBolt,
  IconSettings,
  IconChartBar,
  IconUsers,
  IconUserShield,
  type TablerIcon,
} from "@tabler/icons-react";
import { type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { type AuthUser } from "wasp/auth";
import { getOrganization, useQuery } from "wasp/client/operations";
import { PageHeader } from "../client/components/page-header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";
import { OrgAppLayout } from "../client/layout/OrgAppLayout";

/**
 * The landing page for one organisation, in the kit's dashboard idiom
 * (`src/features/dashboard/index.tsx` in `satnaing/shadcn-admin`): a row of
 * stat cards saying what this organisation is, then the pages that hang off
 * it as cards a person can walk into.
 */
export function OrgHomePage({ user }: { user: AuthUser }) {
  const { orgSlug = "" } = useParams();
  const {
    data: org,
    isLoading,
    error,
  } = useQuery(getOrganization, { slug: orgSlug });

  if (isLoading) {
    return (
      <PageShell slug={orgSlug}>
        <p className="text-muted-foreground text-sm">Loading…</p>
      </PageShell>
    );
  }

  if (error || !org) {
    return (
      <PageShell slug={orgSlug}>
        <PageHeader
          title="This organisation is not open to you"
          description={
            error?.message ??
            "Ask an owner of the organisation for an invitation."
          }
        />
        <p className="text-sm">
          <Link className="underline underline-offset-4" to="/app">
            Back to your organisations
          </Link>
        </p>
      </PageShell>
    );
  }

  const pages: {
    label: string;
    description: string;
    to: string;
    icon: TablerIcon;
  }[] = [
    {
      label: "Overview",
      description: "What the front desk has done this month, and what is late.",
      to: `/app/${org.slug}/overview`,
      icon: IconChartBar,
    },
    {
      label: "Conversations",
      description: "Every call, text and chat, with the transcript behind it.",
      to: `/app/${org.slug}/conversations`,
      icon: IconMessages,
    },
    {
      label: "Requests",
      description: "What was promised, who owns it, and when it is due.",
      to: `/app/${org.slug}/requests`,
      icon: IconClipboardList,
    },
    {
      label: "Settings",
      description: "Hours, services, knowledge and the fixed wording.",
      to: `/app/${org.slug}/settings`,
      icon: IconSettings,
    },
  ];

  if (org.role === "OWNER") {
    pages.push({
      label: "People",
      description: "Who is in this organisation, and who has been invited.",
      to: `/app/${org.slug}/settings/people`,
      icon: IconUsers,
    });
  }

  return (
    <PageShell slug={orgSlug} org={org}>
      <PageHeader
        title={org.name}
        description={`Signed in as ${user.email ?? user.id}.`}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat label="Your role" value={org.role} icon={IconUserShield} />
        <Stat
          label="Runtime tenant"
          value={org.runtimeTenantId}
          icon={IconServerBolt}
        />
        <Stat
          label="People"
          value={String(org.members.length)}
          icon={IconUsers}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {pages.map((page) => (
          <Link key={page.to} to={page.to} className="group">
            <Card className="h-full gap-3 transition-shadow hover:shadow-md">
              <CardHeader>
                <div className="mb-2 flex items-center justify-between">
                  <span className="bg-muted flex size-10 items-center justify-center rounded-lg">
                    <page.icon className="size-5" />
                  </span>
                  <IconArrowRight className="text-muted-foreground size-4 transition-transform group-hover:translate-x-1" />
                </div>
                <CardTitle className="text-base">{page.label}</CardTitle>
                <CardDescription>{page.description}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </PageShell>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: TablerIcon;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div className="truncate text-2xl font-bold">{value}</div>
      </CardContent>
    </Card>
  );
}

/**
 * The organisation's root sits inside the app shell like every page under it,
 * so the sidebar is there whether a person arrived here from the switcher or
 * from a bookmark. It is the one page in an organisation with no crumb of its
 * own: the organisation's name is already the first crumb.
 */
function PageShell({
  slug,
  org,
  children,
}: {
  slug: string;
  org?: { name: string; slug: string; role: "OWNER" | "STAFF" };
  children: ReactNode;
}) {
  return (
    <OrgAppLayout
      orgSlug={org?.slug ?? slug}
      orgName={org?.name}
      role={org?.role}
    >
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">{children}</div>
    </OrgAppLayout>
  );
}
