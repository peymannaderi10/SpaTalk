import { Link } from "react-router";
import { getAgencyRevenue, useQuery } from "wasp/client/operations";
import { formatCad } from "../../../client/formatting";

/**
 * Recurring revenue, per client, beside the template's own revenue numbers.
 *
 * It is counted from the subscription the portal itself keeps on each
 * organisation, at the plan's list price, and the card says as much: Stripe
 * holds the price of record, and this is the agency's own arithmetic.
 */
export function RecurringRevenueCard() {
  const { data, isLoading, error } = useQuery(getAgencyRevenue);

  return (
    <div className="border-border bg-card col-span-12 rounded-lg border p-6">
      <h2 className="text-foreground text-lg font-medium">
        Recurring revenue by tenant
      </h2>

      {isLoading && (
        <p className="text-muted-foreground mt-2 text-sm">Loading…</p>
      )}
      {error && (
        <p className="text-muted-foreground mt-2 text-sm">{error.message}</p>
      )}

      {data && (
        <>
          <p className="text-muted-foreground mt-1 text-sm">
            <span
              data-testid="mrr-total"
              className="text-foreground font-medium"
            >
              {formatCad(data.totalMrrCad)}
            </span>{" "}
            per month from {data.payingCount} of {data.rows.length}{" "}
            {data.rows.length === 1 ? "organisation" : "organisations"}, at the
            list price of {formatCad(data.planMonthlyCad)} each. Stripe holds
            the price of record.
          </p>

          <ul className="mt-4 space-y-2 text-sm">
            {data.rows.map((row) => (
              <li
                key={row.organizationId}
                data-testid={`mrr-row-${row.slug}`}
                className="border-border flex flex-wrap items-baseline justify-between gap-2 rounded-md border p-3"
              >
                <Link className="underline" to={`/app/${row.slug}/overview`}>
                  {row.name}
                </Link>
                <span className="text-muted-foreground">
                  {row.subscriptionStatus ?? "No subscription"}
                </span>
                <span className="text-foreground font-medium">
                  {formatCad(row.mrrCad)}
                </span>
              </li>
            ))}
          </ul>

          {data.rows.length === 0 && (
            <p className="text-muted-foreground mt-2 text-sm">
              No organisations yet.
            </p>
          )}
        </>
      )}
    </div>
  );
}
