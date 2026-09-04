import { useId } from "react";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "../components/ui/chart";
import { formatCad } from "../formatting";
import { cn } from "../utils";

/**
 * Revenue and profit over the days the daily-stats job recorded.
 *
 * The same shape as `UsageChart` and as the kit's `Overview`: the card and its
 * header belong to the page, everything inside belongs here. Two stacked areas
 * would double-count — profit is part of revenue — so the two are drawn on top
 * of each other, revenue behind profit, in `--chart-1` and `--chart-2`.
 *
 * It imports nothing from Wasp, so it can be rendered in a unit test.
 */

/** One recorded day, already labelled and already in dollars. */
export type RevenuePoint = {
  /** What the x axis shows, and what the tooltip is titled. */
  day: string;
  revenue: number;
  profit: number;
};

const REVENUE_CONFIG = {
  revenue: { label: "Revenue", color: "var(--chart-1)" },
  profit: { label: "Profit", color: "var(--chart-2)" },
} satisfies ChartConfig;

/** The configured label for a series, so the tooltip reads like the legend. */
function seriesLabel(name: string | number | undefined): string {
  const key = String(name ?? "");
  return key in REVENUE_CONFIG
    ? REVENUE_CONFIG[key as keyof typeof REVENUE_CONFIG].label
    : key;
}

export function RevenueChart({
  data,
  className,
}: {
  data: RevenuePoint[];
  className?: string;
}) {
  // The two gradients are referenced by id, and an id is global to the
  // document; React hands out one that is unique to this instance.
  const gradient = useId().replace(/:/g, "");
  const revenueFill = `revenue-fill-${gradient}`;
  const profitFill = `profit-fill-${gradient}`;

  if (data.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-sm">
        No day has been recorded yet.
      </p>
    );
  }

  return (
    <ChartContainer
      config={REVENUE_CONFIG}
      className={cn("aspect-auto h-[280px] w-full", className)}
    >
      <AreaChart accessibilityLayer data={data} margin={{ left: 0, right: 8 }}>
        <defs>
          <linearGradient id={revenueFill} x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="5%"
              stopColor="var(--color-revenue)"
              stopOpacity={0.8}
            />
            <stop
              offset="95%"
              stopColor="var(--color-revenue)"
              stopOpacity={0.1}
            />
          </linearGradient>
          <linearGradient id={profitFill} x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="5%"
              stopColor="var(--color-profit)"
              stopOpacity={0.8}
            />
            <stop
              offset="95%"
              stopColor="var(--color-profit)"
              stopOpacity={0.1}
            />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={8}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={72}
          tickFormatter={(value: number) => formatCad(value)}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              formatter={(value, name, item) => (
                <>
                  <div
                    className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: item?.color }}
                  />
                  <div className="flex flex-1 items-center justify-between gap-2 leading-none">
                    <span className="text-muted-foreground">
                      {seriesLabel(name)}
                    </span>
                    <span className="text-foreground font-mono font-medium tabular-nums">
                      {formatCad(Number(value))}
                    </span>
                  </div>
                </>
              )}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        <Area
          dataKey="revenue"
          type="monotone"
          fill={`url(#${revenueFill})`}
          stroke="var(--color-revenue)"
          strokeWidth={2}
        />
        <Area
          dataKey="profit"
          type="monotone"
          fill={`url(#${profitFill})`}
          stroke="var(--color-profit)"
          strokeWidth={2}
        />
      </AreaChart>
    </ChartContainer>
  );
}
