import { describe, expect, test } from "vitest";
import {
  bandLabel,
  channelLabel,
  formatCad,
  formatDuration,
  formatMinutes,
  isOverdue,
  itemTypeLabel,
} from "./formatting";

describe("bandLabel", () => {
  test("names the three outcomes the runtime records", () => {
    expect(bandLabel(1)).toBe("handled");
    expect(bandLabel(2)).toBe("sent to team");
    expect(bandLabel(3)).toBe("to a person");
  });

  test("says nothing about the outcome of a conversation still running", () => {
    expect(bandLabel(null)).toBe("in progress");
    expect(bandLabel(undefined)).toBe("in progress");
  });
});

describe("itemTypeLabel", () => {
  test("puts every tracked item type into words", () => {
    expect(itemTypeLabel("escalation_clinical")).toBe("Clinical");
    expect(itemTypeLabel("new_booking")).toBe("New booking");
  });

  test("falls back to the runtime's own word for a type it has not met", () => {
    expect(itemTypeLabel("brand_new_kind")).toBe("brand new kind");
  });
});

describe("isOverdue", () => {
  const now = Date.parse("2026-09-02T12:00:00Z");

  test("is true only for work still waiting past its promised time", () => {
    const late = { state: "open", due_at: "2026-09-02T11:00:00Z" };
    const acknowledged = {
      state: "acknowledged",
      due_at: "2026-09-02T11:00:00Z",
    };
    expect(isOverdue(late, now)).toBe(true);
    expect(isOverdue(acknowledged, now)).toBe(true);
  });

  test("is false once it is resolved, however late it was", () => {
    expect(
      isOverdue({ state: "resolved", due_at: "2026-09-01T00:00:00Z" }, now),
    ).toBe(false);
  });

  test("is false before the promised time", () => {
    expect(
      isOverdue({ state: "open", due_at: "2026-09-02T13:00:00Z" }, now),
    ).toBe(false);
  });
});

describe("the smaller formatters", () => {
  test("show call minutes to one decimal", () => {
    expect(formatMinutes(6)).toBe("6.0");
    expect(formatMinutes(6.04)).toBe("6.0");
  });

  test("price in Canadian dollars, the currency the rates table is in", () => {
    expect(formatCad(0.2044)).toContain("0.20");
  });

  test("show a call length in minutes and seconds", () => {
    expect(formatDuration(240)).toBe("4m 0s");
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(null)).toBe("—");
  });

  test("name every channel the runtime answers on", () => {
    expect(channelLabel("voice")).toBe("Phone");
    expect(channelLabel("sms")).toBe("Text");
    expect(channelLabel("chat")).toBe("Web chat");
  });
});
