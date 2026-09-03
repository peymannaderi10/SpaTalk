import { describe, expect, test } from "vitest";
import {
  DEFAULT_NOTES_LABEL,
  bandLabel,
  blockStateLabel,
  channelLabel,
  clientLabel,
  controllerLabel,
  formatCad,
  formatDuration,
  formatMinutes,
  isOverdue,
  itemTypeLabel,
  notesLabel,
  practitionerLabel,
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

describe("blockStateLabel", () => {
  const now = Date.parse("2026-09-02T12:00:00Z");

  test("a block placed by a person has no end", () => {
    expect(blockStateLabel(null, now)).toBe("Blocked");
    expect(blockStateLabel(undefined, now)).toBe("Blocked");
  });

  test("a live flood mute says when it ends", () => {
    expect(blockStateLabel("2026-09-03T12:00:00Z", now)).toMatch(/^Muted until /);
  });

  test("a mute that has passed says so", () => {
    expect(blockStateLabel("2026-09-01T12:00:00Z", now)).toBe("Mute ended");
  });
});

describe("clientLabel", () => {
  test("says in words whether the caller had been in before", () => {
    expect(clientLabel(false)).toBe("New client");
    expect(clientLabel(true)).toBe("Returning client");
  });

  test("says nothing at all when the question was never asked", () => {
    expect(clientLabel(null)).toBe("");
    expect(clientLabel(undefined)).toBe("");
  });
});

describe("practitionerLabel", () => {
  test("names the person the caller asked for", () => {
    expect(practitionerLabel("Amanda Coutts")).toBe("Amanda Coutts");
  });

  test("reads the runtime's \"any\" as a preference that was asked for", () => {
    expect(practitionerLabel("any")).toBe("No preference");
    expect(practitionerLabel("Any")).toBe("No preference");
  });

  test("says nothing when nobody was ever asked about", () => {
    expect(practitionerLabel(null)).toBe("");
    expect(practitionerLabel(undefined)).toBe("");
    expect(practitionerLabel("")).toBe("");
    expect(practitionerLabel("   ")).toBe("");
  });
});

describe("notesLabel", () => {
  test("uses the tenant's own wording for the drafted notes", () => {
    expect(
      notesLabel({
        scripts: { notes_label: "Notes drafted by the assistant" },
      }),
    ).toBe("Notes drafted by the assistant");
  });

  test("falls back to the runtime's default when the config is not loaded", () => {
    expect(notesLabel()).toBe(DEFAULT_NOTES_LABEL);
    expect(notesLabel(undefined)).toBe(DEFAULT_NOTES_LABEL);
    expect(notesLabel(null)).toBe(DEFAULT_NOTES_LABEL);
    expect(notesLabel({})).toBe(DEFAULT_NOTES_LABEL);
    expect(notesLabel({ scripts: {} })).toBe(DEFAULT_NOTES_LABEL);
  });

  test("never labels the notes with something that is not wording", () => {
    expect(notesLabel({ scripts: { notes_label: "   " } })).toBe(
      DEFAULT_NOTES_LABEL,
    );
    expect(notesLabel({ scripts: { notes_label: 7 } })).toBe(
      DEFAULT_NOTES_LABEL,
    );
    expect(notesLabel({ scripts: null })).toBe(DEFAULT_NOTES_LABEL);
  });

  test("still says the notes were drafted, whatever the tenant wrote", () => {
    expect(DEFAULT_NOTES_LABEL).toBe("AI notes, drafted from the transcript");
  });
});

describe("controllerLabel", () => {
  test("says who is answering, in the words the list uses", () => {
    expect(controllerLabel("ai")).toBe("The assistant");
    expect(controllerLabel("human")).toBe("A person");
    expect(controllerLabel("closed")).toBe("Closed");
  });

  test("shows an unfamiliar controller rather than guessing at one", () => {
    expect(controllerLabel("robot")).toBe("robot");
    expect(controllerLabel("")).toBe("—");
    expect(controllerLabel(null)).toBe("—");
  });
});
