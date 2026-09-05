import { fireEvent, render, screen } from "@testing-library/react";
import { existsSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { InternalToggle, QuoteBuilder } from "./QuoteBuilder";
import { ASSUMPTIONS_STORAGE_KEY, type RatesFile } from "./pricing";

/**
 * What a prospective client is allowed to see over the admin's shoulder.
 *
 * The face of this page is a price. What it costs us, what margin is on it and
 * how many clinics are sharing the servers are the agency's business, and none
 * of it is in the document at all until the admin presses the three dots that
 * switch the page to internal view — "hidden" here means absent, not merely
 * invisible.
 */

function findPortalRoot(): string {
  let dir = process.cwd();
  for (let hop = 0; hop < 8; hop += 1) {
    if (existsSync(join(dir, "main.wasp.ts"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(`could not find the portal root above ${process.cwd()}`);
}

const RATES: RatesFile = JSON.parse(
  readFileSync(
    join(findPortalRoot(), "..", "docs", "research", "rates.json"),
    "utf8",
  ),
) as RatesFile;

/** Every line of the cost of goods, by the testid the breakdown gives it. */
const COST_LINES = [
  "pricing-line-voice",
  "pricing-line-sms",
  "pricing-line-chat",
  "pricing-line-outbound",
  "pricing-line-per-tenant-fixed",
  "pricing-line-platform-share",
  "pricing-cogs",
];

/** Anything on this list in the visible page would be telling on ourselves. */
const INTERNAL_WORDS = /margin|cost of goods|CAD\/min/i;

/** The page as `AdminPricingPage` wires it: the three dots above the quote. */
function Page() {
  const [internal, setInternal] = useState(false);
  return (
    <>
      <InternalToggle
        internal={internal}
        onToggle={() => setInternal((on) => !on)}
      />
      <QuoteBuilder rates={RATES} internal={internal} />
    </>
  );
}

beforeEach(() => {
  window.localStorage.removeItem(ASSUMPTIONS_STORAGE_KEY);
});

describe("the quote page a client may be looking at", () => {
  it("shows the monthly price and the four unit prices", () => {
    render(<QuoteBuilder rates={RATES} />);

    // The founder's defaults over the live stack: CA$224.39 a month.
    expect(screen.getByTestId("pricing-price")).toHaveTextContent("224.39");
    expect(screen.getByTestId("pricing-price-per-call")).toHaveTextContent(
      "0.2610",
    );
    expect(screen.getByTestId("pricing-price-per-minute")).toHaveTextContent(
      "0.0870",
    );
    expect(screen.getByTestId("pricing-price-per-text")).toHaveTextContent(
      "0.4043",
    );
    expect(screen.getByTestId("pricing-price-per-chat")).toHaveTextContent(
      "0.0072",
    );
  });

  it("asks only what the client needs", () => {
    render(<QuoteBuilder rates={RATES} />);

    for (const field of [
      "pricing-calls",
      "pricing-avg-minutes",
      "pricing-sms-convs",
      "pricing-chat-convs",
      "pricing-outbound",
    ]) {
      expect(screen.getByTestId(field)).toBeInTheDocument();
    }
    // No stack to choose: the quote prices what is running.
    expect(screen.queryByTestId("pricing-voice-stack")).toBeNull();
    expect(screen.queryByTestId("pricing-text-stack")).toBeNull();
    // And nothing about one tenant's measured month.
    expect(screen.queryByTestId("pricing-tenant")).toBeNull();
    // And no list price: the client sees only their own.
    expect(screen.queryByTestId("pricing-list-price")).toBeNull();
  });

  it("keeps every cost line out of the document while internal view is off", () => {
    render(<QuoteBuilder rates={RATES} />);

    for (const testId of COST_LINES) {
      expect(
        screen.queryByTestId(testId),
        `${testId} is on the page`,
      ).toBeNull();
    }
    for (const testId of [
      "pricing-margin",
      "pricing-clients",
      "pricing-at",
      "pricing-list-margin",
      "pricing-fx",
      "pricing-per-call",
      "pricing-per-minute",
    ]) {
      expect(
        screen.queryByTestId(testId),
        `${testId} is on the page`,
      ).toBeNull();
    }
  });

  it("says nothing about margin, cost of goods or a rate a minute", () => {
    const { container } = render(<Page />);
    const words = container.textContent ?? "";
    expect(words).not.toMatch(INTERNAL_WORDS);
    // A guard on the guard: the words do exist once internal view is on.
    fireEvent.click(screen.getByTestId("pricing-assumptions"));
    expect(container.textContent ?? "").toMatch(INTERNAL_WORDS);
  });

  it("switches to internal view on the three dots, and back again", () => {
    render(<Page />);
    fireEvent.click(screen.getByTestId("pricing-assumptions"));

    for (const testId of COST_LINES) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
    expect(screen.getByTestId("pricing-cogs")).toHaveTextContent("78.53");
    expect(screen.getByTestId("pricing-at")).toHaveTextContent("65%");
    expect(screen.getByTestId("pricing-list-margin")).toHaveTextContent("92");
    expect(screen.getByTestId("pricing-margin")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-clients")).toBeInTheDocument();
    expect(screen.getByTestId("pricing-fx")).toHaveTextContent(
      RATES.live_stack.label,
    );

    // A second press turns the page back towards the client.
    fireEvent.click(screen.getByTestId("pricing-assumptions"));
    expect(screen.queryByTestId("pricing-cogs")).toBeNull();
  });

  it("re-prices when the client's volumes change", () => {
    render(<QuoteBuilder rates={RATES} />);
    const before = screen.getByTestId("pricing-price").textContent;

    fireEvent.change(screen.getByTestId("pricing-calls"), {
      target: { value: "1000" },
    });

    expect(screen.getByTestId("pricing-price").textContent).not.toBe(before);
  });
});
