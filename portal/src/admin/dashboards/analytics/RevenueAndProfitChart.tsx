import { type DailyStatsProps } from "../../../analytics/stats";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../../client/components/ui/card";
import { formatCad } from "../../../client/formatting";

/**
 * Revenue and profit over the last seven days, in the kit's chart panel: the
 * card, its header, and one component owning everything inside it — the shape
 * of `src/features/dashboard/components/overview.tsx` in
 * `satnaing/shadcn-admin`.
 *
 * The body is a placeholder that draws the days it was given as proportional
 * bars. Task R3 puts the shadcn chart components (Recharts) inside it; this
 * file no longer imports ApexCharts, which is what that task removes.
 */
export function RevenueAndProfitChart({ weeklyStats }: DailyStatsProps) {
  const days = [...(weeklyStats ?? [])]
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
    .map((stat) => ({
      label: new Date(stat.date).toLocaleDateString(undefined, {
        weekday: "short",
        day: "numeric",
      }),
      revenue: stat.totalRevenue,
      profit: stat.totalProfit,
    }));

  const most = Math.max(1, ...days.map((day) => day.revenue));

  return (
    <Card className="col-span-12 xl:col-span-8">
      <CardHeader>
        <CardTitle>Revenue and profit</CardTitle>
        <CardDescription>The last seven days the job recorded.</CardDescription>
      </CardHeader>
      <CardContent>
        {days.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No day has been recorded yet.
          </p>
        ) : (
          <div className="space-y-4">
            {days.map((day) => (
              <div key={day.label} className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{day.label}</span>
                  <span className="font-medium">
                    {formatCad(day.revenue)}
                    <span className="text-muted-foreground font-normal">
                      {" "}
                      · {formatCad(day.profit)} profit
                    </span>
                  </span>
                </div>
                <div className="bg-muted h-2 w-full overflow-hidden rounded-full">
                  <div
                    className="bg-chart-1 h-full rounded-full"
                    style={{
                      width: `${Math.round((day.revenue / most) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
