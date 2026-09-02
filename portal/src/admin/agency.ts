/**
 * What the agency's tenants table is made of, and the arithmetic behind it.
 *
 * Browser-safe on purpose: the server operation builds these rows and the page
 * sorts and renders them, and both import the same rules. Nothing here invents
 * a number — every count comes from the runtime, and the only thing computed
 * in the portal is recurring revenue, from the subscription the portal itself
 * owns.
 */

import { isEntitlingStatus } from "../payment/entitlement";
import { PLAN_MONTHLY_CAD } from "../payment/plans";

/**
 * The list price of the single plan, in Canadian dollars per month. It lives
 * with the plan itself (`src/payment/plans.ts`) and is re-exported here because
 * this is where the agency's MRR line is computed. Stripe holds the price of
 * record; the pages that print it say so rather than implying the figure came
 * back from Stripe.
 */
export { PLAN_MONTHLY_CAD } from "../payment/plans";

/**
 * The Stripe statuses in which a subscription is still being paid for — the
 * same list that decides whether the clinic's pages open
 * (`src/payment/entitlement.ts`). "We are being paid" and "they get the
 * service" are one question, and answering it in two places is how they drift.
 */
export function isPayingStatus(status: string | null | undefined): boolean {
  return isEntitlingStatus(status);
}

export function mrrCadFor(
  status: string | null | undefined,
  monthlyCad: number = PLAN_MONTHLY_CAD,
): number {
  return isPayingStatus(status) ? monthlyCad : 0;
}

/** One client of the agency, as the tenants table shows it. */
export type AgencyTenantRow = {
  organizationId: string;
  name: string;
  slug: string;
  runtimeTenantId: string;
  /** Whether the runtime knows this tenant. An organisation can exist before it does. */
  configured: boolean;
  /** Why the runtime numbers are missing, in words, when they are. */
  problem: string | null;
  configVersion: number | null;

  // This month so far, in the tenant's own timezone, as the runtime counted it.
  calls: number;
  callMinutes: number;
  texts: number;
  chats: number;
  estCostCad: number;

  openItems: number;
  overdueItems: number;
  lastActivityAt: string | null;

  subscriptionStatus: string | null;
  subscriptionPlan: string | null;
  mrrCad: number;
};

export function totalMrrCad(rows: AgencyTenantRow[]): number {
  return rows.reduce((sum, row) => sum + row.mrrCad, 0);
}

/** The later of a tenant's last call and last text, or nothing if it has had neither. */
export function lastActivityOf(health: {
  last_call_at: string | null;
  last_sms_at: string | null;
}): string | null {
  const seen = [health.last_call_at, health.last_sms_at].filter(
    (value): value is string => Boolean(value),
  );
  if (seen.length === 0) {
    return null;
  }
  return seen.reduce((latest, value) =>
    Date.parse(value) > Date.parse(latest) ? value : latest,
  );
}

export type SortKey =
  | "name"
  | "calls"
  | "texts"
  | "cost"
  | "open"
  | "overdue"
  | "activity"
  | "mrr"
  | "version";

export type SortDirection = "asc" | "desc";

type Comparable = string | number | null;

function valueOf(row: AgencyTenantRow, key: SortKey): Comparable {
  switch (key) {
    case "name":
      return row.name.toLocaleLowerCase();
    case "calls":
      return row.calls;
    case "texts":
      return row.texts;
    case "cost":
      return row.estCostCad;
    case "open":
      return row.openItems;
    case "overdue":
      return row.overdueItems;
    case "activity":
      return row.lastActivityAt === null
        ? null
        : Date.parse(row.lastActivityAt);
    case "mrr":
      return row.mrrCad;
    case "version":
      return row.configVersion;
  }
}

/**
 * Sorts a copy. A row with nothing in the column — a tenant that has never had
 * a call, an organisation the runtime does not know yet — goes last in either
 * direction, because "no activity" is not the smallest activity.
 */
export function sortTenantRows(
  rows: AgencyTenantRow[],
  key: SortKey,
  direction: SortDirection,
): AgencyTenantRow[] {
  const factor = direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const a = valueOf(left, key);
    const b = valueOf(right, key);
    if (a === null && b === null) {
      return left.name.localeCompare(right.name);
    }
    if (a === null) {
      return 1;
    }
    if (b === null) {
      return -1;
    }
    if (typeof a === "string" || typeof b === "string") {
      return String(a).localeCompare(String(b)) * factor;
    }
    return (a - b) * factor;
  });
}
