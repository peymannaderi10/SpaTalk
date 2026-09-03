import {
  IconAlertTriangle,
  IconChecks,
  IconClipboardList,
  IconHeartRateMonitor,
  IconSortAscendingLetters,
  IconSortDescendingLetters,
  IconMessage2,
  IconUrgent,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  acknowledgeItem,
  getTenantRequests,
  getTenantSettings,
  readConversation,
  resolveItem,
  useQuery,
} from "wasp/client/operations";
import { CallNotes } from "./CallNotes";
import { EmptyState } from "./components/empty-state";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import { Input } from "./components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./components/ui/select";
import { Separator } from "./components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import { channelLabel, isOverdue, notesLabel } from "./formatting";
import { OrgShell, Problem, type Org } from "./OrgShell";
import {
  matchesRequest,
  requestFacts,
  requestSummary,
  REQUEST_SORTS,
  sortRequests,
  type RequestSort,
} from "./requests";
import { TranscriptSheet, type TranscriptDetail } from "./TranscriptSheet";

type Requests = Awaited<ReturnType<typeof getTenantRequests>>;
type Item = Requests["open"][number];

/**
 * The ledger, from the client's side: what the assistant promised someone a
 * person would do. Acknowledging or resolving here is the same act as pressing
 * the Slack button — it goes through the runtime, which records who did it.
 *
 * A request is read as a card, not a row, so the page is the kit's app grid
 * (`src/features/apps/index.tsx` in `satnaing/shadcn-admin`): its toolbar of a
 * search box, a switch and a sort, a separator, and a scrolling grid of cards.
 *
 * A card leads with the runtime's own one-line summary of the request (lead
 * context plan, Task L2). That sentence is composed once, in the runtime, from
 * the item's closed fields, so the card, the owner's text and the digest all
 * say the same thing. Everything under it is that sentence broken into words a
 * person can act on: never a service id, never "any any", and no line at all
 * for something the caller was never asked (`requests.ts`).
 *
 * Under those facts, when the runtime drafted them, are the notes it took from
 * the transcript (call notes plan, Task N2) — under the tenant's own label, so
 * nobody mistakes a draft for something the caller signed off.
 */
export function RequestsPage() {
  return (
    <OrgShell
      title="Requests"
      description="What the assistant promised someone a person would do."
      fixed
    >
      {(org) => <Body org={org} />}
    </OrgShell>
  );
}

function Body({ org }: { org: Org }) {
  const [tab, setTab] = useState<"open" | "resolved">("open");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<RequestSort>("newest");
  // `?item=` is how the command palette hands this page a request someone
  // picked out of it. All it does is put the card in front of them: the tab it
  // is filed under, and the page scrolled to it. Reading the transcript stays a
  // click, because reading one is an audited act nobody has asked for yet.
  const [searchParams] = useSearchParams();
  const wanted = Number(searchParams.get("item")) || null;
  const shown = useRef<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [problem, setProblem] = useState<{ message?: string } | null>(null);
  const [detail, setDetail] = useState<TranscriptDetail | null>(null);
  const [reading, setReading] = useState<number | null>(null);

  const { data, isLoading, error, refetch } = useQuery(getTenantRequests, {
    slug: org.slug,
  });

  // The label over the notes is the tenant's wording, from `scripts.notes_label`
  // in its configuration — the same query the settings page reads, so it is one
  // request for the page and none per card. Its failure is never shown: the
  // requests are what this page is for, and `notesLabel` has the runtime's own
  // default to fall back on.
  const { data: settings } = useQuery(getTenantSettings, { slug: org.slug });
  const label = notesLabel(settings?.config);

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

  useEffect(() => {
    if (!wanted || !data || shown.current === wanted) {
      return;
    }
    shown.current = wanted;
    setTab(data.resolved.some((item) => item.id === wanted) ? "resolved" : "open");
    requestAnimationFrame(() => {
      document
        .getElementById(`request-${wanted}`)
        ?.scrollIntoView({ block: "center" });
    });
  }, [wanted, data]);

  const filed = data ? (tab === "open" ? data.open : data.resolved) : [];
  const rows = sortRequests(
    filed.filter((item) => matchesRequest(item, search)),
    sort,
  );

  return (
    <>
      <div className="my-4 flex flex-col gap-4 sm:my-0 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-4 sm:my-4 sm:flex-row sm:items-center">
          <Input
            placeholder="Filter requests…"
            className="h-9 w-full sm:w-40 lg:w-62.5"
            data-testid="requests-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Tabs
            value={tab}
            onValueChange={(next) => setTab(next as "open" | "resolved")}
          >
            <TabsList>
              <TabsTrigger value="open" data-testid="requests-tab-open">
                Open
              </TabsTrigger>
              <TabsTrigger value="resolved" data-testid="requests-tab-resolved">
                Resolved
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <Select
          value={sort}
          onValueChange={(next) => setSort(next as RequestSort)}
        >
          <SelectTrigger className="w-44" data-testid="requests-sort">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            {REQUEST_SORTS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                <div className="flex items-center gap-2">
                  {option.value === "oldest" ? (
                    <IconSortAscendingLetters className="size-4" />
                  ) : (
                    <IconSortDescendingLetters className="size-4" />
                  )}
                  <span>{option.label}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Separator className="shadow-sm" />

      <Problem error={error ?? problem} />

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title={
            search.trim() !== ""
              ? "No request matches that"
              : tab === "open"
                ? "Nothing is waiting on the team"
                : "Nothing has been resolved yet"
          }
          description={
            search.trim() !== ""
              ? "Clear the filter to see everything filed here."
              : tab === "open"
                ? "A request appears here the moment the assistant promises someone a person will follow up."
                : "A request moves here when someone marks it done."
          }
          icon={IconClipboardList}
          testId="requests-empty"
        />
      ) : (
        <ul className="faded-bottom no-scrollbar grid gap-4 overflow-auto pt-4 pb-16 lg:grid-cols-2 2xl:grid-cols-3">
          {rows.map((item) => (
            <li key={item.id}>
              <RequestCard
                item={item}
                label={label}
                tab={tab}
                busy={busy === item.id}
                reading={reading === item.id}
                onAcknowledge={() => act(item.id, acknowledgeItem)}
                onResolve={() => act(item.id, resolveItem)}
                onTranscript={() => openTranscript(item)}
              />
            </li>
          ))}
        </ul>
      )}

      <TranscriptSheet
        detail={detail}
        label={label}
        testId="request-transcript"
        onClose={() => setDetail(null)}
      />
    </>
  );
}

