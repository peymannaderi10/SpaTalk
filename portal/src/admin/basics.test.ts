import { describe, expect, test } from "vitest";
import {
  basicsProblems,
  CANADIAN_TIMEZONES,
  DEFAULT_TIMEZONE,
  defaultBasics,
  isKnownTimezone,
  runtimeHours,
  WEEKDAYS,
  type BasicsDraft,
} from "./basics";

/**
 * The "start from the basics" form of the onboarding wizard, judged before it
 * is sent. The runtime is the authority (`TenantBasics` refuses the same
 * things); these checks only spare the admin a round trip and name the field.
 */

function draft(overrides: Partial<BasicsDraft> = {}): BasicsDraft {
  return { ...defaultBasics(), ...overrides };
}

describe("defaultBasics", () => {
  test("is Toronto, weekdays nine to five, and an assistant called Ava", () => {
    const basics = defaultBasics();
    expect(basics.timezone).toBe(DEFAULT_TIMEZONE);
    expect(basics.assistantName).toBe("Ava");
    expect(basics.hours.mon).toEqual({
      open: true,
      start: "09:00",
      end: "17:00",
    });
    expect(basics.hours.fri.open).toBe(true);
    expect(basics.hours.sat.open).toBe(false);
    expect(basics.hours.sun.open).toBe(false);
    expect(basics.bookingUrl).toBe("");
    expect(basics.publicPhone).toBe("");
  });

  test("passes its own checks once a booking link is given", () => {
    expect(
      basicsProblems(draft({ bookingUrl: "https://clinic.janeapp.com/" })),
    ).toEqual([]);
  });
});

describe("CANADIAN_TIMEZONES", () => {
  test("lists the seven Canadian zones, Toronto first among the defaults", () => {
    const zones = CANADIAN_TIMEZONES.map((entry) => entry.zone);
    expect(zones).toEqual([
      "America/St_Johns",
      "America/Halifax",
      "America/Toronto",
      "America/Winnipeg",
      "America/Regina",
      "America/Edmonton",
      "America/Vancouver",
    ]);
    expect(zones).toContain(DEFAULT_TIMEZONE);
    for (const zone of zones) {
      expect(isKnownTimezone(zone)).toBe(true);
    }
  });
});

describe("isKnownTimezone", () => {
  test("knows an IANA name and refuses a made-up one", () => {
    expect(isKnownTimezone("Europe/London")).toBe(true);
    expect(isKnownTimezone("Toronto/Eastern")).toBe(false);
    expect(isKnownTimezone("")).toBe(false);
    expect(isKnownTimezone("EST")).toBe(true);
  });
});

describe("basicsProblems", () => {
  const ok = { bookingUrl: "https://clinic.janeapp.com/" };

  test("wants a timezone the runtime will know", () => {
    expect(basicsProblems(draft({ ...ok, timezone: "" }))).toEqual([
      "Choose a timezone.",
    ]);
    expect(
      basicsProblems(draft({ ...ok, timezone: "Toronto/Eastern" }))[0],
    ).toMatch(/Toronto\/Eastern.*IANA/);
  });

  test("wants at least one open day", () => {
    const closed = draft(ok);
    for (const [day] of WEEKDAYS) {
      closed.hours[day] = { ...closed.hours[day], open: false };
    }
    expect(basicsProblems(closed)).toEqual(["Open on at least one day."]);
  });

  test("wants HH:MM times that open before they close, naming the day", () => {
    const bad = draft(ok);
    bad.hours.tue = { open: true, start: "18:00", end: "10:00" };
    bad.hours.wed = { open: true, start: "9am", end: "17:00" };
    bad.hours.thu = { open: true, start: "", end: "17:00" };
    // A closed day's times are not looked at.
    bad.hours.sat = { open: false, start: "", end: "" };
    const problems = basicsProblems(bad);
    expect(problems).toHaveLength(3);
    expect(problems[0]).toMatch(/^Tuesday/);
    expect(problems[1]).toMatch(/^Wednesday/);
    expect(problems[2]).toMatch(/^Thursday/);
  });

  test("wants a full http(s) booking link", () => {
    expect(basicsProblems(draft({ bookingUrl: "" }))).toEqual([
      "Give the online booking link, as a full https:// address.",
    ]);
    expect(basicsProblems(draft({ bookingUrl: "clinic.janeapp.com" }))).toEqual(
      ["Give the online booking link, as a full https:// address."],
    );
    expect(basicsProblems(draft({ bookingUrl: "ftp://clinic.test/" }))).toEqual(
      ["Give the online booking link, as a full https:// address."],
    );
    expect(
      basicsProblems(draft({ bookingUrl: "http://clinic.test/book" })),
    ).toEqual([]);
  });

  test("takes the clinic's number as E.164 or nothing", () => {
    expect(
      basicsProblems(draft({ ...ok, publicPhone: "+19055550123" })),
    ).toEqual([]);
    expect(basicsProblems(draft({ ...ok, publicPhone: "" }))).toEqual([]);
    expect(
      basicsProblems(draft({ ...ok, publicPhone: "905-555-0123" })),
    ).toEqual([
      "The clinic's number is +1 followed by the ten digits, or leave it empty.",
    ]);
  });

  test("wants the assistant to have a short name", () => {
    expect(basicsProblems(draft({ ...ok, assistantName: "  " }))).toEqual([
      "Give the assistant a name of up to 40 characters.",
    ]);
    expect(
      basicsProblems(draft({ ...ok, assistantName: "A".repeat(41) })),
    ).toEqual(["Give the assistant a name of up to 40 characters."]);
  });

  test("lists every problem at once, in form order", () => {
    const bad = draft({
      timezone: "",
      bookingUrl: "",
      publicPhone: "nope",
      assistantName: "",
    });
    expect(basicsProblems(bad)).toEqual([
      "Choose a timezone.",
      "Give the online booking link, as a full https:// address.",
      "The clinic's number is +1 followed by the ten digits, or leave it empty.",
      "Give the assistant a name of up to 40 characters.",
    ]);
  });
});

describe("runtimeHours", () => {
  test("is the runtime's shape: every weekday, a span for an open day, nothing for a closed one", () => {
    const basics = draft();
    basics.hours.sat = { open: true, start: "10:00", end: "14:00" };
    const hours = runtimeHours(basics);
    expect(Object.keys(hours)).toEqual([
      "mon",
      "tue",
      "wed",
      "thu",
      "fri",
      "sat",
      "sun",
    ]);
    expect(hours.mon).toEqual([["09:00", "17:00"]]);
    expect(hours.sat).toEqual([["10:00", "14:00"]]);
    expect(hours.sun).toEqual([]);
  });
});
