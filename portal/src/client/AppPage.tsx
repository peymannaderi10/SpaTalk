import { Link } from "react-router";
import { type AuthUser } from "wasp/auth";
import { listMyOrganizations, useQuery } from "wasp/client/operations";

/**
 * The doorway into the app: the organisations this person can open. Each one
 * leads to `/app/:orgSlug`, where its pages live.
 */
export function AppPage({ user }: { user: AuthUser }) {
  const { data: organizations, isLoading } = useQuery(listMyOrganizations);

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-foreground text-2xl font-semibold">Your front desk</h1>
      <p className="text-muted-foreground mt-4 text-sm">
        Signed in as {user.email ?? user.id}.
      </p>

      {isLoading ? (
        <p className="text-muted-foreground mt-8 text-sm">Loading…</p>
      ) : organizations && organizations.length > 0 ? (
        <ul className="mt-8 space-y-3">
          {organizations.map((org) => (
            <li key={org.id} className="border-border rounded-lg border p-4">
              <Link
                className="text-foreground text-base font-medium underline"
                to={`/app/${org.slug}`}
              >
                {org.name}
              </Link>
              <p className="text-muted-foreground mt-1 text-sm">
                You are {org.role} here.
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground mt-8 text-sm">
          No organisation yet. An invitation from your clinic, or from the
          agency, puts one here.
        </p>
      )}
    </main>
  );
}
