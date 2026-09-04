import {
  IconArrowRight,
  IconBuildingStore,
  IconShieldCheck,
  IconUser,
} from "@tabler/icons-react";
import { useEffect } from "react";
import { Link, useNavigate } from "react-router";
import { type AuthUser } from "wasp/auth";
import { listMyOrganizations, useQuery } from "wasp/client/operations";
import { BRAND } from "./brand";
import { EmptyState } from "./components/empty-state";
import { PageHeader } from "./components/page-header";
import { Badge } from "./components/ui/badge";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import { entryDestination, orgHomePath } from "./entry";

/**
 * `/app` — where signing in lands — is not a page but a decision.
 *
 * People who use this portal work for one business, so being asked to pick one
 * from a list of one was a question with no content. This route now resolves:
 * an agency admin goes on to the platform, a person in one organisation goes
 * into it, a person in none is told who invites them, and only the person an
 * admin has added to several is offered a choice. `entry.ts` holds the rule;
 * this file only acts on it.
 */
export function AppPage({ user }: { user: AuthUser }) {
  const navigate = useNavigate();
  const { data: organizations } = useQuery(listMyOrganizations);

  const destination = organizations
    ? entryDestination({
        isAdmin: Boolean(user.isAdmin),
        organizations,
      })
    : null;
  const goTo = destination?.kind === "redirect" ? destination.to : null;

  useEffect(() => {
    if (goTo) {
      // `replace`, so Back goes where the person came from rather than to a
      // route that would only send them here again.
      navigate(goTo, { replace: true });
    }
  }, [goTo, navigate]);

  // Nothing to read while the answer is still unknown, and nothing to read
  // once it is a redirect: either way this route is only being passed through.
  if (!destination || goTo) {
    return (
      <main
        className="flex min-h-[60vh] items-center justify-center px-6"
        data-testid="entry-loading"
      >
        <p className="text-muted-foreground text-sm">Loading…</p>
      </main>
    );
  }

  if (destination.kind === "none") {
    return (
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-16">
        <EmptyState
          title="You are not part of an organisation yet"
          description={`The person who set up your ${BRAND.name} sends the invitations. Ask them to invite ${user.email ?? "this address"}.`}
          icon={IconBuildingStore}
          testId="no-organisations"
        />
      </main>
    );
  }

  // Several. Only an admin adding one person to more than one organisation
  // produces this, and only they can say which one they meant.
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-16">
      <PageHeader
        title="Organisations"
        description={`Signed in as ${user.email ?? user.id}.`}
      />

      <ul className="grid gap-4 sm:grid-cols-2">
        {(organizations ?? []).map((org) => (
          <li key={org.id}>
            <Link to={orgHomePath(org.slug)} className="group">
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
    </main>
  );
}
