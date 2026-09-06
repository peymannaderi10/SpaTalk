import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { FirstRunCard } from "./FirstRunCard";
import { firstRunSteps, type FirstRunFacts } from "./firstRun";

/**
 * The "Getting set up" card above the overview's tiles: one line per step,
 * ticked when done, each linking to where it is done, and nothing at all once
 * the first tracked request exists.
 */

function facts(overrides: Partial<FirstRunFacts> = {}): FirstRunFacts {
  return {
    slug: "north",
    numbers: [{ number: "+19055550100", kind: "voice" }],
    config: {
      hours: { mon: [["09:00", "17:00"]] },
      services: [],
      team: [],
      knowledge: "",
      faq: [],
      delivery: {
        destinations: [{ kind: "email", address: "owner@north.test" }],
      },
    },
    hadConversation: false,
    hadRequest: false,
    ...overrides,
  };
}

function mount(input: FirstRunFacts) {
  const steps = firstRunSteps(input);
  return render(
    <MemoryRouter initialEntries={["/app/north/overview"]}>
      <FirstRunCard steps={steps} />
    </MemoryRouter>,
  );
}

describe("the Getting set up card", () => {
  it("lists every step, ticking the ones that are done", () => {
    mount(facts());

    const card = screen.getByTestId("first-run-card");
    expect(card).toHaveTextContent("Getting set up");
    for (const key of [
      "number",
      "hours",
      "services",
      "team",
      "knowledge",
      "delivery",
      "conversation",
      "request",
    ]) {
      expect(screen.getByTestId(`first-run-step-${key}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("first-run-done-number")).toBeInTheDocument();
    expect(screen.getByTestId("first-run-done-hours")).toBeInTheDocument();
    expect(screen.getByTestId("first-run-done-delivery")).toBeInTheDocument();
    expect(screen.queryByTestId("first-run-done-services")).toBeNull();
    expect(screen.queryByTestId("first-run-done-team")).toBeNull();
    expect(screen.queryByTestId("first-run-done-knowledge")).toBeNull();
    expect(screen.queryByTestId("first-run-done-conversation")).toBeNull();
    expect(screen.queryByTestId("first-run-done-request")).toBeNull();
  });

  it("links each step to where it is done", () => {
    mount(facts());

    const link = (key: string) =>
      screen
        .getByTestId(`first-run-step-${key}`)
        .querySelector("a")
        ?.getAttribute("href");
    expect(link("services")).toBe("/app/north/settings?tab=services");
    expect(link("team")).toBe("/app/north/settings?tab=team");
    expect(link("knowledge")).toBe("/app/north/settings?tab=knowledge");
    expect(link("conversation")).toBe("/app/north/conversations");
  });

  it("counts what is done", () => {
    mount(facts());

    expect(screen.getByTestId("first-run-progress")).toHaveTextContent(
      "3 of 8",
    );
  });

  it("is gone once the first request has landed", () => {
    const { container } = mount(facts({ hadRequest: true }));

    expect(screen.queryByTestId("first-run-card")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });
});
