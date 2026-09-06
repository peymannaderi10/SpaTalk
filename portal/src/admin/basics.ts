/**
 * The basics a clinic is asked for when it starts without a bundle
 * (onboarding roadmap, section 4): a timezone, opening hours, a booking link,
 * its own number and the assistant's name. Everything else comes from the
 * runtime's starter bundle, rendered around these by
 * `POST /internal/tenants/from-basics`.
 *
 * The runtime is the authority: its `TenantBasics` refuses the same things.
 * The checks here only spare the admin a round trip and name the field, and
 * they are a pure function so a test can read them without the wizard.
 */

export const WEEKDAYS = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
] as const;

export type Weekday = (typeof WEEKDAYS)[number][0];

/** One weekday as the form holds it: open or closed, and one span when open. */
export type DayHours = { open: boolean; start: string; end: string };

export type BasicsDraft = {
  timezone: string;
  hours: Record<Weekday, DayHours>;
  bookingUrl: string;
  publicPhone: string;
  assistantName: string;
};

/** The runtime's `hours`: every weekday, `[start, end]` spans, empty when closed. */
export type RuntimeHours = Record<Weekday, [string, string][]>;

export const DEFAULT_TIMEZONE = "America/Toronto";
export const DEFAULT_ASSISTANT_NAME = "Ava";

/** The value of the timezone select that reveals the free-text field. */
export const OTHER_TIMEZONE = "other";

/** Canada's zones, east to west; the labels name the cities a clinic knows. */
export const CANADIAN_TIMEZONES: readonly { zone: string; label: string }[] = [
  { zone: "America/St_Johns", label: "Newfoundland (St. John's)" },
  { zone: "America/Halifax", label: "Atlantic (Halifax, Moncton)" },
  { zone: "America/Toronto", label: "Eastern (Toronto, Ottawa, Montreal)" },
  { zone: "America/Winnipeg", label: "Central (Winnipeg)" },
  { zone: "America/Regina", label: "Saskatchewan (Regina, Saskatoon)" },
  { zone: "America/Edmonton", label: "Mountain (Edmonton, Calgary)" },
  { zone: "America/Vancouver", label: "Pacific (Vancouver, Victoria)" },
];

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const E164 = /^\+[1-9]\d{6,14}$/;

/** Whether the JavaScript runtime knows the zone; the runtime's `zoneinfo` knows the same names. */
export function isKnownTimezone(zone: string): boolean {
  if (!zone) {
    return false;
  }
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/** Toronto, weekdays nine to five, Ava: enough to change rather than to invent. */
export function defaultBasics(): BasicsDraft {
  const hours = {} as Record<Weekday, DayHours>;
  for (const [day] of WEEKDAYS) {
    const weekday = day !== "sat" && day !== "sun";
    hours[day] = { open: weekday, start: "09:00", end: "17:00" };
  }
  return {
    timezone: DEFAULT_TIMEZONE,
    hours,
    bookingUrl: "",
    publicPhone: "",
    assistantName: DEFAULT_ASSISTANT_NAME,
  };
}

/** Every problem with the draft, in the order the form shows the fields; empty when it can be sent. */
export function basicsProblems(draft: BasicsDraft): string[] {
  const problems: string[] = [];

  const zone = draft.timezone.trim();
  if (!zone) {
    problems.push("Choose a timezone.");
  } else if (!isKnownTimezone(zone)) {
    problems.push(
      `${zone} is not a timezone the front desk service knows; use an IANA name such as America/Toronto.`,
    );
  }

  const openDays = WEEKDAYS.filter(([day]) => draft.hours[day]?.open);
  if (openDays.length === 0) {
    problems.push("Open on at least one day.");
  }
  for (const [day, label] of openDays) {
    const { start, end } = draft.hours[day];
    if (!HHMM.test(start) || !HHMM.test(end) || !(start < end)) {
      problems.push(
        `${label}: opening and closing times are HH:MM, and it must open before it closes.`,
      );
    }
  }

  if (!isHttpUrl(draft.bookingUrl)) {
    problems.push("Give the online booking link, as a full https:// address.");
  }

  const phone = draft.publicPhone.trim();
  if (phone && !E164.test(phone)) {
    problems.push(
      "The clinic's number is +1 followed by the ten digits, or leave it empty.",
    );
  }

  const assistant = draft.assistantName.trim();
  if (!assistant || assistant.length > 40) {
    problems.push("Give the assistant a name of up to 40 characters.");
  }

  return problems;
}

/** The form's hours in the runtime's shape. */
export function runtimeHours(draft: BasicsDraft): RuntimeHours {
  const hours = {} as RuntimeHours;
  for (const [day] of WEEKDAYS) {
    const entry = draft.hours[day];
    hours[day] = entry?.open ? [[entry.start, entry.end]] : [];
  }
  return hours;
}
