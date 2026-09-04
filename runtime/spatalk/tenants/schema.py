from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# One entry of `TenantConfig.concerns`, bounded by the width of `items.concern`.
Concern = Annotated[str, Field(max_length=40)]

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


class TeamMember(BaseModel, frozen=True):
    """One person a caller may ask for by name (lead context plan, Task L1).

    The list is the closed vocabulary behind `items.practitioner`: the model may only
    return a name that is in it, or "any" for no preference. A role is written where the
    clinic states one publicly; it is never spoken as a claim about qualifications.

    `name` is bounded by the width of `items.practitioner` (varchar(80)) so a config that
    could not be written to an item is refused at import, rather than losing a request
    mid-call to a truncation error.
    """

    name: str = Field(max_length=80)
    role: str = ""


# The cosmetic concern taxonomy behind `items.concern`. It is deliberately not medical:
# anything about a symptom, a reaction or a condition still routes to the clinical script
# and lives only in the transcript (CLAUDE.md non-negotiables 1 and 2).
DEFAULT_CONCERNS: tuple[str, ...] = (
    "pigmentation",
    "acne",
    "ageing",
    "dryness",
    "hair removal",
    "hair loss",
    "body contouring",
    "skin tightening",
    "tattoo removal",
    "glow",
    "other",
)


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

    # The clinical script for text channels. The voice wording says "hang up and call 911",
    # which makes no sense in a chat window (QA gate C). Same promise, same emergency sentence.
    clinical_text: str = (
        "That's a question for our clinical team, and I don't want to guess. I've sent them "
        "an urgent request, and someone will contact you as soon as possible. If this is an "
        "emergency, please call 911 now."
    )

    # --- call notes (call-notes plan, Task N1) ---
    # Neither line is ever spoken or sent to a customer; both are read by staff only. The
    # label heads the notes block on the portal card, the staff email and the Slack post, so
    # nobody mistakes a drafted paragraph for something the caller dictated. The health line
    # replaces any sentence of the draft that touches a condition, a medication or a
    # symptom: the notes may say what a caller wants, never what they have.
    notes_health_line: str = (
        "Caller mentioned a health matter; read the transcript before calling."
    )
    notes_label: str = "AI notes, drafted from the transcript"
    # Spoken once when the model provider fails after its retries (founder calls
    # 2026-09-03 21:03 and 21:05); asks for a repeat, claims nothing.
    model_unavailable: str = (
        "Sorry, I'm having a little trouble on my end. Could you say that once more?"
    )

    # The one text a sender may get while the tenant's assistant is paused on SMS (plan F).
    # It names no reply time: nothing is generated until the local day rolls over.
    sms_paused: str = (
        "Thanks for texting {name}. The assistant is paused right now. A member of the team "
        "will read your message, or you can call {phone}."
    )

    # Optional: spoken by the system the instant a phone turn is handed to the model, rotating,
    # so the caller never waits in silence for the first token (voice only; never in a
    # transcript). Empty by default: the founder found "Okay" and "One moment" grating, and
    # the model's own first words are the acknowledgement instead.
    fillers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_completion_words(self):
        for key, value in self.__dict__.items():
            low = str(value).lower()
            hits = [b for b in BANNED_SCRIPT_WORDS if b in low]
            if hits:
                raise ValueError(f"scripts.{key} contains completion wording ({hits})")
        if "911" not in self.clinical or "911" not in self.clinical_text:
            raise ValueError("scripts.clinical must keep the emergency sentence")
        return self


class SocialSettings(BaseModel, frozen=True):
    comment_mode: Literal["off", "keyword", "all"] = "keyword"
    comment_keywords: list[str] = Field(default_factory=list)
    public_reply_enabled: bool = False


class SmsGuard(BaseModel, frozen=True):
    """Bounds on what one number, or one tenant's day, may cost on SMS (plan F).

    A sender past `burst_limit` texts in `burst_window_minutes`, or past `daily_limit` in a
    local day, is muted for `mute_hours`. A tenant whose assistant has sent
    `tenant_daily_replies` texts in a local day is paused until the day rolls over. Every
    suppressed text is still stored; only the reply and the model call are withheld.
    """

    burst_limit: int = Field(default=12, ge=1)
    burst_window_minutes: int = Field(default=10, ge=1)
    daily_limit: int = Field(default=40, ge=1)
    mute_hours: int = Field(default=24, ge=1)
    tenant_daily_replies: int = Field(default=400, ge=1)


