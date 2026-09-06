import { describe, expect, it } from "vitest";
import {
  FIRST_RUN_KEYS,
  firstRunDone,
  firstRunSteps,
  KNOWLEDGE_MIN_CHARS,
  type FirstRunFacts,
} from "./firstRun";

/**
 * The "Getting set up" checklist on a clinic's overview: what is left before
 * the assistant takes real calls, each step linking to where it is done, and
 * the whole card gone once the first tracked request lands. The facts are the
 * runtime's own (the configuration, the mapped numbers, whether anything has
 * happened yet); this module only reads them.
 */

const closed = {
  mon: [],
  tue: [],
  wed: [],
  thu: [],
  fri: [],
  sat: [],
  sun: [],
};

function facts(overrides: Partial<FirstRunFacts> = {}): FirstRunFacts {
  return {
    slug: "north",
    numbers: [],
    config: {
      hours: closed,
      services: [],
      team: [],
      knowledge: "",
      faq: [],
      delivery: { destinations: [] },
    },
    hadConversation: false,
    hadRequest: false,
    slackConnected: false,
    ...overrides,
  };
}

function config(overrides: Partial<FirstRunFacts["config"]>) {
  return { ...facts().config, ...overrides };
}

function doneKeys(input: FirstRunFacts): string[] {
  return firstRunSteps(input)
    .filter((step) => step.done)
    .map((step) => step.key);
}

describe("firstRunSteps", () => {
  it("is the eight steps, in the order a clinic does them, each linking to where it is done", () => {
    const steps = firstRunSteps(facts());
    expect(steps.map((step) => step.key)).toEqual([...FIRST_RUN_KEYS]);
    expect(steps.map((step) => step.key)).toEqual([
      "number",
      "hours",
      "services",
      "team",
      "knowledge",
      "delivery",
      "conversation",
      "request",
    ]);
    expect(steps.map((step) => step.to)).toEqual([
      "/app/north/settings?tab=numbers",
      "/app/north/settings?tab=hours",
      "/app/north/settings?tab=services",
      "/app/north/settings?tab=team",
      "/app/north/settings?tab=knowledge",
      "/app/north/settings?tab=delivery",
      "/app/north/conversations",
      "/app/north/requests",
    ]);
    for (const step of steps) {
      expect(step.label.length).toBeGreaterThan(0);
      expect(step.done).toBe(false);
    }
  });

  it("ticks the number only for a voice number the agency mapped", () => {
    expect(
      doneKeys(facts({ numbers: [{ number: "+18885550100", kind: "sms" }] })),
    ).toEqual([]);
    expect(
      doneKeys(facts({ numbers: [{ number: "+19055550100", kind: "voice" }] })),
    ).toEqual(["number"]);
  });

  it("ticks the hours once one day is open", () => {
    expect(
      doneKeys(
        facts({
          config: config({ hours: { ...closed, sat: [["10:00", "14:00"]] } }),
        }),
      ),
    ).toEqual(["hours"]);
  });

  it("ticks services and team once there is one of each", () => {
    expect(
      doneKeys(facts({ config: config({ services: [{ id: "facial" }] }) })),
    ).toEqual(["services"]);
    expect(
      doneKeys(facts({ config: config({ team: [{ name: "Helen" }] }) })),
    ).toEqual(["team"]);
  });

  it("ticks knowledge for a page of facts or one FAQ entry, not for the starter skeleton", () => {
    const skeleton =
      "# North Clinic\n\n## Location, contact, hours\n\n- Hours: Monday closed.\n".padEnd(
        600,
        "-",
      );
    expect(
      doneKeys(facts({ config: config({ knowledge: skeleton }) })),
    ).toEqual([]);
    expect(
      doneKeys(
        facts({
          config: config({ knowledge: "x".repeat(KNOWLEDGE_MIN_CHARS) }),
        }),
      ),
    ).toEqual(["knowledge"]);
    expect(
      doneKeys(
        facts({
          config: config({
            faq: [{ question: "Parking?", answer: "Behind." }],
          }),
        }),
      ),
    ).toEqual(["knowledge"]);
  });

  it("ticks delivery for an email address, an email variable or a staff SMS variable, not for a Slack destination that only names an environment variable", () => {
    const destinations = (list: object[]) =>
      doneKeys(facts({ config: config({ delivery: { destinations: list } }) }));
    expect(
      destinations([{ kind: "slack", webhook_env: "X_SLACK_WEBHOOK" }]),
    ).toEqual([]);
    expect(
      destinations([{ kind: "email", address: "owner@north.test" }]),
    ).toEqual(["delivery"]);
    expect(
      destinations([{ kind: "email", address_env: "NORTH_EMAIL" }]),
    ).toEqual(["delivery"]);
    expect(
      destinations([{ kind: "sms", address_env: "NORTH_STAFF_SMS" }]),
    ).toEqual(["delivery"]);
    expect(destinations([{ kind: "email", address: "" }])).toEqual([]);
  });

  it("ticks delivery for a Slack workspace the clinic connected from the Integrations tab", () => {
    // A connected workspace is a real place requests land, unlike an env-named webhook
    // the portal cannot see into; it satisfies the step on its own.
    expect(doneKeys(facts({ slackConnected: true }))).toEqual(["delivery"]);
    expect(
      firstRunSteps(facts({ slackConnected: true })).find(
        (step) => step.key === "delivery",
      )?.label,
    ).toMatch(/Slack/);
  });

  it("ticks the conversation and the request from what the runtime has seen", () => {
    expect(doneKeys(facts({ hadConversation: true }))).toEqual([
      "conversation",
    ]);
    expect(doneKeys(facts({ hadRequest: true }))).toEqual(["request"]);
  });

  it("copes with a configuration that lacks the fields", () => {
    const steps = firstRunSteps(facts({ config: {} }));
    expect(steps).toHaveLength(8);
    expect(steps.every((step) => !step.done)).toBe(true);
  });
});

describe("firstRunDone", () => {
  it("is true only once the first request has landed, whatever else is left", () => {
    expect(firstRunDone(facts())).toBe(false);
    expect(
      firstRunDone(
        facts({
          numbers: [{ number: "+19055550100", kind: "voice" }],
          hadConversation: true,
        }),
      ),
    ).toBe(false);
    expect(firstRunDone(facts({ hadRequest: true }))).toBe(true);
  });
});
