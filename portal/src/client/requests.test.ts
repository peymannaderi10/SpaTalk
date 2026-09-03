import { describe, expect, test } from "vitest";
import {
  matchesRequest,
  requestContact,
  requestFacts,
  requestStateLabel,
  requestSummary,
  sortRequests,
  type RequestLike,
} from "./requests";

/**
 * The requests page reads as a wall of cards, so what a card says about an
 * item is worth pinning down away from the markup: the sentence at the top,
 * the facts under it, and the two controls in the toolbar that decide which
 * cards are on screen and in what order.
 */

function item(overrides: Partial<RequestLike> = {}): RequestLike {
  return {
    id: 41,
    type: "new_booking",
    summary: "New booking for a hydrafacial",
    channel: "voice",
    urgency: "normal",
    state: "open",
    due_at: "2026-09-03T18:00:00Z",
    created_at: "2026-09-03T12:00:00Z",
    contact_name: "Dana W",
    contact_phone: "+19055550101",
    contact_email: null,
    service_name: "Hydrafacial",
    returning_client: null,
    practitioner: null,
    concern: null,
    preferred_window: {},
    preferred_text: "any day",
    acknowledged_by: null,
    resolved_by: null,
    ...overrides,
  };
}

describe("requestSummary", () => {
  test("shows the sentence the runtime composed", () => {
    expect(requestSummary(item())).toBe("New booking for a hydrafacial");
  });

  test("names the type rather than leaving the card headless", () => {
    expect(requestSummary(item({ summary: "" }))).toBe("New booking");
    expect(requestSummary(item({ summary: null, type: "callback" }))).toBe(
      "Callback",
    );
  });
});

describe("requestContact", () => {
  test("joins only what the caller actually left", () => {
    expect(requestContact(item())).toBe("Dana W · +19055550101");
    expect(
      requestContact(item({ contact_name: null, contact_email: "d@x.ca" })),
    ).toBe("+19055550101 · d@x.ca");
    expect(
      requestContact(
        item({ contact_name: null, contact_phone: null, contact_email: null }),
      ),
    ).toBe("");
  });
});

describe("requestFacts", () => {
  test("always says when it was promised and where it stands", () => {
    const labels = requestFacts(item()).map((fact) => fact.label);
    expect(labels).toContain("Promised by");
    expect(labels).toContain("State");
  });

  test("says nothing about a question the caller was never asked", () => {
    const labels = requestFacts(item()).map((fact) => fact.label);
    expect(labels).not.toContain("Client");
    expect(labels).not.toContain("Practitioner");
    expect(labels).not.toContain("Concern");
    expect(labels).not.toContain("Preferred");
  });

  test("shows the lead context the caller did give", () => {
    const facts = requestFacts(
      item({
        returning_client: true,
        practitioner: "any",
        concern: "acne",
        preferred_window: { part_of_day: "morning" },
        preferred_text: "tomorrow morning",
      }),
    );
    const byLabel = new Map(facts.map((fact) => [fact.label, fact.value]));
    expect(byLabel.get("Client")).toBe("Returning client");
    expect(byLabel.get("Practitioner")).toBe("No preference");
    expect(byLabel.get("Concern")).toBe("acne");
    expect(byLabel.get("Preferred")).toBe("tomorrow morning");
  });

  test("a window of 'any' is not a preference the caller expressed", () => {
    const labels = requestFacts(
      item({ preferred_window: { date: "any", part_of_day: "any" } }),
    ).map((fact) => fact.label);
    expect(labels).not.toContain("Preferred");
  });
});

describe("requestStateLabel", () => {
  test("names the person who acted, and never invents one", () => {
    expect(
      requestStateLabel(
        item({ state: "acknowledged", acknowledged_by: "kim@clinic.ca" }),
      ),
    ).toBe("acknowledged by kim@clinic.ca");
    expect(requestStateLabel(item({ state: "resolved" }))).toBe(
      "resolved by someone",
    );
    expect(requestStateLabel(item())).toBe("open");
  });
});

describe("matchesRequest", () => {
  test("an empty search leaves every card on screen", () => {
    expect(matchesRequest(item(), "")).toBe(true);
    expect(matchesRequest(item(), "   ")).toBe(true);
  });

  test("finds a card by its number, its caller and its words", () => {
    expect(matchesRequest(item(), "41")).toBe(true);
    expect(matchesRequest(item(), "#41")).toBe(true);
    expect(matchesRequest(item(), "dana")).toBe(true);
    expect(matchesRequest(item(), "0101")).toBe(true);
    expect(matchesRequest(item(), "hydrafacial")).toBe(true);
    expect(matchesRequest(item({ concern: "acne" }), "acne")).toBe(true);
  });

  test("does not match what the card does not say", () => {
    expect(matchesRequest(item(), "botox")).toBe(false);
  });
});

describe("sortRequests", () => {
  const older = item({ id: 1, created_at: "2026-09-01T09:00:00Z", due_at: "2026-09-05T09:00:00Z" });
  const newer = item({ id: 2, created_at: "2026-09-02T09:00:00Z", due_at: "2026-09-04T09:00:00Z" });

  test("newest first is the default reading order", () => {
    expect(sortRequests([older, newer], "newest").map((row) => row.id)).toEqual([
      2, 1,
    ]);
  });

  test("oldest first turns it around", () => {
    expect(sortRequests([older, newer], "oldest").map((row) => row.id)).toEqual([
      1, 2,
    ]);
  });

  test("by promise puts the soonest deadline at the top", () => {
    expect(sortRequests([older, newer], "due").map((row) => row.id)).toEqual([
      2, 1,
    ]);
  });

  test("never reorders the caller's own array", () => {
    const rows = [older, newer];
    sortRequests(rows, "newest");
    expect(rows.map((row) => row.id)).toEqual([1, 2]);
  });
});
