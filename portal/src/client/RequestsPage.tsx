import { useState, type ReactNode } from "react";
import {
  acknowledgeItem,
  getTenantRequests,
  resolveItem,
  useQuery,
} from "wasp/client/operations";
import { Button } from "./components/ui/button";
import {
  channelLabel,
  formatDateTime,
  isOverdue,
  itemTypeLabel,
} from "./formatting";
import { OrgShell, Problem, type Org } from "./OrgShell";

type Requests = Awaited<ReturnType<typeof getTenantRequests>>;
type Item = Requests["open"][number];

/**
 * The ledger, from the client's side: what the assistant promised someone a
 * person would do. Acknowledging or resolving here is the same act as pressing
 * the Slack button — it goes through the runtime, which records who did it.
 */
export function RequestsPage() {
  return <OrgShell title="Requests">{(org) => <Body org={org} />}</OrgShell>;
}

function Body({ org }: { org: Org }) {
  const [tab, setTab] = useState<"open" | "resolved">("open");
  const [busy, setBusy] = useState<number | null>(null);
  const [problem, setProblem] = useState<{ message?: string } | null>(null);

  const { data, isLoading, error, refetch } = useQuery(getTenantRequests, {
    slug: org.slug,
  });

  async function act(
    itemId: number,
    what: typeof acknowledgeItem | typeof resolveItem,
  ) {
    setProblem(null);
    setBusy(itemId);
    try {
      await what({ slug: org.slug, itemId });
      await refetch();
    } catch (caught) {
      setProblem(caught as { message?: string });
    } finally {
      setBusy(null);
    }
  }

  const rows = data ? (tab === "open" ? data.open : data.resolved) : [];

  return (
    <>
      <div className="flex gap-2">
        <Button
          variant={tab === "open" ? "default" : "outline"}
          size="sm"
          onClick={() => setTab("open")}
        >
          Open
        </Button>
        <Button
          variant={tab === "resolved" ? "default" : "outline"}
          size="sm"
          onClick={() => setTab("resolved")}
        >
          Resolved
        </Button>
      </div>

      <Problem error={error ?? problem} />

      {isLoading ? (
        <p className="text-muted-foreground mt-6 text-sm">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground mt-6 text-sm">
          {tab === "open"
            ? "Nothing is waiting on the team."
            : "Nothing has been resolved yet."}
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {rows.map((item) => (
            <li
              key={item.id}
              data-testid="request-row"
              className="border-border rounded-lg border p-4 text-sm"
            >
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="text-foreground font-medium">#{item.id}</span>
                <span className="text-foreground">
                  {itemTypeLabel(item.type)}
                </span>
                <span className="text-muted-foreground">
                  {channelLabel(item.channel)}
                </span>
                {item.urgency === "urgent" && (
                  <span className="border-border rounded-full border px-2 py-0.5 text-xs">
                    urgent
                  </span>
                )}
                {item.health_context && (
                  <span
                    data-testid="health-badge"
                    className="border-border rounded-full border px-2 py-0.5 text-xs"
                  >
                    health context
                  </span>
                )}
                {isOverdue(item) && (
                  <span className="text-foreground font-medium">Overdue</span>
                )}
              </div>

              <dl className="text-muted-foreground mt-2 grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-3">
                <Fact label="Contact">
                  {item.contact_name ?? "—"}
                  {item.contact_phone ? ` · ${item.contact_phone}` : ""}
                  {item.contact_email ? ` · ${item.contact_email}` : ""}
                </Fact>
                <Fact label="Promised by">{formatDateTime(item.due_at)}</Fact>
                <Fact label="State">{stateLabel(item)}</Fact>
                {item.service_id && (
                  <Fact label="Service">{item.service_id}</Fact>
                )}
                {preferredWindow(item) && (
                  <Fact label="Preferred">{preferredWindow(item)}</Fact>
                )}
              </dl>

              {tab === "open" && (
                <div className="mt-3 flex gap-2">
                  {item.state === "open" && (
                    <Button
                      size="sm"
                      variant="outline"
                      data-testid={`acknowledge-${item.id}`}
                      disabled={busy === item.id}
                      onClick={() => act(item.id, acknowledgeItem)}
                    >
                      Acknowledge
                    </Button>
                  )}
                  <Button
                    size="sm"
                    data-testid={`resolve-${item.id}`}
                    disabled={busy === item.id}
                    onClick={() => act(item.id, resolveItem)}
                  >
                    Resolve
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function stateLabel(item: Item): string {
  if (item.state === "acknowledged") {
    return `acknowledged by ${item.acknowledged_by ?? "someone"}`;
  }
  if (item.state === "resolved") {
    return `resolved by ${item.resolved_by ?? "someone"}`;
  }
  return item.state;
}

function preferredWindow(item: Item): string {
  const window = (item.preferred_window ?? {}) as {
    date?: string;
    part_of_day?: string;
  };
  return [window.date, window.part_of_day].filter(Boolean).join(" ");
}

function Fact({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs uppercase">{label}</dt>
      <dd className="text-foreground">{children}</dd>
    </div>
  );
}
