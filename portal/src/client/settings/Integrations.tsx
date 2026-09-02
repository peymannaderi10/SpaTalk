import { useState } from "react";
import {
  disconnectIntegration,
  getTenantIntegrations,
  selectMessengerPage,
  startIntegrationConnect,
  useQuery,
} from "wasp/client/operations";
import { formatDateTime } from "../formatting";
import { Button } from "../components/ui/button";

/**
 * Instagram and Facebook Page connections (instagram plan, Task D4).
 *
 * Everything on this tab is the runtime's: the portal keeps no record of a
 * connection and never calls Meta (CLAUDE.md non-negotiable 7). Connect asks
 * the runtime for an authorisation URL carrying a signed state — which is what
 * brings the browser back here afterwards — and Disconnect asks the runtime to
 * unsubscribe the app and delete the token. No token is ever sent to this page.
 */

type Integrations = Awaited<ReturnType<typeof getTenantIntegrations>>;
type Integration = Integrations["integrations"][number];

type Card = {
  provider: "instagram" | "messenger";
  name: string;
  /** What the tenant is connecting, in the words the owner would use. */
  what: string;
};

const CARDS: Card[] = [
  {
    provider: "instagram",
    name: "Instagram",
    what: "Direct messages and comments on the clinic's Instagram account.",
  },
  {
    provider: "messenger",
    name: "Facebook Page",
    what: "Messenger conversations and comments on the clinic's Facebook Page.",
  },
];

/** A Page choice the runtime parked while the owner picks (D3's connect flow). */
type PageChoice = { id: string; name: string };

function pendingPages(): { pending: string; pages: PageChoice[] } | null {
  const params = new URLSearchParams(window.location.search);
  const pending = params.get("messenger_pending");
  const raw = params.get("messenger_pages");
  if (!pending || !raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as PageChoice[];
    return Array.isArray(parsed) && parsed.length > 0
      ? { pending, pages: parsed }
      : null;
  } catch {
    return null;
  }
}

export function IntegrationsTab({
  slug,
  readOnly,
}: {
  slug: string;
  readOnly: boolean;
}) {
  const { data, isLoading, error, refetch } = useQuery(getTenantIntegrations, {
    slug,
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [choice, setChoice] = useState(() => pendingPages());

  if (isLoading || !data) {
    return (
      <p className="text-muted-foreground text-sm" data-testid="integrations-tab">
        {error ? (error as { message?: string }).message : "Loading…"}
      </p>
    );
  }

  const byProvider = new Map(
    data.integrations.map((row) => [row.provider, row]),
  );

  async function connect(provider: Card["provider"]) {
    setBusy(provider);
    setProblem(null);
    try {
      const { url } = await startIntegrationConnect({ slug, provider });
      // The signed state is good for fifteen minutes, so the browser leaves
      // for Meta now, on the click that minted it.
      window.location.assign(url);
    } catch (caught) {
      setProblem(
        (caught as { message?: string }).message ??
          "The connection could not be started.",
      );
      setBusy(null);
    }
  }

  async function disconnect(provider: Card["provider"]) {
    setBusy(provider);
    setProblem(null);
    try {
      await disconnectIntegration({ slug, provider });
      await refetch();
    } catch (caught) {
      setProblem(
        (caught as { message?: string }).message ??
          "The connection could not be removed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function choosePage(pageId: string) {
    if (!choice) {
      return;
    }
    setBusy("messenger");
    setProblem(null);
    try {
      await selectMessengerPage({ slug, pending: choice.pending, pageId });
      setChoice(null);
      await refetch();
    } catch (caught) {
      setProblem(
        (caught as { message?: string }).message ??
          "That Page could not be connected. Start the connection again.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div data-testid="integrations-tab" className="space-y-6">
      <p className="text-muted-foreground text-sm">
        The assistant answers Instagram and Facebook from the same knowledge
        base as calls and texts. What it says about comments — which ones it
        replies to, and whether it replies publicly — is on the Scripts and
        Delivery tabs.
      </p>

      {problem && (
        <p
          data-testid="integration-problem"
          className="border-border rounded-md border p-3 text-sm"
        >
          {problem}
        </p>
      )}

      {choice && (
        <div
          data-testid="messenger-page-choice"
          className="border-border rounded-lg border p-4 text-sm"
        >
          <p className="text-foreground font-medium">
            Which Page should the assistant answer?
          </p>
          <div className="mt-3 space-y-2">
            {choice.pages.map((page) => (
              <div
                key={page.id}
                className="flex items-center justify-between gap-4"
              >
                <span data-testid={`messenger-page-${page.id}`}>
                  {page.name}
                </span>
                <Button
                  type="button"
                  size="sm"
                  disabled={readOnly || busy !== null}
                  data-testid={`messenger-page-choose-${page.id}`}
                  onClick={() => choosePage(page.id)}
                >
                  Use this Page
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {CARDS.map((card) => (
        <IntegrationCard
          key={card.provider}
          card={card}
          status={byProvider.get(card.provider)}
          readOnly={readOnly}
          busy={busy === card.provider}
          onConnect={() => connect(card.provider)}
          onDisconnect={() => disconnect(card.provider)}
        />
      ))}
    </div>
  );
}

function IntegrationCard({
  card,
  status,
  readOnly,
  busy,
  onConnect,
  onDisconnect,
}: {
  card: Card;
  status: Integration | undefined;
  readOnly: boolean;
  busy: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const connected = status?.connected === true;
  const configured = status?.configured !== false;

  return (
    <section
      data-testid={`integration-${card.provider}`}
      className="border-border rounded-lg border p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-foreground text-sm font-medium">{card.name}</h3>
          <p className="text-muted-foreground mt-1 text-sm">{card.what}</p>
          <p
            data-testid={`integration-${card.provider}-status`}
            className="text-foreground mt-3 text-sm"
          >
            {connected
              ? `Connected as ${status?.display_name || status?.external_id}`
              : "Not connected"}
          </p>
          {connected && (
            <p className="text-muted-foreground mt-1 text-xs">
              {status?.token_expires_at
                ? `The connection is renewed automatically; it would expire ${formatDateTime(status.token_expires_at)}.`
                : "The connection is renewed automatically."}
              {status?.connected_by ? ` Connected by ${status.connected_by}.` : ""}
            </p>
          )}
          {connected && status?.needs_reconnect && (
            <p
              data-testid={`integration-${card.provider}-needs-reconnect`}
              className="text-foreground mt-2 text-sm font-medium"
            >
              This connection could not be renewed. Messages still arrive, but
              the assistant will stop being able to reply: connect it again.
            </p>
          )}
          {!configured && (
            <p
              data-testid={`integration-${card.provider}-unconfigured`}
              className="text-muted-foreground mt-2 text-xs"
            >
              {card.name} is not set up on this service yet. Ask us to turn it
              on.
            </p>
          )}
        </div>

        {!readOnly && (
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant={connected ? "outline" : "default"}
              disabled={busy || !configured}
              data-testid={`integration-${card.provider}-connect`}
              onClick={onConnect}
            >
              {connected ? "Reconnect" : "Connect"}
            </Button>
            {connected && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                data-testid={`integration-${card.provider}-disconnect`}
                onClick={onDisconnect}
              >
                Disconnect
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
