import { IconArrowDown, IconArrowUp, IconCoin } from "@tabler/icons-react";
import { useMemo } from "react";
import { type DailyStatsProps } from "../../../analytics/stats";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../../client/components/ui/card";
import { cn } from "../../../client/utils";

/**
 * The kit's stat card (`src/features/dashboard/index.tsx` in
 * `satnaing/shadcn-admin`): the label and an icon in the header, the number
 * and the change under it.
 */
export function TotalRevenueCard({
  dailyStats,
  weeklyStats,
  isLoading,
}: DailyStatsProps) {
  const isDeltaPositive = useMemo(() => {
    if (!weeklyStats) return false;
    return weeklyStats[0].totalRevenue - weeklyStats[1]?.totalRevenue > 0;
  }, [weeklyStats]);

  const deltaPercentage = useMemo(() => {
    if (!weeklyStats || weeklyStats.length < 2 || isLoading) return;
    if (
      weeklyStats[1]?.totalRevenue === 0 ||
      weeklyStats[0]?.totalRevenue === 0
    )
      return 0;

    weeklyStats.sort((a, b) => b.id - a.id);

    const percentage =
      ((weeklyStats[0].totalRevenue - weeklyStats[1]?.totalRevenue) /
        weeklyStats[1]?.totalRevenue) *
      100;
    return Math.floor(percentage);
  }, [isLoading, weeklyStats]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">Total Revenue</CardTitle>
        <IconCoin className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">${dailyStats?.totalRevenue}</div>
        <p
          className={cn("flex items-center gap-1 text-xs", {
            "text-success": isDeltaPositive && !isLoading && deltaPercentage !== 0,
            "text-destructive":
              !isDeltaPositive && !isLoading && deltaPercentage !== 0,
            "text-muted-foreground":
              isLoading || !deltaPercentage || deltaPercentage === 0,
          })}
        >
          {isLoading
            ? "…"
            : deltaPercentage && deltaPercentage !== 0
              ? `${deltaPercentage}%`
              : "no change"}
          {!isLoading &&
            deltaPercentage &&
            deltaPercentage !== 0 &&
            (isDeltaPositive ? (
              <IconArrowUp className="size-3" />
            ) : (
              <IconArrowDown className="size-3" />
            ))}
          <span className="text-muted-foreground">from the week before</span>
        </p>
      </CardContent>
    </Card>
  );
}
