import { type AuthUser } from "wasp/auth";
import { getRates, useQuery } from "wasp/client/operations";
import { PageHeader } from "../client/components/page-header";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "../client/components/ui/alert";
import { DefaultLayout } from "./layout/DefaultLayout";
import { QuoteBuilder } from "./QuoteBuilder";

/**
 * What a clinic would pay, worked out from what its front desk has to handle.
 *
 * This file does one thing: ask the runtime for the rates and hand them to
 * `QuoteBuilder`, which is where the page actually lives. The rates are the
 * runtime's own file — the one behind every `est_cost_cad` — fetched through
 * `getRates`, which refuses anyone who is not an agency admin, and never a copy
 * kept in the portal.
 *
 * The page is meant to be turned towards the person being quoted, so nothing
 * about the agency's side of the deal is on it until the admin opens the
 * Internal disclosure.
 */
export function AdminPricingPage({ user }: { user: AuthUser }) {
  return (
    <DefaultLayout user={user}>
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="Pricing"
          description="What a clinic would pay a month, from what its front desk has to handle."
        />
        <Body />
      </div>
    </DefaultLayout>
  );
}

function Body() {
  const { data, isLoading, error } = useQuery(getRates);

  if (isLoading) {
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  }
  if (error || !data) {
    return (
      <Alert variant="destructive" data-testid="pricing-problem">
        <AlertTitle>There is no price to show</AlertTitle>
        <AlertDescription>
          {error?.message ??
            "The front desk service did not answer with its rate file, so there is nothing to quote from."}
        </AlertDescription>
      </Alert>
    );
  }

  return <QuoteBuilder rates={data} />;
}