function RequestCard({
  item,
  label,
  tab,
  busy,
  reading,
  onAcknowledge,
  onResolve,
  onTranscript,
}: {
  item: Item;
  label: string;
  tab: "open" | "resolved";
  busy: boolean;
  reading: boolean;
  onAcknowledge: () => void;
  onResolve: () => void;
  onTranscript: () => void;
}) {
  const facts = requestFacts(item);

  return (
    <Card
      id={`request-${item.id}`}
      data-testid="request-row"
      className="h-full gap-4 transition-shadow hover:shadow-md"
    >
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="font-mono">
            #{item.id}
          </Badge>
          <Badge variant="outline" className="font-normal">
            {channelLabel(item.channel)}
          </Badge>
          {item.urgency === "urgent" && (
            <Badge variant="outline" className="gap-1 font-normal">
              <IconUrgent className="size-3" />
              urgent
            </Badge>
          )}
          {item.health_context && (
            <Badge
              variant="outline"
              data-testid="health-badge"
              className="gap-1 font-normal"
            >
              <IconHeartRateMonitor className="size-3" />
              health context
            </Badge>
          )}
          {isOverdue(item) && (
            <Badge variant="destructive" className="gap-1 font-normal">
              <IconAlertTriangle className="size-3" />
              Overdue
            </Badge>
          )}
        </div>
        <CardTitle data-testid="request-summary" className="text-base">
          {requestSummary(item)}
        </CardTitle>
      </CardHeader>

      <CardContent className="flex-1">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          {facts.map((fact) => (
            <div key={fact.label}>
              <dt className="text-muted-foreground text-xs uppercase">
                {fact.label}
              </dt>
              <dd className="text-foreground">{fact.value}</dd>
            </div>
          ))}
        </dl>

        <CallNotes notes={item.notes} label={label} testId="request-notes" />
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2">
        {tab === "open" && item.state === "open" && (
          <Button
            size="sm"
            variant="outline"
            data-testid={`acknowledge-${item.id}`}
            disabled={busy}
            onClick={onAcknowledge}
          >
            <IconChecks className="size-4" />
            Acknowledge
          </Button>
        )}
        {tab === "open" && (
          <Button
            size="sm"
            data-testid={`resolve-${item.id}`}
            disabled={busy}
            onClick={onResolve}
          >
            Resolve
          </Button>
        )}
        {item.conversation_id && (
          <Button
            size="sm"
            variant="outline"
            data-testid={`transcript-${item.id}`}
            disabled={reading}
            onClick={onTranscript}
          >
            <IconMessage2 className="size-4" />
            {reading ? "Opening…" : "Transcript"}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
