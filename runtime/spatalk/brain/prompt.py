from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from spatalk.brain.hours import BusinessCalendar, _clock
from spatalk.tenants.schema import WEEKDAYS, TenantConfig

# Per-channel length and formatting rules (text-channels plan, Task B2). Voice has its own
# "at most two sentences" rule in the hard rules below.
CHANNEL_RULES = {
    "sms": "Reply in under 300 characters, plain text, no lists.",
    "chat": "Reply in under 500 characters, plain text.",
}

DAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def _hours_text(cfg: TenantConfig) -> str:
    parts = []
    for d in WEEKDAYS:
        spans = cfg.hours.get(d, [])
        parts.append(
            f"{DAY_NAMES[d]}: "
            + (", ".join(f"{s} to {e}" for s, e in spans) if spans else "closed")
        )
    return "; ".join(parts)


def _services_text(cfg: TenantConfig) -> str:
    lines = []
    for s in cfg.services:
        extra = " (consultation first)" if s.consult_required else ""
        desc = f" {s.description}" if s.description else ""
        lines.append(f"- {s.name} [{s.id}]: {s.price_text}{extra}.{desc}")
    return "\n".join(lines)


def build_system_prompt(cfg: TenantConfig, channel: str, now: datetime) -> str:
    cal = BusinessCalendar(cfg)
    local = now.astimezone(ZoneInfo(cfg.timezone))
    status = "open" if cal.is_open(now) else "closed"
    next_open = cal.next_open(now).astimezone(ZoneInfo(cfg.timezone))
    medium = (
        "a phone call; your words are spoken aloud"
        if channel == "voice"
        else "a text conversation"
    )
    channel_rule = CHANNEL_RULES.get(channel, "")
    channel_note = ("\n- " + channel_rule) if channel_rule else ""
    next_open_note = (
        ""
        if status == "open"
        else f' It next opens {next_open.strftime("%A")} at {_clock(next_open)}.'
    )
    return f"""You are {cfg.persona.assistant_name} for {cfg.name}. This is {medium}. Tone: {cfg.persona.tone}.
The AI disclosure has already been given; do not repeat it.

Right now it is {local.strftime('%A')} {_clock(local)} at the clinic, and the clinic is {status}.{next_open_note}

WHAT YOU CAN DO
- Answer questions about services, prices, hours, location and policies from the facts below. If the facts do not cover it, say so and offer to file a question for the team (capture_request, kind question).
- Text the booking link (send_booking_link) when someone wants to book and can self-serve.
- File requests for the team: callbacks, booking help, reschedules and cancellations, training-course enquiries.
- Hand off to a person (escalate) for anything clinical or medical, any reaction or symptom after a treatment, complaints, payment or legal questions, or when the caller asks for a person.

HARD RULES
- You cannot book, reschedule, cancel or confirm anything. Never say "booked", "confirmed", "scheduled", "cancelled" or "all set" about an appointment. When you use a tool, say nothing about the result: the system speaks the result itself.
- Never give medical advice, never discuss symptoms, never take payment details. Use escalate instead.
- If the caller mentions a health condition, medication, pregnancy or a past procedure while asking for something routine, do not ask about it, do not comment on it, and do not advise. Continue with their request; the team will see the context. If they ask whether a treatment is suitable or safe for them, say the team will confirm that, and file it with capture_request (kind question).
- Keep replies to at most two sentences. Ask for the caller's name and best number in one question when you need them.
- When the caller is done, call end_conversation; do not say goodbye yourself.{channel_note}

HOURS: {_hours_text(cfg)}

SERVICES (name [id]: price):
{_services_text(cfg)}

FACTS ABOUT {cfg.name.upper()}
{cfg.knowledge.strip()}
"""
