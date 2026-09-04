import {
  IconArrowRight,
  IconBuildingStore,
  IconShieldCheck,
  IconUser,
} from "@tabler/icons-react";
import { Link } from "react-router";
import { type AuthUser } from "wasp/auth";
import { listMyOrganizations, useQuery } from "wasp/client/operations";
import { EmptyState } from "./components/empty-state";
import { PageHeader } from "./components/page-header";
import { Badge } from "./components/ui/badge";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";

/**
 * The doorway into the app: the organisations this person can open. Each one
 * leads to `/app/:orgSlug`, where its pages live.
 *
 * It is outside the sidebar shell — there is no organisation to be in yet — so
 * it borrows the kit's page header and its cards.
 */
export function AppPage({ user }: { user: AuthUser }) {
  const { data: organizations, isLoading } = useQuery(listMyOrganizations);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-16">
      <PageHeader
        title="Organisations"
        description={`Signed in as ${user.email ?? user.id}.`}
      />

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : organizations && organizations.length > 0 ? (
        <ul className="grid gap-4 sm:grid-cols-2">
          {organizations.map((org) => (
            <li key={org.id}>
              <Link to={`/app/${org.slug}`} className="group">
                <Card className="h-full gap-3 transition-shadow hover:shadow-md">
                  <CardHeader>
                    <div className="mb-2 flex items-center justify-between">
                      <span className="bg-muted flex size-10 items-center justify-center rounded-lg">
                        <IconBuildingStore className="size-5" />
                      </span>
                      <IconArrowRight className="text-muted-foreground size-4 transition-transform group-hover:translate-x-1" />
                    </div>
                    <CardTitle className="text-base">{org.name}</CardTitle>
                    <CardDescription>
                      <Badge variant="outline" className="gap-1 font-normal">
                        {org.role === "OWNER" ? (
                          <IconShieldCheck className="size-3" />
                        ) : (
                          <IconUser className="size-3" />
                        )}
                        You are {org.role} here
                      </Badge>
                    </CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          title="No organisation yet"
          description="An invitation from your clinic, or from the agency, puts one here."
          icon={IconBuildingStore}
          testId="no-organisations"
        />
      )}
    </main>
  );
}
