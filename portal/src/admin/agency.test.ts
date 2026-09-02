import { describe, expect, test } from "vitest";
import {
  PLAN_MONTHLY_CAD,
  isPayingStatus,
  lastActivityOf,
  mrrCadFor,
  sortTenantRows,
  totalMrrCad,
  type AgencyTenantRow,
} from "./agency";

/**
 * The agency's tenants table: what it may claim about money, what it shows for
 * a tenant the runtime has never heard of, and how it sorts.
 */

function row(over: Partial<AgencyTenantRow> = {}): AgencyTenantRow {
  return {
    organizationId: "org-1",
    name: "Skincentrix",
    slug: "skincentrix",
    runtimeTenantId: "skincentrix",
    configured: true,
    problem: null,
    configVersion: 1,
    calls: 0,
    callMinutes: 0,
    texts: 0,
    chats: 0,
    estCostCad: 0,
    openItems: 0,
    overdueItems: 0,
    lastActivityAt: null,
    subscriptionStatus: null,
    subscriptionPlan: null,
    mrrCad: 0,
    ...over,
  };
}

describe("isPayingStatus", () => {
  test("counts the statuses Stripe leaves a live subscription in", () => {
    expect(isPayingStatus("active")).toBe(true);
    expect(isPayingStatus("trialing")).toBe(true);
    // Still paying until the period ends.
    expect(isPayingStatus("cancel_at_period_end")).toBe(true);
  });

  test("counts nothing else, including an organisation that never subscribed", () => {
    expect(isPayingStatus("past_due")).toBe(false);
    expect(isPayingStatus("deleted")).toBe(false);
    expect(isPayingStatus(null)).toBe(false);
    expect(isPayingStatus(undefined)).toBe(false);
  });
});

describe("mrrCadFor", () => {
  test("is the plan's monthly price for a paying organisation", () => {
    expect(mrrCadFor("active")).toBe(PLAN_MONTHLY_CAD);
  });

  test("is nothing for an organisation that is not paying", () => {
    expect(mrrCadFor("past_due")).toBe(0);
    expect(mrrCadFor(null)).toBe(0);
  });

  test("takes the price it is given, so a changed plan needs no new arithmetic", () => {
    expect(mrrCadFor("active", 1299)).toBe(1299);
  });
});

describe("totalMrrCad", () => {
  test("adds up only what the organisations are actually paying", () => {
    const rows = [
      row({ subscriptionStatus: "active", mrrCad: 999 }),
      row({ subscriptionStatus: "past_due", mrrCad: 0 }),
      row({ subscriptionStatus: "trialing", mrrCad: 999 }),
    ];
    expect(totalMrrCad(rows)).toBe(1998);
  });
});

describe("lastActivityOf", () => {
  test("is the later of the last call and the last text", () => {
    expect(
      lastActivityOf({
        last_call_at: "2026-09-01T10:00:00Z",
        last_sms_at: "2026-09-02T09:00:00Z",
      }),
    ).toBe("2026-09-02T09:00:00Z");
  });

  test("is whichever one exists when only one does", () => {
    expect(
      lastActivityOf({
        last_call_at: null,
        last_sms_at: "2026-09-02T09:00:00Z",
      }),
    ).toBe("2026-09-02T09:00:00Z");
  });

  test("is nothing when the tenant has had no activity at all", () => {
    expect(
      lastActivityOf({ last_call_at: null, last_sms_at: null }),
    ).toBeNull();
  });
});

describe("sortTenantRows", () => {
  const rows = [
    row({ organizationId: "b", name: "Beacon", calls: 5, estCostCad: 12.5 }),
    row({ organizationId: "a", name: "Aurora", calls: 40, estCostCad: 3 }),
    row({ organizationId: "c", name: "Cedar", calls: 12, estCostCad: 99 }),
  ];

  test("orders by name in either direction", () => {
    expect(sortTenantRows(rows, "name", "asc").map((r) => r.name)).toEqual([
      "Aurora",
      "Beacon",
      "Cedar",
    ]);
    expect(sortTenantRows(rows, "name", "desc").map((r) => r.name)).toEqual([
      "Cedar",
      "Beacon",
      "Aurora",
    ]);
  });

  test("orders by a number, not by the text of that number", () => {
    expect(sortTenantRows(rows, "calls", "desc").map((r) => r.calls)).toEqual([
      40, 12, 5,
    ]);
    expect(
      sortTenantRows(rows, "cost", "desc").map((r) => r.estCostCad),
    ).toEqual([99, 12.5, 3]);
  });

  test("leaves the given rows alone", () => {
    const before = rows.map((r) => r.name);
    sortTenantRows(rows, "name", "desc");
    expect(rows.map((r) => r.name)).toEqual(before);
  });

  test("puts a tenant with no activity last however the column is sorted", () => {
    const withDates = [
      row({ organizationId: "quiet", lastActivityAt: null }),
      row({ organizationId: "old", lastActivityAt: "2026-08-01T10:00:00Z" }),
      row({ organizationId: "recent", lastActivityAt: "2026-09-02T10:00:00Z" }),
    ];
    expect(
      sortTenantRows(withDates, "activity", "desc").map(
        (r) => r.organizationId,
      ),
    ).toEqual(["recent", "old", "quiet"]);
    expect(
      sortTenantRows(withDates, "activity", "asc").map((r) => r.organizationId),
    ).toEqual(["old", "recent", "quiet"]);
  });
});
