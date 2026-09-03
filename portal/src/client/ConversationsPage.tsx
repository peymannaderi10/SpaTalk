import { useState } from "react";
import {
  blockSmsNumber,
  getTenantConversations,
  readConversation,
  useQuery,
} from "wasp/client/operations";
import { Button } from "./components/ui/button";
import {
  bandLabel,
  channelLabel,
  formatDateTime,
  formatDuration,
} from "./formatting";
import { OrgShell, Problem, type Org } from "./OrgShell";

type Detail = Awaited<ReturnType<typeof readConversation>>;

/**
 * Every conversation the assistant has had, and — one audited click away — what
 * was said. The list never shows a whole phone number; the runtime masks it to
 * the last four digits before it leaves the data plane.
 */
export function ConversationsPage() {
  return (
    <OrgShell title="Conversations">{(org) => <Body org={org} />}</OrgShell>
  );
}

const CHANNELS = ["voice", "sms", "chat", "instagram", "messenger"];

function Body({ org }: { org: Org }) {
  const [channel, setChannel] = useState("");
  const [band, setBand] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery(getTenantConversations, {
    slug: org.slug,
    channel: channel || undefined,
    band: band ? Number(band) : undefined,
    page,
  });

  const [detail, setDetail] = useState<Detail | null>(null);
  const [reading, setReading] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ message?: string } | null>(null);

  async function open(conversationId: string) {
    setProblem(null);
    setReading(conversationId);
    try {
      // Reading a transcript is an audited act: the runtime writes the row,
      // naming the person whose session this is.
      setDetail(await readConversation({ slug: org.slug, conversationId }));
    } catch (caught) {
      setProblem(caught as { message?: string });
    } finally {
      setReading(null);
    }
  }

  // A texting number can be blocked from its own transcript (plan F). The
  // runtime refuses staff numbers and writes the audit row.
  const blockCaller =
    detail && detail.conversation.channel === "sms" && detail.conversation.caller
      ? async () => {
          await blockSmsNumber({
            slug: org.slug,
            phone: detail.conversation.caller as string,
          });
        }
      : undefined;

  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  return (
    <>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Channel</span>
          <select
            aria-label="Channel"
            className="border-border bg-background text-foreground rounded-md border px-2 py-1 text-sm"
            value={channel}
            onChange={(event) => {
              setChannel(event.target.value);
              setPage(1);
            }}
          >
            <option value="">Every channel</option>
            {CHANNELS.map((option) => (
              <option key={option} value={option}>
                {channelLabel(option)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Outcome</span>
          <select
            aria-label="Band"
            className="border-border bg-background text-foreground rounded-md border px-2 py-1 text-sm"
            value={band}
            onChange={(event) => {
              setBand(event.target.value);
              setPage(1);
            }}
          >
            <option value="">Every outcome</option>
            <option value="1">Handled end to end</option>
            <option value="2">Sent to the team</option>
            <option value="3">Straight to a person</option>
          </select>
        </label>
      </div>

      <Problem error={error ?? problem} />

      {isLoading ? (
        <p className="text-muted-foreground mt-6 text-sm">Loading…</p>
      ) : (
        <table className="mt-6 w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-2 font-normal">Started</th>
              <th className="py-2 font-normal">Channel</th>
              <th className="py-2 font-normal">Caller</th>
              <th className="py-2 font-normal">Length</th>
              <th className="py-2 font-normal">Outcome</th>
              <th className="py-2 font-normal">Requests</th>
              <th className="py-2 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((row) => (
              <tr
                key={row.id}
                data-testid="conversation-row"
                className="border-border hover:bg-muted/40 cursor-pointer border-t"
                onClick={() => open(row.id)}
              >
                <td className="py-2">{formatDateTime(row.started_at)}</td>
                <td className="py-2">{channelLabel(row.channel)}</td>
                <td className="py-2">{row.caller_masked ?? "—"}</td>
                <td className="py-2">{formatDuration(row.duration_s)}</td>
                <td className="py-2">
                  <span>{bandLabel(row.band)}</span>
                  {row.health_context && (
                    <span
                      data-testid="health-badge"
                      className="border-border text-foreground ml-2 rounded-full border px-2 py-0.5 text-xs"
                    >
                      health context
                    </span>
                  )}
                </td>
                <td className="py-2">{row.item_count}</td>
                <td className="py-2 text-right">
                  {reading === row.id ? "Opening…" : "Open"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data && data.total === 0 && (
        <p className="text-muted-foreground mt-6 text-sm">
          Nothing on this channel yet.
        </p>
      )}

      {pages > 1 && (
        <div className="mt-6 flex items-center gap-3 text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((current) => current - 1)}
          >
            Previous
          </Button>
          <span className="text-muted-foreground">
            Page {page} of {pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage((current) => current + 1)}
          >
            Next
          </Button>
        </div>
      )}

      {detail && (
        <Transcript detail={detail} onBlock={blockCaller} onClose={() => setDetail(null)} />
      )}
    </>
  );
}

function Transcript({
  detail,
  onClose,
  onBlock,
}: {
  detail: Detail;
  onClose: () => void;
  onBlock?: () => Promise<void>;
}) {
  const { conversation, messages, items } = detail;
  const [blocked, setBlocked] = useState(false);
  const [blockProblem, setBlockProblem] = useState<string | null>(null);
  return (
    <div
      data-testid="transcript-drawer"
      className="border-border bg-background fixed inset-y-0 right-0 z-50 w-full max-w-xl overflow-y-auto border-l p-6 shadow-lg"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-foreground text-lg font-medium">
            {channelLabel(conversation.channel)} ·{" "}
            {bandLabel(conversation.band)}
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

      {onBlock && (
        <div className="mt-4 text-sm">
          {blocked ? (
            <p data-testid="blocked-note" className="text-muted-foreground">
              Blocked. Its texts are kept here and never answered. Undo it under
              Settings, Numbers.
            </p>
          ) : (
            <Button
              variant="outline"
              size="sm"
              data-testid="block-number"
              onClick={async () => {
                setBlockProblem(null);
                try {
                  await onBlock();
                  setBlocked(true);
                } catch (caught) {
                  setBlockProblem(
                    (caught as { message?: string }).message ??
                      "That number could not be blocked.",
                  );
                }
              }}
            >
              Block this number
            </Button>
          )}
          {blockProblem && <p className="text-destructive mt-2">{blockProblem}</p>}
        </div>
      )}

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

      {items.length > 0 && (
        <section className="mt-8">
          <h3 className="text-foreground text-sm font-medium">
            Requests from this conversation
          </h3>
          <ul className="text-muted-foreground mt-2 space-y-1 text-sm">
            {items.map((item) => (
              <li key={item.id}>
                #{item.id} · {item.type} · {item.state}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
