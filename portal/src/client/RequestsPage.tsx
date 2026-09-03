import { useState, type ReactNode } from "react";
import {
  acknowledgeItem,
  getTenantRequests,
  readConversation,
  resolveItem,
  useQuery,
} from "wasp/client/operations";
import { Button } from "./components/ui/button";
import {
  channelLabel,
  clientLabel,
  formatDateTime,
  isOverdue,
  itemTypeLabel,
  practitionerLabel,
} from "./formatting";
import { OrgShell, Problem, type Org } from "./OrgShell";

type Requests = Awaited<ReturnType<typeof getTenantRequests>>;
type Item = Requests["open"][number];
type Detail = Awaited<ReturnType<typeof readConversation>>;

/**
 * The ledger, from the client's side: what the assistant promised someone a
 * person would do. Acknowledging or resolving here is the same act as pressing
 * the Slack button — it goes through the runtime, which records who did it.
 *
 * A card leads with the runtime's own one-line summary of the request (lead
 * context plan, Task L2). That sentence is composed once, in the runtime, from
 * the item's closed fields, so the card, the owner's text and the digest all
 * say the same thing. Everything under it is that sentence broken into words a
 * person can act on: never a service id, never "any any", and no line at all
 * for something the caller was never asked.
 */
export function RequestsPage() {
  return <OrgShell title="Requests">{(org) => <Body org={org} />}</OrgShell>;
}

function Body({ org }: { org: Org }) {
  const [tab, setTab] = useState<"open" | "resolved">("open");
  const [busy, setBusy] = useState<number | null>(null);
  const [problem, setProblem] = useState<{ message?: string } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [reading, setReading] = useState<number | null>(null);

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

  /**
   * Reading what was actually said is where a follow-up starts. It is an
   * audited act: the runtime writes the row naming this person, which is why
   * the card carries a button and not a cached link.
   */
  async function openTranscript(item: Item) {
    setProblem(null);
    setReading(item.id);
    try {
      setDetail(
        await readConversation({
          slug: org.slug,
          conversationId: item.conversation_id as string,
        }),
      );
    } catch (caught) {
      setProblem(caught as { message?: string });
    } finally {
      setReading(null);
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
                <span
                  data-testid="request-summary"
                  className="text-foreground font-medium"
                >
                  {summaryOf(item)}
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
                {contactText(item) && (
                  <Fact label="Contact">{contactText(item)}</Fact>
                )}
                {item.service_name && (
                  <Fact label="Service">{item.service_name}</Fact>
                )}
                {clientLabel(item.returning_client) && (
                  <Fact label="Client">{clientLabel(item.returning_client)}</Fact>
                )}
                {practitionerLabel(item.practitioner) && (
                  <Fact label="Practitioner">
                    {practitionerLabel(item.practitioner)}
                  </Fact>
                )}
                {item.concern && <Fact label="Concern">{item.concern}</Fact>}
                {askedForATime(item) && (
                  <Fact label="Preferred">{item.preferred_text}</Fact>
                )}
                <Fact label="Promised by">{formatDateTime(item.due_at)}</Fact>
                <Fact label="State">{stateLabel(item)}</Fact>
              </dl>

              <div className="mt-3 flex flex-wrap gap-2">
                {tab === "open" && item.state === "open" && (
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
                {tab === "open" && (
                  <Button
                    size="sm"
                    data-testid={`resolve-${item.id}`}
                    disabled={busy === item.id}
                    onClick={() => act(item.id, resolveItem)}
                  >
                    Resolve
                  </Button>
                )}
                {item.conversation_id && (
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`transcript-${item.id}`}
                    disabled={reading === item.id}
                    onClick={() => openTranscript(item)}
                  >
                    {reading === item.id ? "Opening…" : "Transcript"}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {detail && (
        <Transcript detail={detail} onClose={() => setDetail(null)} />
      )}
    </>
  );
}

/**
 * The runtime composes the sentence; the card only shows it. The fallback is
 * for a row read from a runtime that predates the summary — it names the type
 * rather than leaving the card headless, and claims nothing beyond it.
 */
function summaryOf(item: Item): string {
  return item.summary || itemTypeLabel(item.type);
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

function contactText(item: Item): string {
  return [item.contact_name, item.contact_phone, item.contact_email]
    .filter(Boolean)
    .join(" · ");
}

/**
 * `preferred_text` always reads as something — an item nobody was asked about
 * says "any day" — so the line is shown only when the caller actually named a
 * day or a time of day. The summary sentence says the rest.
 */
function askedForATime(item: Item): boolean {
  const window = (item.preferred_window ?? {}) as {
    date?: string;
    part_of_day?: string;
  };
  return [window.date, window.part_of_day].some(
    (value) => typeof value === "string" && value !== "" && value !== "any",
  );
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

/** What was said, opened from the request it produced. */
function Transcript({
  detail,
  onClose,
}: {
  detail: Detail;
  onClose: () => void;
}) {
  const { conversation, messages } = detail;
  return (
    <div
      data-testid="request-transcript"
      className="border-border bg-background fixed inset-y-0 right-0 z-50 w-full max-w-xl overflow-y-auto border-l p-6 shadow-lg"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-foreground text-lg font-medium">
            {channelLabel(conversation.channel)}
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">
            {conversation.caller ?? conversation.external_ref ?? "no caller id"}{" "}
            · {formatDateTime(conversation.started_at)}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      {conversation.health_context && (
        <p className="border-border mt-4 rounded-md border p-3 text-sm">
          The caller volunteered health information. It is in the transcript and
          nowhere else.
        </p>
      )}

      <ol className="mt-6 space-y-3">
        {messages.map((message, index) => (
          <li key={index} className="text-sm">
            <span className="text-muted-foreground text-xs uppercase">
              {message.role}
            </span>
            <p className="text-foreground mt-1">{message.text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
