import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "../components/ui/chart";
import { cn } from "../utils";

/**
 * Conversations a day, stacked by channel.
 *
 * The shape is the kit's `Overview`
 * (`src/features/dashboard/components/overview.tsx` in
 * `satnaing/shadcn-admin`): one component, handed the series, owning
 * everything inside the card. The drawing is the shadcn chart component on
 * Recharts, so the colours are `--chart-1..3` and follow the theme rather than
 * being written into the file.
 *
 * It imports nothing from Wasp: the page turns the runtime's answer into these
 * points, and this file only draws them.
 */

/** One day of the series, already labelled and already summed per channel. */
export type UsagePoint = {
  /** What the x axis shows, and what the tooltip is titled. */
  day: string;
  calls: number;
  texts: number;
  chats: number;
};

const USAGE_CONFIG = {
  calls: { label: "Calls", color: "var(--chart-1)" },
  texts: { label: "Texts", color: "var(--chart-2)" },
  chats: { label: "Chats", color: "var(--chart-3)" },
} satisfies ChartConfig;

export function UsageChart({
  data,
  className,
}: {
  data: UsagePoint[];
  className?: string;
}) {
  if (data.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-sm">
        No days recorded yet.
      </p>
    );
  }

  return (
    <ChartContainer
      config={USAGE_CONFIG}
      className={cn("aspect-auto h-[280px] w-full", className)}
    >
      <BarChart accessibilityLayer data={data} margin={{ left: 0, right: 8 }}>
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
          width={32}
          allowDecimals={false}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Bar
          dataKey="calls"
          stackId="conversations"
          fill="var(--color-calls)"
          radius={[0, 0, 4, 4]}
        />
        <Bar
          dataKey="texts"
          stackId="conversations"
          fill="var(--color-texts)"
          radius={[0, 0, 0, 0]}
        />
        <Bar
          dataKey="chats"
          stackId="conversations"
          fill="var(--color-chats)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ChartContainer>
  );
}
