import { IconCircleCheck } from "@tabler/icons-react";
import { Link } from "react-router";
import { useAuth } from "wasp/client/auth";
import { listMyOrganizations, useQuery } from "wasp/client/operations";
import { routes } from "wasp/client/router";
import { Button } from "../client/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardTitle,
} from "../client/components/ui/card";
import {
  PaymentPlanId,
  PLAN_FEATURES,
  PLAN_PRICE_TEXT,
  prettyPaymentPlanName,
} from "./plans";

/**
 * One plan, one price, per clinic.
 *
 * A clinic subscribes, not a person, so this page cannot itself start a
 * checkout: it sends whoever is signed in to the billing page of the
 * organisation they mean.
 */

export function PricingPage() {
  const { data: user } = useAuth();
  const { data: organizations } = useQuery(listMyOrganizations, undefined, {
    enabled: !!user,
  });

  const mine = organizations ?? [];

  return (
    <div className="py-10 lg:mt-10">
      <div className="mx-auto max-w-3xl px-6 lg:px-8">
        <div id="pricing" className="mx-auto max-w-2xl text-center">
          <h2 className="text-foreground mt-2 text-4xl font-bold tracking-tight sm:text-5xl">
            One plan, per clinic
          </h2>
        </div>

        <div className="isolate mx-auto mt-16 grid max-w-md grid-cols-1 gap-y-8">
          <Card className="ring-primary relative flex grow flex-col justify-between overflow-hidden ring-2">
            <CardContent className="h-full justify-between p-8 xl:p-10">
              <CardTitle className="text-foreground text-lg font-semibold leading-8">
                {prettyPaymentPlanName(PaymentPlanId.FrontDesk)}
              </CardTitle>
              <p className="text-muted-foreground mt-4 text-sm leading-6">
                One clinic, every channel, one monthly price
              </p>
              <p className="mt-6 flex items-baseline gap-x-1">
                <span className="text-foreground text-4xl font-bold tracking-tight">
                  {PLAN_PRICE_TEXT}
                </span>
                <span className="text-muted-foreground text-sm font-semibold leading-6">
                  /month
                </span>
              </p>
              <ul
                role="list"
                className="text-muted-foreground mt-8 space-y-3 text-sm leading-6"
              >
                {PLAN_FEATURES.map((feature) => (
                  <li key={feature} className="flex gap-x-3">
                    <IconCircleCheck
                      className="text-primary h-5 w-5 flex-none"
                      aria-hidden="true"
                    />
                    {feature}
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter className="flex-col items-stretch gap-3">
              {!user && (
                <Link to={routes.LoginRoute.to}>
                  <Button className="w-full">Log in to subscribe</Button>
                </Link>
              )}
              {user && mine.length === 0 && (
                <p className="text-muted-foreground text-sm">
                  You are not in an organisation yet. The agency creates one for
                  each clinic before it can be subscribed.
                </p>
              )}
              {user &&
                mine.map((org) => (
                  <Link key={org.id} to={`/app/${org.slug}/billing`}>
                    <Button
                      className="w-full"
                      variant={org.entitled ? "outline" : "default"}
                    >
                      {org.entitled
                        ? `Manage billing for ${org.name}`
                        : `Subscribe ${org.name}`}
                    </Button>
                  </Link>
                ))}
            </CardFooter>
          </Card>
        </div>
      </div>
    </div>
  );
}
