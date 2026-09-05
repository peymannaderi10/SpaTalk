/**
 * How runtime values are put into words on the client pages.
 *
 * Browser-safe on purpose: the pages import it, and so do its tests. Nothing
 * here invents an outcome — a band is what the runtime recorded, and a request
 * that is late is called late, never "handled".
 */

/** `conversations.band`: 1 handled end to end, 2 captured for a human, 3 straight to a human. */
export function bandLabel(band: number | null | undefined): string {
  switch (band) {
    case 1:
      return "handled";
    case 2:
      return "sent to team";
    case 3:
      return "to a person";
    default:
      return "in progress";
  }
}

const ITEM_TYPES: Record<string, string> = {
  callback: "Callback",
  new_booking: "New booking",
  question: "Question",
  training_enquiry: "Training enquiry",
  reschedule: "Reschedule",
  cancel: "Cancellation",
  send_link: "Send a link",
  escalation_human_request: "Asked for a person",
  escalation_emergency: "Emergency",
  escalation_clinical: "Clinical",
  escalation_complaint: "Complaint",
  escalation_payment: "Payment",
  escalation_legal: "Legal",
  escalation_unsure: "Unsure",
};

export function itemTypeLabel(type: string): string {
  return ITEM_TYPES[type] ?? type.replace(/_/g, " ");
}

/**
 * `items.returning_client`: the caller was asked whether they had been in
 * before. Null is not "new" — it is that the question never came up, and a card
 * that says nothing is the honest reading of it.
 */
export function clientLabel(returning: boolean | null | undefined): string {
  if (returning === true) {
    return "Returning client";
  }
  if (returning === false) {
    return "New client";
  }
  return "";
}

/**
 * `items.practitioner`: a name from the tenant's team, or the literal `"any"`
 * the runtime stores when the caller was asked and had no one in mind. Null
 * means nobody was asked about, so the card shows no line at all.
 */
export function practitionerLabel(value: string | null | undefined): string {
  const name = (value ?? "").trim();
  if (name === "") {
    return "";
  }
  return name.toLowerCase() === "any" ? "No preference" : name;
}

const CHANNELS: Record<string, string> = {
  voice: "Phone",
  sms: "Text",
  chat: "Web chat",
  instagram: "Instagram",
  messenger: "Messenger",
};

export function channelLabel(channel: string): string {
  return CHANNELS[channel] ?? channel;
}

const CONTROLLERS: Record<string, string> = {
  ai: "The assistant",
  human: "A person",
  closed: "Closed",
};

/**
 * `conversations.controller`: who is answering this conversation now. `human`
 * is the one the front desk cares about — a person took it over and the
 * assistant has stopped replying — which is what the list's filter is for.
 * An unfamiliar value is shown as it came, never guessed at.
 */
export function controllerLabel(controller: string | null | undefined): string {
  const value = (controller ?? "").trim();
  if (value === "") {
    return "—";
  }
  return CONTROLLERS[value] ?? value;
}

export function isOverdue(
  item: { state: string; due_at: string },
  now: number = Date.now(),
): boolean {
  return (
    (item.state === "open" || item.state === "acknowledged") &&
    Date.parse(item.due_at) < now
  );
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "—";
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
}

/** Canadian dollars, because the rates table the runtime prices with is in CAD. */
export function formatCad(amount: number): string {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2,
  }).format(amount);
}

export function formatMinutes(minutes: number): string {
  return minutes.toFixed(1);
}

/** How a blocked or muted number reads in the settings table (plan F). */
export function blockStateLabel(
  until: string | null | undefined,
  now: number = Date.now(),
): string {
  if (until == null) return "Blocked";
  const ends = Date.parse(until);
  if (Number.isNaN(ends)) return "Muted";
  return ends > now ? `Muted until ${formatDateTime(until)}` : "Mute ended";
}

/**
 * The label the notes are read under. The runtime drafts the notes from the
 * transcript, so the reader has to see that they were drafted before they see
 * the sentences — and the wording of that is the tenant's, in
 * `scripts.notes_label`, not the portal's.
 *
 * The default is the runtime's own default, used only until the tenant's
 * configuration has loaded (or when a runtime that predates call notes answers
 * without the script). It is the one place the portal spells the words out.
 */
export const DEFAULT_NOTES_LABEL = "AI notes, drafted from the transcript";

export function notesLabel(config?: unknown): string {
  const scripts = (config as { scripts?: unknown } | null | undefined)?.scripts;
  const label = (scripts as { notes_label?: unknown } | null | undefined)
    ?.notes_label;
  return typeof label === "string" && label.trim() !== ""
    ? label.trim()
    : DEFAULT_NOTES_LABEL;
}
