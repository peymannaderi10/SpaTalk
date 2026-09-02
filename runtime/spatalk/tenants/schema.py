from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# docs/reference/tenant-config.md: no script may contain "booked", "confirmed" or "scheduled".
BANNED_SCRIPT_WORDS: tuple[str, ...] = ("booked", "confirmed", "scheduled")


def _valid_hhmm(s: str) -> bool:
    if len(s) != 5 or s[2] != ":":
        return False
    h, m = s.split(":")
    return h.isdigit() and m.isdigit() and 0 <= int(h) <= 23 and 0 <= int(m) <= 59


class Service(BaseModel, frozen=True):
    id: str
    name: str
    category: str
    price_text: str = ""            # "from $99", "$150 per session", "free"
    duration_minutes: int | None = None
    booking_url: str
    consult_required: bool = False
    clinical: bool = False
    description: str = ""


class Persona(BaseModel, frozen=True):
    assistant_name: str = "the assistant"
    tone: str = "warm, brief, plain-spoken"
    max_sentences_per_turn: int = 2


class Scripts(BaseModel, frozen=True):
    """Every fixed sentence the system can say.

    Required keys have no default. See docs/reference/tenant-config.md.
    """

    disclosure: str
    clinical: str
    human_request: str
    complaint: str
    payment: str
    captured: str
    link_sent: str
    link_captured: str
    cannot_complete: str
    goodbye: str
    after_hours_note: str = "The clinic is closed right now."
    link_shown: str = "Here is the booking link for {service}: {url}"
    refuse_no_contact: str = (
        "I'd need a phone number or email to send that. Could you give me one?"
    )
    refuse_unknown_service: str = (
        "I don't have that treatment on the list. "
        "Could you tell me a bit more about what you're looking for?"
    )
    refuse_out_of_scope: str = (
        "That's not something I can help with from here. "
        "The clinic can, at {phone} during opening hours."
    )
    refuse_unavailable: str = (
        "I'm having trouble saving that right now, so please don't count on me for it. "
        "Please call the clinic directly at {phone}."
    )
    followup: str = (
        "Just checking in from {name}: still want a hand with that? "
        "Reply here anytime, or book online: {booking_url}"
    )
    missed_call_text: str = (
        "Hi, this is {name}'s assistant. You just called us. "
        "Reply here and I can help, or book online: {booking_url}"
    )
    offline_reply: str = (
        "Thanks for texting {name}. We'll reply shortly. To book now: {booking_url}"
    )
    chat_greeting: str = (
        "Hi, I'm {name}'s AI assistant. I can answer questions about services, prices and hours, "
        "or pass a request to the team. How can I help?"
    )
    optout_confirm: str = (
        "You've been unsubscribed from {name} texts. Reply START to opt back in."
    )
    help_text: str = (
        "{name}: reply with your question and the assistant will help, or call {phone}. "
        "Reply STOP to unsubscribe."
    )
    takeover_notice: str = "A member of the {name} team has joined this conversation."
    comment_public_reply: str = "Thanks! Check your DMs."
    dm_greeting: str = "Hi, this is {name}'s assistant."
    loop_guard: str = (
        "This line is answered by the clinic's assistant and cannot transfer to itself. "
        "Please call back from another number."
    )
    failover: str = (
        "We can't take your call right now. "
        "Please text us at {sms_number} or book online at {booking_url}."
    )
    transferring: str = "One moment, I'll connect you to the team."

    @model_validator(mode="after")
    def _no_completion_words(self):
        for key, value in self.__dict__.items():
            low = str(value).lower()
            hits = [b for b in BANNED_SCRIPT_WORDS if b in low]
            if hits:
                raise ValueError(f"scripts.{key} contains completion wording ({hits})")
        if "911" not in self.clinical:
            raise ValueError("scripts.clinical must keep the emergency sentence")
        return self


class SocialSettings(BaseModel, frozen=True):
    comment_mode: Literal["off", "keyword", "all"] = "keyword"
    comment_keywords: list[str] = Field(default_factory=list)
    public_reply_enabled: bool = False


class Lexicons(BaseModel, frozen=True):
    human_request: list[str] = Field(default_factory=list)
    clinical: list[str] = Field(default_factory=list)        # symptoms, reactions -> band 3
    health_context: list[str] = Field(default_factory=list)  # conditions, meds -> flag only
    complaint: list[str] = Field(default_factory=list)
    payment: list[str] = Field(default_factory=list)
    completion: list[str] = Field(default_factory=list)


class Destination(BaseModel, frozen=True):
    kind: Literal["slack", "email", "webhook", "whatsapp"]
    webhook_env: str | None = None      # slack / webhook: env var NAME holding the URL
    address: str | None = None          # email
    # --- whatsapp (plan W) ---
    # A staff WhatsApp number is a personal phone number, so it is never written into a
    # bundle: the destination names the environment variable that holds the E.164 value,
    # exactly as a Slack destination names the variable holding its webhook URL. Email may
    # use it too, for a mailbox a tenant would rather not commit.
    address_env: str | None = None
    channel_id: str | None = None       # slack channel id, used with a bot token (B5)
    urgent_only: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.kind in ("slack", "webhook") and not self.webhook_env:
            raise ValueError(f"{self.kind} destination needs webhook_env")
        if self.kind == "email" and not (self.address or self.address_env):
            raise ValueError("email destination needs address or address_env")
        if self.kind == "whatsapp" and not self.address_env:
            raise ValueError("whatsapp destination needs address_env")
        return self


class Delivery(BaseModel, frozen=True):
    destinations: list[Destination]
    digest_time_local: str = "07:30"
    staff_phone_numbers: list[str] = Field(default_factory=list)

    @field_validator("digest_time_local")
    @classmethod
    def _hhmm(cls, v):
        if not _valid_hhmm(v):
            raise ValueError("digest_time_local must be HH:MM")
        return v


class Escalation(BaseModel, frozen=True):
    owner_name: str
    owner_email: str
    owner_phone: str | None = None
    urgent_minutes: int = 15
    standard_business_hours: int = 3
    after_hours_clinical_contact: str | None = None


class TenantConfig(BaseModel, frozen=True):
    id: str
    name: str
    public_phone: str = ""            # spoken when the assistant cannot help; never a promise
    timezone: str = "America/Toronto"
    jurisdiction: str = "CA-ON"
    integration_tier: Literal["A", "B", "C"] = "C"
    fulfilment: str = "tier_c"
    retention_days: int = 30
    recording_enabled: bool = False
    hours: dict[str, list[tuple[str, str]]]
    holidays: list[date] = Field(default_factory=list)
    voice_numbers: list[str] = Field(default_factory=list)
    sms_from_number: str | None = None
    transfer_number: str | None = None    # staffed back-line for live transfer (E10)
    booking_url_default: str
    persona: Persona = Persona()
    services: list[Service]
    knowledge: str
    scripts: Scripts
    lexicons: Lexicons = Lexicons()
    escalation: Escalation
    delivery: Delivery
    social: SocialSettings = SocialSettings()

    @field_validator("hours")
    @classmethod
    def _hours(cls, v):
        for day, spans in v.items():
            if day not in WEEKDAYS:
                raise ValueError(f"unknown weekday {day}")
            for start, end in spans:
                if not (_valid_hhmm(start) and _valid_hhmm(end) and start < end):
                    raise ValueError(f"bad hours for {day}: {start}-{end}")
        return {d: [tuple(s) for s in v.get(d, [])] for d in WEEKDAYS}

    def service(self, service_id: str) -> Service | None:
        return next((s for s in self.services if s.id == service_id), None)
