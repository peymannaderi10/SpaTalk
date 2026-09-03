import { IconArrowUp, IconUsersGroup } from "@tabler/icons-react";
import { useMemo } from "react";
import { type DailyStatsProps } from "../../../analytics/stats";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../../client/components/ui/card";
import { cn } from "../../../client/utils";

/** The kit's stat card, counting people with an account. */
export function TotalSignupsCard({ dailyStats, isLoading }: DailyStatsProps) {
  const isDeltaPositive = useMemo(() => {
    return !!dailyStats?.userDelta && dailyStats.userDelta > 0;
  }, [dailyStats]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">Total Signups</CardTitle>
        <IconUsersGroup className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{dailyStats?.userCount}</div>
        <p
          className={cn("flex items-center gap-1 text-xs", {
            "text-success": isDeltaPositive && !isLoading,
            "text-destructive":
              !isDeltaPositive && !isLoading && dailyStats?.userDelta !== 0,
            "text-muted-foreground": isLoading || !dailyStats?.userDelta,
          })}
        >
          {isLoading ? "…" : (dailyStats?.userDelta ?? "no change")}
          {!isLoading && (dailyStats?.userDelta ?? 0) > 0 && (
            <IconArrowUp className="size-3" />
          )}
          <span className="text-muted-foreground">since yesterday</span>
        </p>
      </CardContent>
    </Card>
  );
}
