import { type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router";
import { getOrganization, useQuery } from "wasp/client/operations";

/**
 * The frame every client page sits in: the organisation it is about, the
 * navigation between its pages, and the one place a refusal is turned into a
 * sentence instead of a blank screen.
 */

export type Org = {
  id: string;
  name: string;
  slug: string;
  runtimeTenantId: string;
  role: "OWNER" | "STAFF";
};

export function OrgShell({
  title,
  children,
}: {
  title: string;
  children: (org: Org) => ReactNode;
}) {
  const { orgSlug = "" } = useParams();
  const { data: org, isLoading, error } = useQuery(getOrganization, {
    slug: orgSlug,
  });

  if (isLoading) {
    return (
      <Frame title={title} slug={orgSlug}>
        <p className="text-muted-foreground text-sm">Loading…</p>
      </Frame>
    );
  }

  if (error || !org) {
    return (
      <Frame title={title} slug={orgSlug}>
        <p className="text-muted-foreground text-sm">
          {error?.message ??
            "This organisation is not open to you. Ask an owner for an invitation."}
        </p>
        <p className="mt-6 text-sm">
          <Link className="underline" to="/app">
            Back to your organisations
          </Link>
        </p>
      </Frame>
    );
  }

  return (
    <Frame title={title} slug={org.slug} org={org}>
      {children(org)}
    </Frame>
  );
}

const PAGES = [
  { label: "Overview", path: "overview" },
  { label: "Conversations", path: "conversations" },
  { label: "Requests", path: "requests" },
  { label: "Settings", path: "settings" },
] as const;

function Frame({
  title,
  slug,
  org,
  children,
}: {
  title: string;
  slug: string;
  org?: Org;
  children: ReactNode;
}) {
  const location = useLocation();

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <p className="text-muted-foreground text-sm">
        {org ? (
          <Link className="underline" to={`/app/${org.slug}`}>
            {org.name}
          </Link>
        ) : (
          slug
        )}
      </p>
      <h1 className="text-foreground mt-1 text-2xl font-semibold">{title}</h1>

      <nav className="border-border mt-6 flex flex-wrap gap-4 border-b pb-2 text-sm">
        {PAGES.map((page) => {
          const to = `/app/${slug}/${page.path}`;
          const current = location.pathname === to;
          return (
            <Link
              key={page.path}
              to={to}
              className={
                current
                  ? "text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground"
              }
            >
              {page.label}
            </Link>
          );
        })}
        {org?.role === "OWNER" && (
          <Link
            to={`/app/${slug}/settings/people`}
            className="text-muted-foreground hover:text-foreground"
          >
            People
          </Link>
        )}
      </nav>

      <div className="mt-8">{children}</div>
    </main>
  );
}

/** A refusal or an outage, said in one line rather than shown as a stack. */
export function Problem({ error }: { error: { message?: string } | null }) {
  if (!error) {
    return null;
  }
  return (
    <p
      data-testid="page-problem"
      className="border-border text-foreground mt-4 rounded-md border p-4 text-sm"
    >
      {error.message ?? "Something went wrong."}
    </p>
  );
}
