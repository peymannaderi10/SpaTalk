import { IconBuildingStore } from "@tabler/icons-react";
import { Link } from "react-router";
import { getAgencyRevenue, useQuery } from "wasp/client/operations";
import { EmptyState } from "../../../client/components/empty-state";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../../client/components/ui/card";
import { formatCad } from "../../../client/formatting";

/**
 * Recurring revenue, per client, beside the template's own revenue numbers.
 *
 * It is counted from the subscription the portal itself keeps on each
 * organisation, at the plan's list price, and the card says as much: Stripe
 * holds the price of record, and this is the agency's own arithmetic.
 *
 * The panel is the kit's "recent" list (`recent-sales.tsx` in
 * `src/features/dashboard/components`): a row per client, the name and its
 * subscription on the left, the money on the right.
 */
export function RecurringRevenueCard() {
  const { data, isLoading, error } = useQuery(getAgencyRevenue);

  return (
    <Card className="col-span-12">
      <CardHeader>
        <CardTitle>Recurring revenue by tenant</CardTitle>
        {data && (
          <CardDescription>
            <span data-testid="mrr-total" className="text-foreground font-medium">
              {formatCad(data.totalMrrCad)}
            </span>{" "}
            per month from {data.payingCount} of {data.rows.length}{" "}
            {data.rows.length === 1 ? "organisation" : "organisations"}, at the
            list price of {formatCad(data.planMonthlyCad)} each. Stripe holds
            the price of record.
          </CardDescription>
        )}
      </CardHeader>

      <CardContent>
        {isLoading && (
          <p className="text-muted-foreground text-sm">Loading…</p>
        )}
        {error && (
          <p className="text-muted-foreground text-sm">{error.message}</p>
        )}

        {data && data.rows.length === 0 && (
          <EmptyState
            title="No organisation yet"
            description="Onboard one with the wizard and it appears here."
            icon={IconBuildingStore}
            className="border-0"
          />
        )}

        {data && data.rows.length > 0 && (
          <ul className="space-y-6">
            {data.rows.map((row) => (
              <li
                key={row.organizationId}
                data-testid={`mrr-row-${row.slug}`}
                className="flex items-center gap-4"
              >
                <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-full">
                  <IconBuildingStore className="size-4" />
                </span>
                <div className="flex flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <div className="space-y-1">
                    <Link
                      className="text-sm leading-none font-medium underline-offset-4 hover:underline"
                      to={`/app/${row.slug}/overview`}
                    >
                      {row.name}
                    </Link>
                    <p className="text-muted-foreground text-sm">
                      {row.subscriptionStatus ?? "No subscription"}
                    </p>
                  </div>
                  <div className="font-medium">{formatCad(row.mrrCad)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