class Lexicons(BaseModel, frozen=True):
    human_request: list[str] = Field(default_factory=list)
    clinical: list[str] = Field(default_factory=list)        # symptoms, reactions -> band 3
    health_context: list[str] = Field(default_factory=list)  # conditions, meds -> flag only
    complaint: list[str] = Field(default_factory=list)
    payment: list[str] = Field(default_factory=list)
    completion: list[str] = Field(default_factory=list)


class Destination(BaseModel, frozen=True):
    # --- sms staff delivery (plan S) ---
    # "sms" is the kind the founder chose on 2026-09-02: a tracked item lands on the owner's
    # own mobile from the tenant's Telnyx number. "whatsapp" stays here, dormant.
    kind: Literal["slack", "email", "webhook", "whatsapp", "sms"]
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
        # --- sms staff delivery (plan S) ---
        # An owner's mobile is personal data, so it is named, never written (S1).
        if self.kind == "sms" and not self.address_env:
            raise ValueError("sms destination needs address_env")
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
    # --- call notes (call-notes plan, Task N1) ---
    # Whether the post-conversation job drafts notes from the transcript. Off means no model
    # call and no `conversations.notes`; the assistant still asks whether there is anything
    # the team should know, because the answer is in the transcript either way.
    call_notes: bool = True
    hours: dict[str, list[tuple[str, str]]]
    holidays: list[date] = Field(default_factory=list)
    voice_numbers: list[str] = Field(default_factory=list)
    sms_from_number: str | None = None
    transfer_number: str | None = None    # staffed back-line for live transfer (E10)
    booking_url_default: str
    persona: Persona = Persona()
    # --- lead context (plan L, Task L1) ---
    # The two closed vocabularies a request may draw on: who the caller may ask for, and
    # what they may say they are coming in for. Both are config, never prompt text.
    team: list[TeamMember] = Field(default_factory=list)
    # Bounded by the width of `items.concern` (varchar(40)), for the same reason as a name.
    concerns: list[Concern] = Field(default_factory=lambda: list(DEFAULT_CONCERNS))
    services: list[Service]
    knowledge: str
    scripts: Scripts
    lexicons: Lexicons = Lexicons()
    escalation: Escalation
    delivery: Delivery
    social: SocialSettings = SocialSettings()
    sms_guard: SmsGuard = SmsGuard()

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

    @model_validator(mode="after")
    def _concerns_are_cosmetic(self):
        """Health stays out of the fields, enforced rather than trusted (lead context plan).

        `concerns` is a cosmetic taxonomy: a tenant who adds "rosacea" or "pregnancy" turns
        a condition into a closed value the ledger will happily write to `items.concern`,
        where no retention job treats it as clinical detail. Anything medical belongs in the
        clinical script and the transcript, so a medical concern is refused at import.

        `spatalk.brain.rules` imports this module, so the lexicons are imported here rather
        than at module level.
        """
        from spatalk.brain.rules import DEFAULT_LEXICONS, HEALTH_CONTEXT_DEFAULT

        medical = {w.lower() for w in DEFAULT_LEXICONS["clinical"] + HEALTH_CONTEXT_DEFAULT}
        for concern in self.concerns:
            lowered = concern.lower()
            offending = {lowered, *lowered.split()} & medical
            if offending:
                raise ValueError(
                    f"concern {concern!r} is a clinical or health-context term "
                    f"({sorted(offending)[0]!r}); concerns are cosmetic only"
                )
        return self

    def service(self, service_id: str) -> Service | None:
        return next((s for s in self.services if s.id == service_id), None)

    def practitioner_names(self) -> list[str]:
        """The values `items.practitioner` may hold: "any" first, then the team by name."""
        return ["any"] + [m.name for m in self.team]
