"""A tenant from a few basics (onboarding roadmap, section 4, row 1).

The five-file bundle stays the only thing the runtime judges. `render_starter` turns the
basics a form or a command line can ask for into the five texts, and whoever calls it
hands them to `config_from_texts`, so a tenant born this way obeys exactly the rules
`spatalk tenant import` enforces and nothing here can drift from them.

The fixed files ship as package data under `spatalk/tenants/starter/`: `scripts.yaml` and
`guard.yaml` are the wording and the lexicons Skincentrix went live with, made generic.
They are copied out byte for byte, never formatted, so the runtime's own placeholders
(`{name}`, `{assistant_name}`, `{service}`, `{phone}`, ...) reach the new tenant untouched
and the renderer fills them at the moment of speaking (CLAUDE.md non-negotiable 3).

`tenant.yaml` is built as a dictionary and dumped, never templated as text, and the only
staff destination it writes beside the owner's email names an environment variable, never
a number (CLAUDE.md non-negotiable 5).
"""

from __future__ import annotations

import re
from importlib import resources
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator

from spatalk.tenants.schema import WEEKDAYS, _valid_hhmm

STARTER = resources.files(__package__) / "starter"

# The files that come out of the package as they are.
FIXED_FILES = ("scripts.yaml", "guard.yaml", "services.yaml")

SLUG = re.compile(r"^[a-z0-9-]{2,40}$")
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}

DEFAULT_ASSISTANT_NAME = "Ava"
DIGEST_TIME_LOCAL = "07:30"

# The SMS guard and social defaults Skincentrix carries, written out so the clinic can
# see and change them (tenant-config.md, `sms_guard` and `social`).
SMS_GUARD = {
    "burst_limit": 12,
    "burst_window_minutes": 10,
    "daily_limit": 40,
    "mute_hours": 24,
    "tenant_daily_replies": 400,
}
SOCIAL = {
    "comment_mode": "keyword",
    "comment_keywords": ["price", "how much", "book", "info", "details"],
    "public_reply_enabled": False,
}


class TenantBasics(BaseModel):
    """What a clinic must be asked for before it can have a front desk at all."""

    id: str = Field(pattern=SLUG.pattern, description="tenant id: lowercase letters, digits, hyphens")
    name: str = Field(min_length=2, max_length=80)
    # Required, no default: every due time is computed in it (CLAUDE.md non-negotiable 8),
    # so a clinic is asked rather than assumed. `spatalk tenant new` defaults the option.
    timezone: str = Field(description="IANA zone, e.g. America/Toronto")
    hours: dict[str, list[tuple[str, str]]] = Field(
        description="mon..sun to [start, end] HH:MM spans; a missing or empty day is closed"
    )
    booking_url: HttpUrl
    public_phone: str = Field(default="", description="the clinic's own number, E.164, or empty")
    owner_name: str = Field(default="", max_length=120)
    owner_email: str
    assistant_name: str = Field(default=DEFAULT_ASSISTANT_NAME, min_length=1, max_length=40)

    @field_validator("name", "owner_name", "assistant_name", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("timezone")
    @classmethod
    def _zone(cls, v: str) -> str:
        v = v.strip()
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {v!r}")
        return v

    @field_validator("hours")
    @classmethod
    def _hours(cls, v):
        for day, spans in v.items():
            if day not in WEEKDAYS:
                raise ValueError(f"unknown weekday {day!r}; use {', '.join(WEEKDAYS)}")
            for start, end in spans:
                if not (_valid_hhmm(start) and _valid_hhmm(end) and start < end):
                    raise ValueError(f"bad hours for {day}: {start}-{end} (HH:MM, start before end)")
        full = {d: [tuple(s) for s in v.get(d, [])] for d in WEEKDAYS}
        if not any(full.values()):
            raise ValueError("hours need at least one open day")
        return full

    @field_validator("public_phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if v and not E164.match(v):
            raise ValueError("public_phone must be E.164 (+1 and the digits) or empty")
        return v

    @field_validator("owner_email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL.match(v):
            raise ValueError("owner_email is not an email address")
        return v

    def staff_sms_env(self) -> str:
        """`<ID_UPPER>_STAFF_SMS`: the variable the staff mobile is read from, never written."""
        return re.sub(r"[^A-Z0-9]", "_", self.id.upper()) + "_STAFF_SMS"

    def escalation_owner_name(self) -> str:
        return self.owner_name or f"{self.name} front desk"


def _fixed_text(name: str) -> str:
    """One shipped file, bytes decoded and nothing else: no newline translation, no format."""
    return (STARTER / name).read_bytes().decode("utf-8")


def hours_in_words(hours: dict[str, list[tuple[str, str]]]) -> str:
    """`Monday closed. Tuesday 10:00 to 18:00. ...`, for the knowledge file."""
    parts = []
    for day in WEEKDAYS:
        spans = hours.get(day, [])
        if not spans:
            parts.append(f"{DAY_NAMES[day]} closed")
        else:
            parts.append(
                f"{DAY_NAMES[day]} " + " and ".join(f"{start} to {end}" for start, end in spans)
            )
    return ". ".join(parts) + "."


def _knowledge(basics: TenantBasics) -> str:
    lines = [f"# {basics.name}", "", "## Location, contact, hours", ""]
    if basics.public_phone:
        lines.append(f"- Phone: {basics.public_phone}.")
    lines.append(f"- Hours: {hours_in_words(basics.hours)}")
    lines.append(
        f"- Appointment-based clinic. Book online at {basics.booking_url} or through the team."
    )
    lines.append("")
    return "\n".join(lines) + "\n" + _fixed_text("knowledge.md")


def tenant_document(basics: TenantBasics) -> dict:
    """The `tenant.yaml` document as data; `render_starter` dumps it."""
    return {
        "id": basics.id,
        "name": basics.name,
        "public_phone": basics.public_phone,
        "timezone": basics.timezone,
        "hours": {day: [list(span) for span in basics.hours[day]] for day in WEEKDAYS},
        "holidays": [],
        "voice_numbers": [],
        "sms_from_number": None,
        "transfer_number": None,
        "booking_url_default": str(basics.booking_url),
        "persona": {"assistant_name": basics.assistant_name},
        "escalation": {
            "owner_name": basics.escalation_owner_name(),
            "owner_email": basics.owner_email,
            "urgent_minutes": 15,
            "standard_business_hours": 3,
        },
        "delivery": {
            "destinations": [
                {"kind": "email", "address": basics.owner_email},
                {"kind": "sms", "address_env": basics.staff_sms_env()},
            ],
            "digest_time_local": DIGEST_TIME_LOCAL,
        },
        "sms_guard": dict(SMS_GUARD),
        "social": {**SOCIAL, "comment_keywords": list(SOCIAL["comment_keywords"])},
    }


def render_starter(basics: TenantBasics) -> dict[str, str]:
    """The five bundle files, filename to text, for `config_from_texts` or for disk."""
    texts = {name: _fixed_text(name) for name in FIXED_FILES}
    texts["knowledge.md"] = _knowledge(basics)
    texts["tenant.yaml"] = yaml.safe_dump(
        tenant_document(basics), sort_keys=False, allow_unicode=True
    )
    return texts
