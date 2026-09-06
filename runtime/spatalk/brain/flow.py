"""The runtime owns the request conversation (slot engine design, 2026-09-05).

`Slots` is what the runtime knows about the open request. `next_step` is the fixed order.
`step_question` is the script the caller hears next. Nothing here talks to a model, a
database or a phone: the drivers do, with what these functions return.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pydantic import BaseModel, Field

from spatalk.brain.ports import ItemDraft
from spatalk.brain.requests import ContactInfo, PreferredWindow
from spatalk.brain.resolve import (
    first_name_of,
    match_practitioner,
    match_service,
    normalise_phone,
    sounds_like,
    spoken_digits,
    typed_digits,
)
from spatalk.brain.tools import REQUEST_KINDS, always_tools, slot_tool
from spatalk.tenants.schema import TenantConfig

Flow = Literal[
    "new_booking", "callback", "reschedule", "cancel", "question", "training_enquiry", "clinical"
]
NAME_REQUIRED_FLOWS = ("new_booking", "callback", "reschedule", "cancel", "question", "clinical")
BOOKING_LIKE = ("new_booking", "callback")


class Step(str, Enum):
    QA = "qa"
    RETURNING = "returning"
    OFFERS = "offers"
    PRACTITIONER = "practitioner"
    SERVICE = "service"
    NAME = "name"
    PHONE = "phone"
    WINDOW = "window"
    TEAM_NOTE = "team_note"
    ROUTE = "route"
    COMPLETE = "complete"


class Pending(BaseModel, frozen=True):
    """A confirmation the caller owes an answer to before the slot can be filled."""

    kind: Literal["match", "which", "name_staff", "phone", "not_service", "offers", "route"]
    slot: str
    value: str | None = None
    candidates: tuple[str, ...] = ()


class Slots(BaseModel, frozen=True):
    """What the runtime knows about the open request. Every value is a closed one."""

    flow: Flow | None = None
    returning_client: bool | None = None
    offers_done: bool = False
    practitioner: str | None = None
    service_id: str | None = None
    first_name: str | None = None
    phone: str | None = None
    phone_confirmed: bool = False
    preferred_window: PreferredWindow | None = None
    team_note_asked: bool = False
    pending: Pending | None = None
    misses: dict[str, int] = Field(default_factory=dict)
    ended_flow: bool = False

    def with_(self, **changes) -> Slots:
        return self.model_copy(update=changes)

    def miss(self, slot: str) -> Slots:
        misses = dict(self.misses)
        misses[slot] = misses.get(slot, 0) + 1
        return self.with_(misses=misses)


def _phone_needed(slots: Slots, channel: str) -> bool:
    if channel == "sms":
        return False
    return not (slots.phone and slots.phone_confirmed)


def next_step(slots: Slots, cfg: TenantConfig, channel: str) -> Step:
    """The fixed order (slot engine design, §4). A step already answered is skipped."""
    if slots.flow is None or slots.ended_flow:
        return Step.QA
    if slots.flow in BOOKING_LIKE:
        if slots.returning_client is None:
            return Step.RETURNING
        if slots.returning_client is False and not slots.offers_done:
            return Step.OFFERS
        if slots.returning_client:
            if slots.practitioner is None:
                return Step.PRACTITIONER
            if slots.service_id is None:
                return Step.SERVICE
        else:
            if slots.service_id is None:
                return Step.SERVICE
            if slots.practitioner is None:
                return Step.PRACTITIONER
    if not slots.first_name:
        return Step.NAME
    if _phone_needed(slots, channel):
        return Step.PHONE
    if slots.flow in ("new_booking", "callback", "reschedule") and slots.preferred_window is None:
        return Step.WINDOW
    if slots.flow in BOOKING_LIKE and not slots.team_note_asked:
        return Step.TEAM_NOTE
    if slots.flow == "new_booking" and cfg.sms_from_number and channel == "voice":
        return Step.ROUTE
    return Step.COMPLETE


def _consultation_name(cfg: TenantConfig) -> str:
    consult = next((s for s in cfg.services if s.category == "consultation"), None)
    return f"a {consult.name.lower()}" if consult else "the team can help you pick when they call"


def _service_name(cfg: TenantConfig, service_id: str) -> str:
    s = cfg.service(service_id)
    return s.name if s else service_id


def _initialled(a: str, b: str) -> tuple[str, str]:
    """'Helen' and 'Amanda' when the first names differ; 'Amanda C.' and 'Amanda K.' when not."""
    fa, fb = first_name_of(a), first_name_of(b)
    if fa.lower() != fb.lower():
        return fa, fb
    return f"{fa} {a.split()[-1][0]}.", f"{fb} {b.split()[-1][0]}."


def step_question(
    step: Step, slots: Slots, cfg: TenantConfig, channel: str
) -> tuple[str, dict] | None:
    """The `scripts` key the caller hears next, with its fills; None at QA and COMPLETE."""
    p = slots.pending
    if p is not None:
        if p.kind == "match":
            label = first_name_of(p.value or "") if p.slot == "practitioner" else _service_name(cfg, p.value or "")
            return "confirm_match", {"value": label}
        if p.kind == "which":
            a, b = p.candidates[:2]
            if p.slot == "practitioner":
                a, b = _initialled(a, b)
            else:
                a, b = _service_name(cfg, a), _service_name(cfg, b)
            return "confirm_which", {"first": a, "second": b}
        if p.kind == "name_staff":
            return "confirm_name_staff", {"name": p.value}
        if p.kind == "phone":
            digits = spoken_digits(p.value or "") if channel == "voice" else typed_digits(p.value or "")
            return "confirm_phone", {"digits": digits}
        if p.kind == "not_service":
            return "practitioner_not_service", {
                "practitioner": first_name_of(p.value or ""),
                "service": _service_name(cfg, slots.service_id or ""),
            }
        if p.kind == "offers":
            return "ask_service_kind", {"consultation": _consultation_name(cfg)}
        if p.kind == "route":
            return "ask_route", {}
    if step == Step.RETURNING:
        return "ask_returning", {}
    if step == Step.OFFERS:
        return "ask_offers", {}
    if step == Step.PRACTITIONER:
        key = "ask_practitioner_again" if slots.misses.get("practitioner") else "ask_practitioner"
        return key, {}
    if step == Step.SERVICE:
        if slots.misses.get("service"):
            return "ask_service_again", {}
        fresh_client = slots.returning_client is False and slots.offers_done
        return ("ask_after_offers" if fresh_client else "ask_service"), {}
    if step == Step.NAME:
        return ("ask_name_again" if slots.misses.get("name") else "ask_name"), {}
    if step == Step.PHONE:
        same = bool(slots.phone) and not slots.misses.get("phone")
        return ("ask_phone_same" if same else "ask_phone"), {}
    if step == Step.WINDOW:
        return "ask_window", {}
    if step == Step.TEAM_NOTE:
        return "ask_team_note", {}
    if step == Step.ROUTE:
        return "ask_route", {}
    return None


# The slot tool each step offers. PHONE and COMPLETE are decided in `step_tools` itself.
STEP_TOOL = {
    Step.RETURNING: "answer",
    Step.OFFERS: "answer",
    Step.PRACTITIONER: "choose_practitioner",
    Step.SERVICE: "choose_service",
    Step.NAME: "give_name",
    Step.WINDOW: "choose_window",
    Step.TEAM_NOTE: "answer",
    Step.ROUTE: "answer",
}


def step_tools(
    step: Step, slots: Slots, cfg: TenantConfig, channel: str, transfer_enabled: bool = False
) -> list[FunctionSchema]:
    """The tools the model may call at this step: the step's own slot tool, `answer` while a
    confirmation is pending, `change_answer` once a flow is open, and the always-on tools.
    `file_request` and `send_link` exist only where every required slot is filled (§3.1)."""
    tools: list[FunctionSchema] = []
    if step == Step.QA:
        tools.append(slot_tool("start_request", cfg))
    elif step == Step.PHONE:
        if slots.pending is not None and slots.pending.kind == "phone":
            tools.append(slot_tool("answer", cfg))
        elif slots.phone and not slots.misses.get("phone"):
            tools.append(slot_tool("answer", cfg))   # "is the number you're calling from ok?"
        else:
            tools.append(slot_tool("give_phone", cfg))
    elif step == Step.COMPLETE:
        tools.append(slot_tool("file_request", cfg))
    else:
        tools.append(slot_tool(STEP_TOOL[step], cfg))
        if slots.pending is not None and STEP_TOOL[step] != "answer":
            tools.append(slot_tool("answer", cfg))
        if step == Step.NAME and slots.flow == "clinical" and not slots.misses.get("name"):
            tools.append(slot_tool("answer", cfg))  # the clinical offer is answered yes/no first
        if step == Step.ROUTE:
            tools.append(slot_tool("file_request", cfg))
            if cfg.sms_from_number and slots.phone and slots.phone_confirmed:
                tools.append(slot_tool("send_link", cfg))
    if step != Step.QA:
        tools.append(slot_tool("change_answer", cfg))
    return tools + always_tools(cfg, transfer_enabled)


class Applied(BaseModel, frozen=True):
    """What one tool call did: the new record, the fixed lines to say, and the acts the
    driver must perform (file, send the link, end). `ignored` means the model called a tool
    the step did not offer: nothing is said and nothing is written."""

    slots: Slots
    say: tuple[tuple[str, dict], ...] = ()
    file: bool = False
    send_link: bool = False
    end: bool = False
    ignored: bool = False
    # True when the model's own words are the content of the turn (the offers, two or three
    # options from the facts) rather than a one-line acknowledgement.
    model_speaks: bool = False


def _tool_allowed(name: str, step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> bool:
    return name in {t.name for t in step_tools(step, slots, cfg, channel, transfer_enabled=True)}


def _open(kind: str, previous: Slots, channel: str, caller_phone: str | None) -> Slots:
    """A new flow keeps what the conversation already knows about the person, never about
    the request: the name and number asked once are not asked twice; a second request
    still gets its own treatment and practitioner."""
    on_sms = channel == "sms" and bool(caller_phone)
    return Slots(
        flow=kind,
        returning_client=previous.returning_client,
        first_name=previous.first_name,
        # The caller id is the number to confirm ("is this the best one?"); on SMS the
        # sender's number needs no confirming.
        phone=previous.phone or caller_phone,
        phone_confirmed=previous.phone_confirmed or on_sms,
    )


open_flow = _open


def _finalize(applied: Applied, cfg: TenantConfig, channel: str) -> Applied:
    """The record files itself the moment the last required slot lands (the route step of a
    booking on a call with an SMS number is the one question asked before it)."""
    s = applied.slots
    if applied.ignored or applied.file or applied.send_link or applied.end:
        return applied
    if s.flow is None or s.ended_flow or s.pending is not None:
        return applied
    if next_step(s, cfg, channel) == Step.COMPLETE:
        done = s.with_(ended_flow=True)
        if s.flow == "new_booking" and channel != "voice":
            # Text channels show the booking link in the conversation itself (Task B4); a
            # call without an SMS number files a callback instead.
            return applied.model_copy(update={"slots": done, "send_link": True})
        return applied.model_copy(update={"slots": done, "file": True})
    return applied


def apply(
    slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> Applied:
    """Move the record on one tool call. Answers land only in the open slot (§3.3)."""
    return _finalize(_apply(slots, name, args, cfg, channel, caller_phone), cfg, channel)


def _apply(
    slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> Applied:
    step = next_step(slots, cfg, channel)
    if name in ("escalate", "end_conversation", "transfer_to_human"):
        return Applied(slots=slots, end=(name == "end_conversation"))
    if not _tool_allowed(name, step, slots, cfg, channel):
        return Applied(slots=slots, ignored=True)
    args = args or {}
    if name == "start_request":
        kind = args.get("kind")
        if kind not in REQUEST_KINDS:
            return Applied(slots=slots, ignored=True)
        return Applied(slots=_open(kind, slots, channel, caller_phone))
    if name == "change_answer":
        return Applied(slots=_reopen(slots, args.get("slot", "")))
    if name == "answer":
        return _answer(slots, step, args.get("value", "unsure"), cfg, channel, caller_phone)
    if name == "choose_practitioner":
        return _practitioner(slots, args.get("said", ""), cfg)
    if name == "choose_service":
        return _service(slots, args.get("said", ""), cfg)
    if name == "give_name":
        return _name(slots, args.get("first_name", ""), cfg)
    if name == "give_phone":
        return _phone(slots, args.get("digits", ""), caller_phone, channel)
    if name == "choose_window":
        window = PreferredWindow(
            date=args.get("date") or "any", part_of_day=args.get("part_of_day") or "any"
        )
        return Applied(slots=slots.with_(preferred_window=window))
    if name == "file_request":
        return Applied(slots=slots.with_(ended_flow=True), file=True)
    if name == "send_link":
        return Applied(slots=slots.with_(ended_flow=True), send_link=True)
    return Applied(slots=slots, ignored=True)


def _reopen(slots: Slots, slot: str) -> Slots:
    clear = {
        "returning_client": {"returning_client": None},
        "practitioner": {"practitioner": None},
        "service": {"service_id": None},
        "name": {"first_name": None},
        "phone": {"phone": None, "phone_confirmed": False},
        "window": {"preferred_window": None},
    }.get(slot)
    if clear is None:
        return slots
    misses = {k: v for k, v in slots.misses.items() if k != slot}
    return slots.with_(pending=None, misses=misses, **clear)


def _answer(
    slots: Slots, step: Step, value: str, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> Applied:
    yes = value == "yes"
    p = slots.pending
    if p is not None:
        if p.kind == "which":
            # Answered by naming one of the two, through the slot tool, not yes/no.
            return Applied(slots=slots, ignored=True)
        if p.kind == "match":
            if yes:
                field = "practitioner" if p.slot == "practitioner" else "service_id"
                return _after_slot(slots.with_(pending=None, **{field: p.value}), cfg)
            return Applied(slots=slots.with_(pending=None).miss(p.slot))
        if p.kind == "name_staff":
            if yes:
                return Applied(slots=slots.with_(pending=None, first_name=p.value))
            return Applied(slots=slots.with_(pending=None).miss("name"))
        if p.kind == "phone":
            if yes:
                return Applied(slots=slots.with_(pending=None, phone=p.value, phone_confirmed=True))
            return _phone_miss(slots.with_(pending=None), caller_phone, channel)
        if p.kind == "not_service":
            if yes:
                names = [first_name_of(m.name) for m in cfg.team_for_service(slots.service_id or "")]
                fills = {"names": _join(names[:3]), "service": _service_name(cfg, slots.service_id or "")}
                return Applied(slots=slots.with_(pending=None), say=(("practitioner_suggest", fills),))
            return Applied(slots=slots.with_(pending=None), say=(("practitioner_else", {}),))
        if p.kind == "offers":
            # yes = hear options (the model names two or three from the facts); no = the consultation
            if yes:
                return Applied(slots=slots.with_(pending=None), model_speaks=True)
            consult = next((s for s in cfg.services if s.category == "consultation"), None)
            if consult is None:
                return Applied(slots=slots.with_(pending=None))
            return _after_slot(slots.with_(pending=None, service_id=consult.id), cfg)
        if p.kind == "route":
            return _route(slots.with_(pending=None), yes, cfg)
    if slots.flow == "clinical" and slots.first_name is None and step == Step.NAME:
        # The clinical offer: yes goes on to the name, no closes with nothing filed.
        if yes:
            return Applied(slots=slots)
        return Applied(slots=slots.with_(ended_flow=True), say=(("clinical_declined", {}),))
    if step == Step.RETURNING:
        return Applied(slots=slots.with_(returning_client=yes))
    if step == Step.OFFERS:
        # After the offers the treatment question is "What did you have in mind?" (the
        # SERVICE step asks it that way for a new client); the model's recital comes whole.
        return Applied(slots=slots.with_(offers_done=True), model_speaks=yes)
    if step == Step.PHONE:
        if yes and slots.phone:
            return Applied(slots=slots.with_(phone_confirmed=True))
        return Applied(slots=slots.miss("phone"))
    if step == Step.TEAM_NOTE:
        return Applied(slots=slots.with_(team_note_asked=True))
    if step == Step.ROUTE:
        return _route(slots, yes, cfg)
    return Applied(slots=slots, ignored=True)


def _route(slots: Slots, yes: bool, cfg: TenantConfig) -> Applied:
    if yes and cfg.sms_from_number and slots.phone_confirmed:
        return Applied(slots=slots.with_(ended_flow=True), send_link=True)
    return Applied(slots=slots.with_(ended_flow=True), file=True)


def _after_slot(slots: Slots, cfg: TenantConfig) -> Applied:
    """A practitioner and a service both known: check the pairing (§4.3)."""
    if slots.practitioner and slots.practitioner != "any" and slots.service_id:
        if not cfg.member_does(slots.practitioner, slots.service_id):
            pending = Pending(kind="not_service", slot="practitioner", value=slots.practitioner)
            return Applied(slots=slots.with_(practitioner=None, pending=pending))
    return Applied(slots=slots)


def _practitioner(slots: Slots, said: str, cfg: TenantConfig) -> Applied:
    m = match_practitioner(said, cfg)
    if m.kind == "exact":
        return _after_slot(slots.with_(pending=None, practitioner=m.value), cfg)
    if m.kind == "confirm":
        pending = Pending(kind="match", slot="practitioner", value=m.value)
        return Applied(slots=slots.with_(pending=pending))
    if m.kind == "which":
        pending = Pending(kind="which", slot="practitioner", candidates=m.candidates)
        return Applied(slots=slots.with_(pending=pending))
    missed = slots.with_(pending=None).miss("practitioner")
    if missed.misses["practitioner"] >= 2:
        return Applied(slots=missed.with_(practitioner="any"), say=(("practitioner_any", {}),))
    return Applied(slots=missed)


def _service(slots: Slots, said: str, cfg: TenantConfig) -> Applied:
    m = match_service(said, cfg)
    if m.kind == "exact":
        return _after_slot(slots.with_(pending=None, service_id=m.value), cfg)
    if m.kind == "confirm":
        pending = Pending(kind="match", slot="service", value=m.value)
        return Applied(slots=slots.with_(pending=pending))
    if m.kind == "which":
        pending = Pending(kind="which", slot="service", candidates=m.candidates)
        return Applied(slots=slots.with_(pending=pending))
    if m.kind == "kind":
        pending = Pending(kind="offers", slot="service_kind", value=m.value)
        return Applied(slots=slots.with_(pending=pending))
    missed = slots.with_(pending=None).miss("service")
    if missed.misses["service"] >= 2:
        pending = Pending(kind="offers", slot="service_kind")
        return Applied(slots=missed.with_(pending=pending))
    return Applied(slots=missed)


def _name(slots: Slots, first_name: str, cfg: TenantConfig) -> Applied:
    name = " ".join((first_name or "").split())[:80]
    if not name or not any(ch.isalpha() for ch in name):
        missed = slots.miss("name")
        if missed.misses["name"] >= 2:
            return Applied(slots=missed.with_(ended_flow=True), say=(("no_name", {}),))
        return Applied(slots=missed)
    name = name.split()[0].capitalize()
    staff = slots.practitioner and slots.practitioner != "any"
    if staff and sounds_like(name, first_name_of(slots.practitioner or "")):
        pending = Pending(kind="name_staff", slot="name", value=name)
        return Applied(slots=slots.with_(pending=pending))
    return Applied(slots=slots.with_(first_name=name, pending=None))


def _phone(slots: Slots, digits: str, caller_phone: str | None, channel: str) -> Applied:
    e164 = normalise_phone(digits)
    if e164 is None:
        return _phone_miss(slots, caller_phone, channel)
    return Applied(slots=slots.with_(pending=Pending(kind="phone", slot="phone", value=e164)))


def _phone_miss(slots: Slots, caller_phone: str | None, channel: str) -> Applied:
    missed = slots.miss("phone")
    if missed.misses["phone"] >= 2 and channel == "voice" and caller_phone:
        fallback = missed.with_(phone=caller_phone, phone_confirmed=True)
        return Applied(slots=fallback, say=(("phone_fallback", {}),))
    return Applied(slots=missed)


def _join(names: list[str]) -> str:
    if not names:
        return "Someone on the team"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


# --- the item, and the model's one-paragraph brief per step -------------------------------

STEP_MARKER = "[step]"

ITEM_TYPE = {
    "new_booking": "new_booking",
    "callback": "callback",
    "reschedule": "reschedule",
    "cancel": "cancel",
    "question": "question",
    "training_enquiry": "training_enquiry",
    "clinical": "escalation_clinical",
}


def draft_from(slots: Slots, cfg: TenantConfig, health_context: bool = False) -> ItemDraft:
    """The only way a request becomes an item: from the record, never from a tool argument."""
    return ItemDraft(
        type=ITEM_TYPE[slots.flow or "question"],
        urgency="urgent" if slots.flow == "clinical" else "normal",
        service_id=slots.service_id,
        contact=ContactInfo(name=slots.first_name, phone=slots.phone),
        preferred_window=slots.preferred_window or PreferredWindow(),
        health_context=health_context,
        returning_client=slots.returning_client,
        practitioner=slots.practitioner,
        concern=None,
    )


def step_message(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> str:
    """One short brief for the model: what is known, what is open, which tool takes the
    answer. It replaces the booking bullets that used to sit in the middle of the prompt."""
    if step == Step.QA:
        return (
            f"{STEP_MARKER} No request is open. Answer questions from the facts. The moment the "
            "caller wants to book, be called back, reschedule, cancel, ask about a course, or "
            "asks something the facts do not answer, call start_request with no words of your "
            "own: never say that you will start, file or pass on a request, and never ask for "
            "their name or number; the system asks the questions from there."
        )
    known = []
    if slots.returning_client is not None:
        known.append("returning client" if slots.returning_client else "new client")
    if slots.practitioner:
        who = "anyone" if slots.practitioner == "any" else slots.practitioner
        known.append("wants to see " + who)
    if slots.service_id:
        known.append("treatment " + _service_name(cfg, slots.service_id))
    if slots.first_name:
        known.append("first name " + slots.first_name)
    known_text = ("Known: " + ", ".join(known) + ". ") if known else ""
    if step == Step.COMPLETE:
        return (
            f"{STEP_MARKER} {known_text}Everything is collected. Call file_request now. "
            "Say nothing about the result."
        )
    if step == Step.OFFERS and slots.pending is None:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether they would like to hear "
            "the new-client offers. If they say yes, say the new-client offers listed in the facts, "
            "in the order the facts list them, in one breath, and call answer with yes. If they "
            "say no, call answer with no and say nothing else. Never invent an offer."
        )
    if slots.pending is not None and slots.pending.kind == "offers":
        return (
            f"{STEP_MARKER} {known_text}The caller named a kind of treatment. The system just "
            "offered two or three options or a consultation. If they want options, name two or "
            "three from the facts with prices in one breath and then wait; when they choose one, "
            "call choose_service."
        )
    offered = {t.name for t in step_tools(step, slots, cfg, channel)}
    order = (
        "answer", "choose_practitioner", "choose_service", "give_name", "give_phone",
        "choose_window", "file_request",
    )
    tool = next((n for n in order if n in offered), "answer")
    return (
        f"{STEP_MARKER} {known_text}The system has just asked the caller a question. Put their "
        f"answer in {tool}. Do not ask a question yourself; one short acknowledgement at most."
    )
