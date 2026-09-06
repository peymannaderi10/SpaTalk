import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntegrationsTab } from "./Integrations";

/**
 * The Slack card on Settings → Integrations (onboarding roadmap, section 3):
 * a clinic connects its own workspace with one click. Everything shown is the
 * runtime's; the portal keeps no token, no webhook URL and no channel id, and
 * Connect is a runtime-signed link the browser is sent to.
 */

const mocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
  startIntegrationConnect: vi.fn(),
  disconnectIntegration: vi.fn(),
  selectMessengerPage: vi.fn(),
}));

vi.mock("wasp/client/operations", () => ({
  useQuery: mocks.useQuery,
  getTenantIntegrations: () => undefined,
  startIntegrationConnect: mocks.startIntegrationConnect,
  disconnectIntegration: mocks.disconnectIntegration,
  selectMessengerPage: mocks.selectMessengerPage,
}));

type Row = {
  provider: string;
  connected: boolean;
  configured: boolean;
  external_id?: string | null;
  display_name?: string | null;
  token_expires_at?: string | null;
  scopes?: string[];
  needs_reconnect?: boolean;
  connected_by?: string | null;
  connected_at?: string | null;
};

const notConnected = (provider: string): Row => ({
  provider,
  connected: false,
  configured: true,
});

const connectedSlack: Row = {
  provider: "slack",
  connected: true,
  configured: true,
  external_id: "T0123ABC",
  display_name: "Skincentrix · #front-desk",
  token_expires_at: null,
  scopes: ["incoming-webhook", "chat:write"],
  needs_reconnect: false,
  connected_by: "slack connect link",
  connected_at: "2026-09-06T12:00:00Z",
};

function mount(
  slack: Row = notConnected("slack"),
  { role = "OWNER", readOnly = false } = {},
) {
  const refetch = vi.fn().mockResolvedValue(undefined);
  mocks.useQuery.mockReturnValue({
    data: {
      role,
      integrations: [
        notConnected("instagram"),
        notConnected("messenger"),
        slack,
      ],
    },
    isLoading: false,
    error: null,
    refetch,
  });
  render(<IntegrationsTab slug="north" readOnly={readOnly} />);
  return refetch;
}

const assign = vi.fn();

beforeEach(() => {
  Object.defineProperty(window, "location", {
    value: { search: "", assign },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("the Slack card", () => {
  it("says Not connected, offers Connect and no Disconnect, and says what connecting does", () => {
    mount();

    const card = screen.getByTestId("integration-slack");
    expect(card).toHaveTextContent("Slack");
    expect(screen.getByTestId("integration-slack-status")).toHaveTextContent(
      "Not connected",
    );
    expect(screen.getByTestId("integration-slack-connect")).toHaveTextContent(
      "Connect",
    );
    expect(screen.queryByTestId("integration-slack-disconnect")).toBeNull();
    // What the owner is agreeing to, in their words.
    expect(card).toHaveTextContent(/Acknowledge/);
    expect(card).toHaveTextContent(/Resolve/);
    expect(card).toHaveTextContent(/reply to the customer from the thread/i);
    // The two Meta cards are still there.
    expect(screen.getByTestId("integration-instagram")).toBeInTheDocument();
    expect(screen.getByTestId("integration-messenger")).toBeInTheDocument();
  });

  it("renders a connected workspace: the workspace and channel, who connected it, no token", () => {
    mount(connectedSlack);

    const card = screen.getByTestId("integration-slack");
    expect(screen.getByTestId("integration-slack-status")).toHaveTextContent(
      "Connected as Skincentrix · #front-desk",
    );
    expect(card).toHaveTextContent("Connected by slack connect link");
    expect(
      screen.getByTestId("integration-slack-disconnect"),
    ).toHaveTextContent("Disconnect");
    expect(screen.getByTestId("integration-slack-connect")).toHaveTextContent(
      "Reconnect",
    );
    // A bot token is not renewed like a Meta token; the card must not say it is.
    expect(card).not.toHaveTextContent(/renewed automatically/);
    // The bot has to be invited to the channel for threads; the card says so.
    expect(screen.getByTestId("integration-slack-invite")).toHaveTextContent(
      /invite/i,
    );
    expect(card.innerHTML).not.toMatch(/xoxb|access_token|hooks\.slack\.com/);
  });

  it("Connect asks the runtime for the Slack link and sends the browser there", async () => {
    mocks.startIntegrationConnect.mockResolvedValue({
      url: "https://slack.com/oauth/v2/authorize?client_id=X&state=signed",
      expiresIn: 900,
    });
    mount();

    fireEvent.click(screen.getByTestId("integration-slack-connect"));

    await waitFor(() =>
      expect(mocks.startIntegrationConnect).toHaveBeenCalledWith({
        slug: "north",
        provider: "slack",
      }),
    );
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        "https://slack.com/oauth/v2/authorize?client_id=X&state=signed",
      ),
    );
  });

  it("Disconnect calls the action with slack and redraws from the runtime", async () => {
    mocks.disconnectIntegration.mockResolvedValue({
      role: "OWNER",
      integrations: [],
    });
    const refetch = mount(connectedSlack);

    fireEvent.click(screen.getByTestId("integration-slack-disconnect"));

    await waitFor(() =>
      expect(mocks.disconnectIntegration).toHaveBeenCalledWith({
        slug: "north",
        provider: "slack",
      }),
    );
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("shows the problem when the link cannot be minted", async () => {
    mocks.startIntegrationConnect.mockRejectedValue(
      new Error("slack is not configured on this service"),
    );
    mount();

    fireEvent.click(screen.getByTestId("integration-slack-connect"));

    await waitFor(() =>
      expect(screen.getByTestId("integration-problem")).toHaveTextContent(
        "slack is not configured on this service",
      ),
    );
    expect(assign).not.toHaveBeenCalled();
  });

  it("has no buttons for someone who is not the owner", () => {
    mount(connectedSlack, { role: "MEMBER", readOnly: true });

    expect(screen.getByTestId("integration-slack-status")).toHaveTextContent(
      "Connected as Skincentrix · #front-desk",
    );
    expect(screen.queryByTestId("integration-slack-connect")).toBeNull();
    expect(screen.queryByTestId("integration-slack-disconnect")).toBeNull();
  });

  it("says when Slack is not set up on this service and keeps Connect disabled", () => {
    mount({ ...notConnected("slack"), configured: false });

    expect(
      screen.getByTestId("integration-slack-unconfigured"),
    ).toHaveTextContent(/not set up on this service/);
    expect(screen.getByTestId("integration-slack-connect")).toBeDisabled();
  });
});
