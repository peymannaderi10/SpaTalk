import {
  IconArrowDown,
  IconArrowUp,
  IconBuildingStore,
  IconPlus,
  IconSelector,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { type AuthUser } from "wasp/auth";
import { getAgencyTenants, useQuery } from "wasp/client/operations";
import { EmptyState } from "../client/components/empty-state";
import { PageHeader } from "../client/components/page-header";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "../client/components/ui/alert";
import { Badge } from "../client/components/ui/badge";
import { Button } from "../client/components/ui/button";
import { Input } from "../client/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../client/components/ui/table";
import { formatCad, formatDateTime, formatMinutes } from "../client/formatting";
import { cn } from "../client/utils";
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
 * The table is the kit's (`src/features/tasks/components/tasks-table.tsx` in
 * `satnaing/shadcn-admin`): its toolbar above a bordered table with sortable
 * headers. The sort itself stays `sortTenantRows`, which knows how a missing
 * number and a missing date should fall.
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
  const [search, setSearch] = useState("");

  const rows = useMemo(
    () => sortTenantRows(data ?? [], sort.key, sort.direction),
    [data, sort],
  );

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle === "") {
      return rows;
    }
    return rows.filter((row) =>
      [row.name, row.slug, row.runtimeTenantId]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [rows, search]);

  function toggle(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "name" ? "asc" : "desc" },
    );
  }

  return (
    <DefaultLayout user={user}>
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="Tenants"
          description="Every clinic the agency runs a front desk for."
          actions={
            <Button asChild>
              <Link to="/admin/tenants/new">
                <IconPlus className="size-4" />
                New tenant
              </Link>
            </Button>
          }
        />

        {data && (
          <p className="text-muted-foreground text-sm">
            This month so far, in each tenant's own timezone.{" "}
            <span data-testid="agency-mrr" className="text-foreground font-medium">
              {formatCad(totalMrrCad(rows))}
            </span>{" "}
            recurring, at the list price of {formatCad(PLAN_MONTHLY_CAD)} per
            subscribed tenant per month.
          </p>
        )}

        {error && (
          <Alert variant="destructive" data-testid="tenants-problem">
            <AlertTitle>The tenants could not be read</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        )}

        {isLoading && (
          <p className="text-muted-foreground text-sm">Loading…</p>
        )}

        {data && (
          <div className="flex flex-1 flex-col gap-4">
            <div className="flex items-center" role="toolbar">
              <Input
                placeholder="Filter tenants…"
                data-testid="tenants-search"
                className="h-8 w-37.5 lg:w-62.5"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>

            <div className="overflow-x-auto rounded-md border">
              <Table
                data-testid="tenants-table"
                className="min-w-4xl border-collapse"
              >
                <TableHeader>
                  <TableRow>
                    {COLUMNS.map((column) => (
                      <TableHead
                        key={column.key}
                        className={column.numeric ? "text-right" : undefined}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          data-testid={`sort-${column.key}`}
                          onClick={() => toggle(column.key)}
                          className={cn(
                            "data-[state=open]:bg-accent -ms-2 h-8",
                            column.numeric && "ms-auto -me-2",
                          )}
                        >
                          <span>{column.label}</span>
                          {sort.key === column.key ? (
                            sort.direction === "asc" ? (
                              <IconArrowUp className="size-4" />
                            ) : (
                              <IconArrowDown className="size-4" />
                            )
                          ) : (
                            <IconSelector className="size-4" />
                          )}
                        </Button>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shown.map((row) => (
                    <Row key={row.organizationId} row={row} />
                  ))}
                </TableBody>
              </Table>
            </div>

            {shown.length === 0 && (
              <EmptyState
                title={
                  rows.length === 0
                    ? "No organisation yet"
                    : "No tenant matches that"
                }
                description={
                  rows.length === 0
                    ? "Onboard one with the wizard."
                    : "Clear the filter to see every tenant."
                }
                icon={IconBuildingStore}
                testId="tenants-empty"
              />
            )}
          </div>
        )}
      </div>
    </DefaultLayout>
  );
}

function Row({ row }: { row: AgencyTenantRow }) {
  const cell = (name: string) => `tenant-${row.slug}-${name}`;

  return (
    <TableRow data-testid={`tenant-row-${row.slug}`}>
      <TableCell data-testid="tenant-name">
        <Link
          className="font-medium underline-offset-4 hover:underline"
          to={`/app/${row.slug}/overview`}
        >
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
      </TableCell>
      <TableCell className="text-right" data-testid={cell("calls")}>
        {row.calls}
      </TableCell>
      <TableCell className="text-right" data-testid={cell("texts")}>
        {row.texts}
      </TableCell>
      <TableCell className="text-right" data-testid={cell("cost")}>
        {formatCad(row.estCostCad)}
      </TableCell>
      <TableCell className="text-right" data-testid={cell("open")}>
        {row.openItems}
      </TableCell>
      <TableCell className="text-right" data-testid={cell("overdue")}>
        {row.overdueItems}
      </TableCell>
      <TableCell data-testid={cell("activity")}>
        {row.lastActivityAt ? formatDateTime(row.lastActivityAt) : "—"}
        <div className="text-muted-foreground text-xs">
          {formatMinutes(row.callMinutes)} call minutes
        </div>
      </TableCell>
      <TableCell className="text-right" data-testid={cell("version")}>
        {row.configVersion === null ? "—" : `v${row.configVersion}`}
      </TableCell>
      <TableCell data-testid={cell("subscription")}>
        {row.subscriptionStatus ? (
          <>
            <Badge variant="outline" className="font-normal">
              {row.subscriptionStatus}
            </Badge>
            <div className="text-muted-foreground text-xs">
              {formatCad(row.mrrCad)} per month
            </div>
          </>
        ) : (
          <span className="text-muted-foreground">No subscription</span>
        )}
      </TableCell>
    </TableRow>
  );
}
