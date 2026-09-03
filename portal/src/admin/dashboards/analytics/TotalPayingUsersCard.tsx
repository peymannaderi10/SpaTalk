import { IconArrowDown, IconArrowUp, IconBuildingStore } from "@tabler/icons-react";
import { useMemo } from "react";
import { type DailyStatsProps } from "../../../analytics/stats";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../../client/components/ui/card";
import { cn } from "../../../client/utils";

/** The kit's stat card; the number is clinics, not people. */
export function TotalPayingUsersCard({
  dailyStats,
  isLoading,
}: DailyStatsProps) {
  const isDeltaPositive = useMemo(() => {
    return !!dailyStats?.paidUserDelta && dailyStats?.paidUserDelta > 0;
  }, [dailyStats]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">
          Total Paying Users
        </CardTitle>
        <IconBuildingStore className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{dailyStats?.paidUserCount}</div>
        <p
          className={cn("flex items-center gap-1 text-xs", {
            "text-success": isDeltaPositive && !isLoading,
            "text-destructive":
              !isDeltaPositive && !isLoading && dailyStats?.paidUserDelta !== 0,
            "text-muted-foreground": isLoading || !dailyStats?.paidUserDelta,
          })}
        >
          {isLoading ? "…" : (dailyStats?.paidUserDelta ?? "no change")}
          {!isLoading &&
            (dailyStats?.paidUserDelta ?? 0) !== 0 &&
            (isDeltaPositive ? (
              <IconArrowUp className="size-3" />
            ) : (
              <IconArrowDown className="size-3" />
            ))}
          <span className="text-muted-foreground">since yesterday</span>
        </p>
      </CardContent>
    </Card>
  );
}
