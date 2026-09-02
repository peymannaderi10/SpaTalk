import { useMemo, useState } from "react";
import { Link } from "react-router";
import { type AuthUser } from "wasp/auth";
import { getAgencyTenants, useQuery } from "wasp/client/operations";
import { formatCad, formatDateTime, formatMinutes } from "../client/formatting";
import {
  PLAN_MONTHLY_CAD,
  sortTenantRows,
  totalMrrCad,
  type AgencyTenantRow,
  type SortDirection,
  type SortKey,
} from "./agency";
import { DefaultLayout } from "./layout/DefaultLayout";

/**
 * Every client of the agency on one page: what their front desk did this
 * month, what it cost us, what they owe, and what is late.
 *
 * Each number is the runtime's, read through `/internal` when the page loads.
 * The one thing computed here is recurring revenue, which is the portal's own
 * to know, and the page says which price it used.
 */

const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "name", label: "Tenant", numeric: false },
  { key: "calls", label: "Calls", numeric: true },
  { key: "texts", label: "Texts", numeric: true },
  { key: "cost", label: "Est. cost", numeric: true },
  { key: "open", label: "Open", numeric: true },
  { key: "overdue", label: "Overdue", numeric: true },
  { key: "activity", label: "Last activity", numeric: false },
  { key: "version", label: "Config", numeric: true },
  { key: "mrr", label: "Subscription", numeric: false },
];

export function TenantsPage({ user }: { user: AuthUser }) {
  const { data, isLoading, error } = useQuery(getAgencyTenants);
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({
    key: "name",
    direction: "asc",
  });

  const rows = useMemo(
    () => sortTenantRows(data ?? [], sort.key, sort.direction),
    [data, sort],
  );

  function toggle(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "name" ? "asc" : "desc" },
    );
  }

  return (
    <DefaultLayout user={user}>
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h1 className="text-foreground text-2xl font-semibold">Tenants</h1>
        <Link
          to="/admin/tenants/new"
          className="border-border rounded-md border px-3 py-1.5 text-sm"
        >
          New tenant
        </Link>
      </div>

      {isLoading && (
        <p className="text-muted-foreground mt-6 text-sm">Loading…</p>
      )}

      {error && (
        <p
          data-testid="tenants-problem"
          className="border-border text-foreground mt-6 rounded-md border p-4 text-sm"
        >
          {error.message}
        </p>
      )}

      {data && (
        <>
          <p className="text-muted-foreground mt-2 text-sm">
            This month so far, in each tenant's own timezone.{" "}
            <span data-testid="agency-mrr">{formatCad(totalMrrCad(rows))}</span>{" "}
            recurring, at the list price of {formatCad(PLAN_MONTHLY_CAD)} per
            subscribed tenant per month.
          </p>

          <div className="mt-6 overflow-x-auto">
            <table
              data-testid="tenants-table"
              className="w-full min-w-4xl border-collapse text-sm"
            >
              <thead>
                <tr className="border-border border-b text-left">
                  {COLUMNS.map((column) => (
                    <th
                      key={column.key}
                      className={
                        column.numeric
                          ? "px-3 py-2 text-right font-medium"
                          : "px-3 py-2 font-medium"
                      }
                    >
                      <button
                        type="button"
                        data-testid={`sort-${column.key}`}
                        onClick={() => toggle(column.key)}
                        className="hover:text-foreground text-muted-foreground"
                      >
                        {column.label}
                        {sort.key === column.key
                          ? sort.direction === "asc"
                            ? " ↑"
                            : " ↓"
                          : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <Row key={row.organizationId} row={row} />
                ))}
              </tbody>
            </table>
          </div>

          {rows.length === 0 && (
            <p className="text-muted-foreground mt-6 text-sm">
              No organisations yet. Onboard one with the wizard.
            </p>
          )}
        </>
      )}
    </DefaultLayout>
  );
}

function Row({ row }: { row: AgencyTenantRow }) {
  const cell = (name: string) => `tenant-${row.slug}-${name}`;

  return (
    <tr
      data-testid={`tenant-row-${row.slug}`}
      className="border-border border-b"
    >
      <td className="px-3 py-2" data-testid="tenant-name">
        <Link className="underline" to={`/app/${row.slug}/overview`}>
          {row.name}
        </Link>
        <div className="text-muted-foreground text-xs">
          {row.runtimeTenantId}
          {!row.configured && (
            <span className="text-foreground"> · Not configured</span>
          )}
        </div>
        {row.problem && (
          <div className="text-muted-foreground text-xs">{row.problem}</div>
        )}
      </td>
      <td className="px-3 py-2 text-right" data-testid={cell("calls")}>
        {row.calls}
      </td>
      <td className="px-3 py-2 text-right" data-testid={cell("texts")}>
        {row.texts}
      </td>
      <td className="px-3 py-2 text-right" data-testid={cell("cost")}>
        {formatCad(row.estCostCad)}
      </td>
      <td className="px-3 py-2 text-right" data-testid={cell("open")}>
        {row.openItems}
      </td>
      <td className="px-3 py-2 text-right" data-testid={cell("overdue")}>
        {row.overdueItems}
      </td>
      <td className="px-3 py-2" data-testid={cell("activity")}>
        {row.lastActivityAt ? formatDateTime(row.lastActivityAt) : "—"}
        <div className="text-muted-foreground text-xs">
          {formatMinutes(row.callMinutes)} call minutes
        </div>
      </td>
      <td className="px-3 py-2 text-right" data-testid={cell("version")}>
        {row.configVersion === null ? "—" : `v${row.configVersion}`}
      </td>
      <td className="px-3 py-2" data-testid={cell("subscription")}>
        {row.subscriptionStatus ? (
          <>
            {row.subscriptionStatus}
            <div className="text-muted-foreground text-xs">
              {formatCad(row.mrrCad)} per month
            </div>
          </>
        ) : (
          "No subscription"
        )}
      </td>
    </tr>
  );
}
