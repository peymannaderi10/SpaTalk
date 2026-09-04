import { type DailyStatsProps } from "../../../analytics/stats";
import {
  RevenueChart,
  type RevenuePoint,
} from "../../../client/charts/revenue-chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../../client/components/ui/card";

/**
 * Revenue and profit over the last seven days, in the kit's chart panel: the
 * card, its header, and one component owning everything inside it — the shape
 * of `src/features/dashboard/components/overview.tsx` in
 * `satnaing/shadcn-admin`.
 *
 * The drawing is `RevenueChart`, the shadcn chart component on Recharts. This
 * file only orders the days the job recorded and labels them; ApexCharts, which
 * used to draw this, is gone from the portal entirely.
 */
export function RevenueAndProfitChart({ weeklyStats }: DailyStatsProps) {
  const days: RevenuePoint[] = [...(weeklyStats ?? [])]
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
    .map((stat) => ({
      day: new Date(stat.date).toLocaleDateString(undefined, {
        weekday: "short",
        day: "numeric",
      }),
      revenue: stat.totalRevenue,
      profit: stat.totalProfit,
    }));

  return (
    <Card className="col-span-12 xl:col-span-8">
      <CardHeader>
        <CardTitle>Revenue and profit</CardTitle>
        <CardDescription>The last seven days the job recorded.</CardDescription>
      </CardHeader>
      <CardContent>
        <RevenueChart data={days} />
      </CardContent>
    </Card>
  );
}
