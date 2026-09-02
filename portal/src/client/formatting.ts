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
  escalation_clinical: "Clinical",
  escalation_complaint: "Complaint",
  escalation_payment: "Payment",
  escalation_legal: "Legal",
  escalation_unsure: "Unsure",
};

export function itemTypeLabel(type: string): string {
  return ITEM_TYPES[type] ?? type.replace(/_/g, " ");
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
