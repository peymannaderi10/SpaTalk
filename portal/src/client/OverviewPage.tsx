import { type ApexOptions } from "apexcharts";
import { useMemo } from "react";
import ReactApexChart from "react-apexcharts";
import { getTenantOverview, useQuery } from "wasp/client/operations";
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
 * Every number here is the runtime's; the portal computes nothing about a
 * tenant except which slice of the runtime's answer to show.
 */
export function OverviewPage() {
  // The overview stays open without a subscription: an owner deciding whether
  // to pay has to be able to see what they would be paying for (portal plan,
  // Task C6). The banner still appears above it.
  return (
    <OrgShell title="Overview" requiresSubscription={false}>
      {(org) => <Body org={org} />}
    </OrgShell>
  );
}

function Body({ org }: { org: Org }) {
  const { data, isLoading, error } = useQuery(getTenantOverview, {
    slug: org.slug,
  });

  const chart = useMemo(() => {
    const days = data?.days ?? [];
    return {
      options: chartOptions(days.map((day) => day.date)),
      series: [
        { name: "Calls", data: days.map((day) => day.calls) },
        {
          name: "Texts",
          data: days.map((day) => day.sms_in + day.sms_out),
        },
        { name: "Chats", data: days.map((day) => day.chats) },
      ],
    };
  }, [data?.days]);

  if (isLoading) {
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  }
  if (error || !data) {
    return <Problem error={error ?? { message: "No overview to show." }} />;
  }

  const { totals } = data.month;
  const latest = data.latency[data.latency.length - 1];

  return (
    <>
      <p className="text-muted-foreground text-sm">
        This month so far, from {data.month.from} to {data.month.to}, for{" "}
        {data.tenantId}.
      </p>

      <dl className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Tile id="calls" label="Calls" value={String(totals.calls)} />
        <Tile
          id="call-minutes"
          label="Call minutes"
          value={formatMinutes(totals.call_minutes)}
        />
        <Tile
          id="texts"
          label="Texts"
          value={String(totals.sms_in + totals.sms_out)}
        />
        <Tile id="chats" label="Chats" value={String(totals.chats)} />
        <Tile
          id="open-items"
          label="Open requests"
          value={String(data.health.open_items)}
        />
        <Tile
          id="overdue-items"
          label="Overdue"
          value={String(data.health.overdue_items)}
        />
        <Tile
          id="p95-latency"
          label="Reply time (p95)"
          value={latest ? `${latest.p95_ms} ms` : "—"}
        />
        <Tile
          id="est-cost"
          label="Estimated cost"
          value={formatCad(totals.est_cost_cad)}
        />
      </dl>

      <section className="mt-10">
        <h2 className="text-foreground text-lg font-medium">
          Last <span data-testid="usage-chart-days">{data.days.length}</span>{" "}
          days
        </h2>
        <div
          data-testid="usage-chart"
          className="border-border mt-3 rounded-lg border p-4"
        >
          <ReactApexChart
            options={chart.options}
            series={chart.series}
            type="bar"
            height={280}
          />
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-lg font-medium">Needs attention</h2>
        <div data-testid="needs-attention" className="mt-3">
          {data.overdue.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing is past its promised time.
            </p>
          ) : (
            <ul className="space-y-2">
              {data.overdue.map((item) => (
                <li
                  key={item.id}
                  className="border-border flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-md border p-3 text-sm"
                >
                  <span className="text-foreground font-medium">
                    #{item.id}
                  </span>
                  <span>{itemTypeLabel(item.type)}</span>
                  <span className="text-muted-foreground">
                    {item.contact_name ?? item.contact_phone ?? "no contact"}
                  </span>
                  <span className="text-muted-foreground">
                    due {formatDateTime(item.due_at)}
                  </span>
                  <span className="text-foreground font-medium">Overdue</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </>
  );
}

function Tile({
  id,
  label,
  value,
}: {
  id: string;
  label: string;
  value: string;
}) {
  return (
    <div className="border-border rounded-lg border p-4">
      <dt className="text-muted-foreground text-xs uppercase">{label}</dt>
      <dd
        data-testid={`tile-${id}`}
        className="text-foreground mt-1 text-2xl font-semibold"
      >
        {value}
      </dd>
    </div>
  );
}

function chartOptions(categories: string[]): ApexOptions {
  return {
    chart: {
      fontFamily: "system-ui, sans-serif",
      type: "bar",
      stacked: true,
      toolbar: { show: false },
      animations: { enabled: false },
    },
    colors: ["#3C50E0", "#80CAEE", "#0FADCF"],
    dataLabels: { enabled: false },
    legend: { position: "top", horizontalAlign: "left" },
    plotOptions: { bar: { columnWidth: "60%" } },
    xaxis: {
      categories,
      labels: { rotate: -60, hideOverlappingLabels: true },
      tickAmount: 10,
    },
    yaxis: { labels: { formatter: (value: number) => String(Math.round(value)) } },
  };
}
