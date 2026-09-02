import { type AuthUser } from "wasp/auth";
import { getDailyStats, useQuery } from "wasp/client/operations";
import { cn } from "../../../client/utils";
import { DefaultLayout } from "../../layout/DefaultLayout";
import { RecurringRevenueCard } from "./RecurringRevenueCard";
import { RevenueAndProfitChart } from "./RevenueAndProfitChart";
import { TotalPayingUsersCard } from "./TotalPayingUsersCard";
import { TotalRevenueCard } from "./TotalRevenueCard";
import { TotalSignupsCard } from "./TotalSignupsCard";

export function AnalyticsDashboardPage({ user }: { user: AuthUser }) {
  const { data: stats, isLoading, error } = useQuery(getDailyStats);

  // The signups and revenue block is one thing and the agency's own recurring
  // revenue is another: a daily-stats job that has not run yet must not take
  // the whole page down with it, which is what an early return did.
  if (error) {
    return (
      <DefaultLayout user={user}>
        <div className="bg-card rounded-lg p-8 shadow-lg">
          <p className="text-2xl font-bold text-red-500">Error</p>
          <p className="text-muted-foreground mt-2 text-sm">
            {error.message || "Something went wrong while fetching stats."}
          </p>
        </div>

        <div className="2xl:mt-7.5 mt-4 grid grid-cols-12 gap-4 md:mt-6 md:gap-6">
          <RecurringRevenueCard />
        </div>
      </DefaultLayout>
    );
  }

  return (
    <DefaultLayout user={user}>
      <div className="relative">
        <div
          className={cn({
            "opacity-25": !stats,
          })}
        >
          <div className="2xl:gap-7.5 grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6 xl:grid-cols-3">
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

          <div className="2xl:mt-7.5 2xl:gap-7.5 mt-4 grid grid-cols-12 gap-4 md:mt-6 md:gap-6">
            <RevenueAndProfitChart
              weeklyStats={stats?.weeklyStats}
              isLoading={isLoading}
            />
          </div>
        </div>

        {!stats && (
          <div className="bg-background/50 absolute inset-0 flex items-start justify-center">
            <div className="bg-card rounded-lg p-8 shadow-lg">
              <p className="text-foreground text-2xl font-bold">
                No daily stats generated yet
              </p>
              <p className="text-muted-foreground mt-2 text-sm">
                Stats will appear here once the daily stats job has run
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Outside the stats block on purpose: the agency's own recurring revenue
          does not depend on the daily-stats job having run, and the "no stats
          yet" overlay must not sit on top of it. */}
      <div className="2xl:mt-7.5 mt-4 grid grid-cols-12 gap-4 md:mt-6 md:gap-6">
        <RecurringRevenueCard />
      </div>
    </DefaultLayout>
  );
}
