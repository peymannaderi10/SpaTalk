import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NumbersTab } from "./NumbersTab";

/**
 * The Numbers page's "Forward your line" card: the one thing a clinic has to
 * do on its own phone system before a single call reaches the assistant. It
 * exists only once the agency has mapped a voice number; before that the page
 * says so in one line rather than showing instructions for a number that does
 * not exist. The wording is the runbook's ("What to tell the clinic to do" in
 * `docs/runbooks/accounts-and-env.md`): no answer after four rings and busy,
 * Incoming Caller ID on TELUS Business Connect, one line that never forwards.
 */

const config = {
  sms_from_number: "+12899170079",
  transfer_number: null,
  public_phone: "+19057037546",
  booking_url_default: "https://skincentrix.janeapp.com/",
};

const VOICE = { number: "+19055550100", kind: "voice" };
const SMS = { number: "+18885550100", kind: "sms" };

function mount(numbers: { number: string; kind: string }[]) {
  render(<NumbersTab config={config} numbers={numbers} />);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the Forward your line card", () => {
  it("shows the assigned voice number, large, with the forwarding conditions", () => {
    mount([VOICE, SMS]);

    const card = screen.getByTestId("forward-line");
    expect(screen.getByTestId("forward-line-number")).toHaveTextContent(
      "+19055550100",
    );
    // The texting number is not what the line forwards to.
    expect(screen.getByTestId("forward-line-number")).not.toHaveTextContent(
      "+18885550100",
    );
    expect(card).toHaveTextContent(/no answer after four rings/i);
    expect(card).toHaveTextContent(/on busy/i);
    expect(card).toHaveTextContent(/TELUS Business Connect/);
    expect(card).toHaveTextContent(/Incoming Caller ID/);
    expect(card).toHaveTextContent(/not Dialed Number/);
    expect(card).toHaveTextContent(/does not forward/);
    expect(card).toHaveTextContent(/ask your provider to forward/i);
    expect(screen.queryByTestId("forward-line-unassigned")).toBeNull();
  });

  it("is absent without a voice number, and says the agency assigns one", () => {
    mount([SMS]);

    expect(screen.queryByTestId("forward-line")).toBeNull();
    expect(screen.getByTestId("forward-line-unassigned")).toHaveTextContent(
      /No number assigned yet/,
    );
    expect(screen.getByTestId("forward-line-unassigned")).toHaveTextContent(
      /agency/,
    );
  });

  it("is absent with no numbers at all", () => {
    mount([]);

    expect(screen.queryByTestId("forward-line")).toBeNull();
    expect(screen.getByTestId("forward-line-unassigned")).toBeInTheDocument();
  });

  it("copies the number to the clipboard and says so", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mount([VOICE]);

    fireEvent.click(screen.getByTestId("forward-line-copy"));

    expect(writeText).toHaveBeenCalledWith("+19055550100");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });
});
