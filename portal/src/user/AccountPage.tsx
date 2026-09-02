import { Link } from "react-router";
import { listMyOrganizations, useQuery } from "wasp/client/operations";
import type { User } from "wasp/entities";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";
import { Separator } from "../client/components/ui/separator";

/**
 * The account page. It says who you are and which clinics you can open.
 *
 * There is no plan here: a subscription belongs to an organisation, not to a
 * person (portal plan, Task C6), so billing lives on each organisation's own
 * billing page and only its owners can reach it.
 */

const STATUS_WORDING: Record<string, string> = {
  active: "Subscribed",
  trialing: "In trial",
  cancel_at_period_end: "Subscribed, ending this billing period",
  past_due: "Payment past due",
  deleted: "Subscription ended",
};

export function AccountPage({ user }: { user: User }) {
  const { data: organizations, isLoading } = useQuery(listMyOrganizations);

  return (
    <div className="mt-10 px-6">
      <Card className="mb-4 lg:m-8">
        <CardHeader>
          <CardTitle className="text-foreground text-base font-semibold leading-6">
            Account
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="space-y-0">
            {!!user.email && (
              <Row label="Email address">
                <span className="text-foreground text-sm">{user.email}</span>
              </Row>
            )}
            {!!user.username && (
              <>
                <Separator />
                <Row label="Username">
                  <span className="text-foreground text-sm">
                    {user.username}
                  </span>
                </Row>
              </>
            )}
            <Separator />
            <Row label="Your organisations">
              {isLoading ? (
                <span className="text-muted-foreground text-sm">Loading…</span>
              ) : organizations && organizations.length > 0 ? (
                <ul className="space-y-2 text-sm">
                  {organizations.map((org) => (
                    <li key={org.id} data-testid="account-organization">
                      <Link className="underline" to={`/app/${org.slug}`}>
                        {org.name}
                      </Link>
                      <span className="text-muted-foreground">
                        {" — "}
                        {org.role === "OWNER" ? "owner" : "staff"},{" "}
                        {org.subscriptionStatus
                          ? STATUS_WORDING[org.subscriptionStatus] ??
                            org.subscriptionStatus
                          : "no subscription yet"}
                      </span>
                      {org.role === "OWNER" && (
                        <>
                          {" · "}
                          <Link
                            className="underline"
                            to={`/app/${org.slug}/billing`}
                          >
                            Billing
                          </Link>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="text-muted-foreground text-sm">
                  You are not in an organisation yet.
                </span>
              )}
            </Row>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="px-6 py-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 sm:gap-4">
        <div className="text-muted-foreground text-sm font-medium">{label}</div>
        <div className="text-foreground mt-1 text-sm sm:col-span-2 sm:mt-0">
          {children}
        </div>
      </div>
    </div>
  );
}
