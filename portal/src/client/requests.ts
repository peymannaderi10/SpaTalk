import {
  clientLabel,
  formatDateTime,
  itemTypeLabel,
  practitionerLabel,
} from "./formatting";

/**
 * What a request card says, decided away from the markup.
 *
 * The page is a wall of cards in the kit's card idiom, and three things about
 * a card are worth pinning down where a test can reach them: the sentence at
 * the top, the facts under it, and the two toolbar controls that decide which
 * cards are on screen and in what order.
 *
 * The rules the ledger relies on this file to keep are the ones the page kept
 * before it: the summary sentence is the runtime's, composed once from the
 * item's closed fields; a fact whose question the caller was never asked gets
 * no line at all rather than an invented one; and a state names the person the
 * runtime recorded, never someone the portal supposes.
 */

/** A tracked request, as much of one as this file reads. */
export type RequestLike = {
  id: number;
  type: string;
  summary?: string | null;
  channel: string;
  urgency?: string | null;
  state: string;
  due_at: string;
  created_at: string;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
  service_name?: string | null;
  returning_client?: boolean | null;
  practitioner?: string | null;
  concern?: string | null;
  preferred_window?: { [key: string]: unknown } | null;
  preferred_text?: string | null;
  acknowledged_by?: string | null;
  resolved_by?: string | null;
};

/** One line of the card's description list. */
export type RequestFact = { label: string; value: string };

/**
 * The runtime composes the sentence; the card only shows it. The fallback is
 * for a row read from a runtime that predates the summary — it names the type
 * rather than leaving the card headless, and claims nothing beyond it.
 */
export function requestSummary(item: RequestLike): string {
  return item.summary || itemTypeLabel(item.type);
}

/** Only what the caller actually left, in the order a person would read it. */
export function requestContact(item: RequestLike): string {
  return [item.contact_name, item.contact_phone, item.contact_email]
    .filter(Boolean)
    .join(" · ");
}

/**
 * `preferred_text` always reads as something — an item nobody was asked about
 * says "any day" — so the line is shown only when the caller actually named a
 * day or a time of day. The summary sentence says the rest.
 */
export function askedForATime(item: RequestLike): boolean {
  const window = (item.preferred_window ?? {}) as {
    date?: string;
    part_of_day?: string;
  };
  return [window.date, window.part_of_day].some(
    (value) => typeof value === "string" && value !== "" && value !== "any",
  );
}

export function requestStateLabel(item: RequestLike): string {
  if (item.state === "acknowledged") {
    return `acknowledged by ${item.acknowledged_by ?? "someone"}`;
  }
  if (item.state === "resolved") {
    return `resolved by ${item.resolved_by ?? "someone"}`;
  }
  return item.state;
}

export function requestFacts(item: RequestLike): RequestFact[] {
  const facts: RequestFact[] = [];
  const push = (label: string, value: string) => {
    if (value) {
      facts.push({ label, value });
    }
  };

  push("Contact", requestContact(item));
  push("Service", item.service_name ?? "");
  push("Client", clientLabel(item.returning_client));
  push("Practitioner", practitionerLabel(item.practitioner));
  push("Concern", item.concern ?? "");
  if (askedForATime(item)) {
    push("Preferred", item.preferred_text ?? "");
  }
  facts.push({ label: "Promised by", value: formatDateTime(item.due_at) });
  facts.push({ label: "State", value: requestStateLabel(item) });

  return facts;
}

/**
 * The toolbar's search, over exactly what the card shows: its number, the
 * sentence, the caller, the service and the concern. Nothing hidden is
 * searchable, so a card that comes back always explains why it did.
 */
export function matchesRequest(item: RequestLike, query: string): boolean {
  const needle = query.trim().toLowerCase().replace(/^#/, "");
  if (needle === "") {
    return true;
  }
  return [
    String(item.id),
    requestSummary(item),
    requestContact(item),
    item.service_name ?? "",
    item.concern ?? "",
    item.practitioner ?? "",
  ]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

export type RequestSort = "newest" | "oldest" | "due";

export const REQUEST_SORTS: { value: RequestSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "due", label: "Promised soonest" },
];

/** A copy, sorted; the caller's array is never reordered under it. */
export function sortRequests<T extends RequestLike>(
  items: T[],
  sort: RequestSort,
): T[] {
  const when = (value: string) => Date.parse(value) || 0;
  return [...items].sort((a, b) => {
    if (sort === "due") {
      return when(a.due_at) - when(b.due_at);
    }
    const difference = when(a.created_at) - when(b.created_at);
    return sort === "oldest" ? difference : -difference;
  });
}
