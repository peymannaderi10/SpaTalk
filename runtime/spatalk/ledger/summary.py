"""One tracked item as one readable sentence (lead context plan, Task L1).

Founder decision 2026-09-03: a request that says "Wants to book" is not a lead. Every
channel that shows an item — the owner's SMS, the email, the Slack card, the portal's
request card — shows the same sentence, so there is exactly one place where the wording
lives and it cannot drift between them.

The sentence is composed here, from the item's own columns and fixed labels, and never by
a model (CLAUDE.md non-negotiable 1). It is derived rather than stored, so it cannot drift
from the fields either: change a field, and the next render says the new thing.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from spatalk.tenants.schema import TenantConfig

# The long labels the ledger has always used to name an item's type to staff. Imported from
# the delivery module would be a cycle (delivery reads this file), so the map lives here and
# delivery imports it.
TYPE_LABELS: dict[str, str] = {
    "callback": "Callback requested",
    "new_booking": "Wants to book",
    "question": "Question for the team",
    "training_enquiry": "Training course enquiry",
    "reschedule": "Reschedule request",
    "cancel": "Cancellation request",
    "send_link": "Send booking link",
    "escalation_human_request": "Asked for a person",
    "escalation_emergency": "EMERGENCY",
    "escalation_clinical": "CLINICAL question",
    "escalation_complaint": "COMPLAINT",
    "escalation_payment": "Payment question",
    "escalation_legal": "Legal question",
    "escalation_unsure": "Assistant was unsure",
}

# The short label that opens the summary sentence. Where a type has no short form, the long
# label opens the sentence and is not repeated after the colon.
SUMMARY_LABELS: dict[str, str] = {
    "callback": "Callback",
    "new_booking": "New booking",
    "question": "Question",
    "training_enquiry": "Training enquiry",
    "reschedule": "Reschedule",
    "cancel": "Cancellation",
    "send_link": "Send booking link",
}

# The only item types whose summary ends in a callback time: the ones where a caller was
# asked when to be reached.
CALLBACK_TYPES: tuple[str, ...] = ("new_booking", "callback")

DAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

PART_OF_DAY_PLURAL: dict[str, str] = {
    "morning": "mornings",
    "afternoon": "afternoons",
    "evening": "evenings",
}

MONTH_NAMES: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class HasItemFields(Protocol):
    """What the summary reads: `runtime.items` columns, and nothing else."""

    type: str
    service_id: str | None
    preferred_window: dict[str, Any] | None
    returning_client: bool | None
    practitioner: str | None
    concern: str | None


def type_label(item_type: str) -> str:
    """The long staff-facing label for an item type; the raw type if it has none."""
    return TYPE_LABELS.get(item_type, item_type)


def preferred_text(window: dict[str, Any] | None) -> str:
    """A preferred window in words: "any day", "Thursday 24 September, afternoons", "mornings".

    A caller who names a real day is telling the team when to reach them, so the day they
    named has to survive: an ISO date renders as the weekday, the day and the month
    ("Thursday 24 September"), because a bare "Thursday" three weeks out reads as this
    Thursday. A weekday the caller named without a date is only a weekday, and renders as
    one. Never "any any", never a bare ISO date, and never a date the model mangled: a
    `date` that does not parse is treated as no date at all.
    """
    window = window or {}
    raw_date = window.get("date") or "any"
    part = window.get("part_of_day") or "any"
    day, dated = "", False
    if raw_date != "any":
        try:
            on = date.fromisoformat(str(raw_date))
        except (TypeError, ValueError):
            # Not a date: the closed vocabulary also allows a weekday the caller named.
            day = next((d for d in DAY_NAMES if d.lower() == str(raw_date).lower()), "")
        else:
            day = f"{DAY_NAMES[on.weekday()]} {on.day} {MONTH_NAMES[on.month - 1]}"
            dated = True
    if day and part != "any":
        # A dated day already reads as a phrase, so the part of day follows a comma.
        plural = PART_OF_DAY_PLURAL.get(part, part)
        return f"{day}, {plural}" if dated else f"{day} {part}"
    if day:
        return day
    if part != "any":
        return PART_OF_DAY_PLURAL.get(part, part)
    return "any day"


def service_name(item: HasItemFields, cfg: TenantConfig) -> str:
    """The catalog name of the item's service, or the type label when there is no service.

    A service id the tenant has since dropped is not a name, so it falls back too: staff
    read words, never ids. Every column is read defensively: a summary is wording, and no
    staff message may fail to send because a row predates a column.
    """
    service_id = getattr(item, "service_id", None)
    if service_id:
        known = cfg.service(service_id)
        if known is not None:
            return known.name
    return type_label(item.type)


def summarize_item(item: HasItemFields, cfg: TenantConfig) -> str:
    """One request as one sentence, from closed fields and fixed labels only.

    For example: "New booking: Mirapeel facial for pigmentation. New client, no
    practitioner preference. Would like to come in Thursday afternoon."
    """
    label = SUMMARY_LABELS.get(item.type, type_label(item.type))
    name = service_name(item, cfg)
    head = label if name == label else f"{label}: {name}"

    concern = getattr(item, "concern", None)
    if concern:
        head += f" for {concern}"

    returning = getattr(item, "returning_client", None)
    if returning is None:
        client = ""
    else:
        client = ". Returning client" if returning else ". New client"

    practitioner = getattr(item, "practitioner", None)
    if practitioner == "any":
        # Only said when a preference was actually asked for, which is what "any" records.
        who = ", no practitioner preference"
    elif practitioner:
        who = f", would like {practitioner}"
    else:
        who = ""

    when = ""
    if item.type in CALLBACK_TYPES:
        when = f". Would like to come in {preferred_text(getattr(item, 'preferred_window', None))}"

    return f"{head}{client}{who}{when}."
