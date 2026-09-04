import {
  IconAlertTriangle,
  IconBolt,
  IconClipboardList,
  IconClock,
  IconCoin,
  IconMessage,
  IconMessageChatbot,
  IconPhone,
  type TablerIcon,
} from "@tabler/icons-react";
import { getTenantOverview, useQuery } from "wasp/client/operations";
import { UsageChart, type UsagePoint } from "./charts/usage-chart";
import { EmptyState } from "./components/empty-state";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import {
  formatCad,
  formatDateTime,
  formatMinutes,
  itemTypeLabel,
} from "./formatting";
import { OrgShell, Problem, type Org } from "./OrgShell";

/**
 * What the month has looked like, and what is late.
 *
 * The page is the kit's dashboard (`src/features/dashboard/index.tsx` in
 * `satnaing/shadcn-admin`): a row of stat cards, then the chart panel beside
 * the "recent" list. Every number here is the runtime's; the portal computes
 * nothing about a tenant except which slice of the runtime's answer to show.
 */
export function OverviewPage() {
  // The overview stays open without a subscription: an owner deciding whether
  // to pay has to be able to see what they would be paying for (portal plan,
  // Task C6). The banner still appears above it.
  return (
    <OrgShell
      title="Overview"
      description="What the front desk has done this month, and what is late."
      requiresSubscription={false}
    >
      {(org) => <Body org={org} />}
    </OrgShell>
  );
}

function Body({ org }: { org: Org }) {
  const { data, isLoading, error } = useQuery(getTenantOverview, {
    slug: org.slug,
  });

  if (isLoading) {
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  }
  if (error || !data) {
    return <Problem error={error ?? { message: "No overview to show." }} />;
  }

  const { totals } = data.month;
  const latest = data.latency[data.latency.length - 1];

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">
        This month so far, from {data.month.from} to {data.month.to}, for{" "}
        {data.tenantId}.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          id="calls"
          label="Calls"
          icon={IconPhone}
          value={String(totals.calls)}
          note="answered this month"
        />
        <Tile
          id="call-minutes"
          label="Call minutes"
          icon={IconClock}
          value={formatMinutes(totals.call_minutes)}
          note="on the phone this month"
        />
        <Tile
          id="texts"
          label="Texts"
          icon={IconMessage}
          value={String(totals.sms_in + totals.sms_out)}
          note="sent and received"
        />
        <Tile
          id="chats"
          label="Chats"
          icon={IconMessageChatbot}
          value={String(totals.chats)}
          note="web and social conversations"
        />
        <Tile
          id="open-items"
          label="Open requests"
          icon={IconClipboardList}
          value={String(data.health.open_items)}
          note="waiting on the team"
        />
        <Tile
          id="overdue-items"
          label="Overdue"
          icon={IconAlertTriangle}
          value={String(data.health.overdue_items)}
          note="past the promised time"
        />
        <Tile
          id="p95-latency"
          label="Reply time (p95)"
          icon={IconBolt}
          value={latest ? `${latest.p95_ms} ms` : "—"}
          note="nineteen replies in twenty are faster"
        />
        <Tile
          id="est-cost"
          label="Estimated cost"
          icon={IconCoin}
          value={formatCad(totals.est_cost_cad)}
          note="what the providers charged us"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-7">
        <Card className="col-span-1 lg:col-span-4">
          <CardHeader>
            <CardTitle>
              Last <span data-testid="usage-chart-days">{data.days.length}</span>{" "}
              days
            </CardTitle>
            <CardDescription>
              Conversations a day, in the clinic's own timezone.
            </CardDescription>
          </CardHeader>
          <CardContent data-testid="usage-chart" className="ps-2">
            <UsageOverview days={data.days} />
          </CardContent>
        </Card>

        <Card className="col-span-1 lg:col-span-3">
          <CardHeader>
            <CardTitle>Needs attention</CardTitle>
            <CardDescription>
              Requests past the time the assistant promised.
            </CardDescription>
          </CardHeader>
          <CardContent data-testid="needs-attention">
            {data.overdue.length === 0 ? (
              <EmptyState
                title="Nothing is past its promised time"
                description="Requests appear here the moment they run late."
                icon={IconClipboardList}
                className="border-0 py-6"
              />
            ) : (
              <ul className="space-y-6">
                {data.overdue.map((item) => (
                  <li key={item.id} className="flex items-center gap-4">
                    <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-full">
                      <IconAlertTriangle className="size-4" />
                    </span>
                    <div className="flex flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1">
                      <div className="space-y-1">
                        <p className="text-sm leading-none font-medium">
                          #{item.id} · {itemTypeLabel(item.type)}
                        </p>
                        <p className="text-muted-foreground text-sm">
                          {item.contact_name ??
                            item.contact_phone ??
                            "no contact"}{" "}
                          · due {formatDateTime(item.due_at)}
                        </p>
                      </div>
                      <div className="text-sm font-medium">Overdue</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/** One day of the runtime's usage series. */
type UsageDay = {
  date: string;
  calls: number;
  sms_in: number;
  sms_out: number;
  chats: number;
};

/**
 * The chart panel's body, in the shape of the kit's `Overview`
 * (`src/features/dashboard/components/overview.tsx`): one component, given the
 * series, owning everything inside the card.
 *
 * The drawing itself is `UsageChart`, the shadcn chart component on Recharts.
 * All this does is turn the runtime's day into a point: the two SMS directions
 * are one "texts" bar, because a text in and a text out are both the front desk
 * having a conversation, and the date becomes the label the axis shows.
 */
function UsageOverview({ days }: { days: UsageDay[] }) {
  const points: UsagePoint[] = days.map((day) => ({
    day: dayLabel(day.date),
    calls: day.calls,
    texts: day.sms_in + day.sms_out,
    chats: day.chats,
  }));

  return <UsageChart data={points} />;
}

/**
 * `2026-09-03` as `Sep 3`. Parsed at local midnight rather than through
 * `new Date("2026-09-03")`, which is UTC midnight and reads as the day before
 * anywhere west of Greenwich — including this clinic.
 */
function dayLabel(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return date;
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function Tile({
  id,
  label,
  value,
  note,
  icon: Icon,
}: {
  id: string;
  label: string;
  value: string;
  note: string;
  icon: TablerIcon;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div data-testid={`tile-${id}`} className="text-2xl font-bold">
          {value}
        </div>
        <p className="text-muted-foreground text-xs">{note}</p>
      </CardContent>
    </Card>
  );
}
