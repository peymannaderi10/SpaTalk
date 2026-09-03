import { type AuthUser } from "wasp/auth";
import { getDailyStats, useQuery } from "wasp/client/operations";
import { PageHeader } from "../../../client/components/page-header";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "../../../client/components/ui/alert";
import { cn } from "../../../client/utils";
import { DefaultLayout } from "../../layout/DefaultLayout";
import { RecurringRevenueCard } from "./RecurringRevenueCard";
import { RevenueAndProfitChart } from "./RevenueAndProfitChart";
import { TotalPayingUsersCard } from "./TotalPayingUsersCard";
import { TotalRevenueCard } from "./TotalRevenueCard";
import { TotalSignupsCard } from "./TotalSignupsCard";

/**
 * The agency's own numbers, in the kit's dashboard arrangement
 * (`src/features/dashboard/index.tsx` in `satnaing/shadcn-admin`): a row of
 * stat cards, then the chart panel, then the "recent" list.
 */
export function AnalyticsDashboardPage({ user }: { user: AuthUser }) {
  const { data: stats, isLoading, error } = useQuery(getDailyStats);

  // The signups and revenue block is one thing and the agency's own recurring
  // revenue is another: a daily-stats job that has not run yet must not take
  // the whole page down with it, which is what an early return did.
  if (error) {
    return (
      <DefaultLayout user={user}>
        <div className="flex flex-1 flex-col gap-4 sm:gap-6">
          <PageHeader
            title="Platform"
            description="Signups, revenue and what every clinic is paying."
          />
          <Alert variant="destructive">
            <AlertTitle>The daily statistics could not be read</AlertTitle>
            <AlertDescription>
              {error.message || "Something went wrong while fetching stats."}
            </AlertDescription>
          </Alert>
          <div className="grid grid-cols-12 gap-4">
            <RecurringRevenueCard />
          </div>
        </div>
      </DefaultLayout>
    );
  }

  return (
    <DefaultLayout user={user}>
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="Platform"
          description="Signups, revenue and what every clinic is paying."
        />

        <div className="relative">
          <div className={cn("space-y-4", { "opacity-25": !stats })}>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <TotalRevenueCard
                dailyStats={stats?.dailyStats}
                weeklyStats={stats?.weeklyStats}
                isLoading={isLoading}
              />
              <TotalPayingUsersCard
                dailyStats={stats?.dailyStats}
                isLoading={isLoading}
              />
              <TotalSignupsCard
                dailyStats={stats?.dailyStats}
                isLoading={isLoading}
              />
            </div>

            <div className="grid grid-cols-12 gap-4">
              <RevenueAndProfitChart
                weeklyStats={stats?.weeklyStats}
                isLoading={isLoading}
              />
            </div>
          </div>

          {!stats && (
            <div className="bg-background/50 absolute inset-0 flex items-start justify-center">
              <Alert className="max-w-md shadow-lg">
                <AlertTitle>No daily stats generated yet</AlertTitle>
                <AlertDescription>
                  Stats will appear here once the daily stats job has run.
                </AlertDescription>
              </Alert>
            </div>
          )}
        </div>

        {/* Outside the stats block on purpose: the agency's own recurring
            revenue does not depend on the daily-stats job having run, and the
            "no stats yet" overlay must not sit on top of it. */}
        <div className="grid grid-cols-12 gap-4">
          <RecurringRevenueCard />
        </div>
      </div>
    </DefaultLayout>
  );
}
