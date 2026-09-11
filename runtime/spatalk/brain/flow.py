"""The runtime owns the request conversation (slot engine design, 2026-09-05).

`Slots` is what the runtime knows about the open request. `next_step` is the fixed order.
`step_question` is the script the caller hears next. Nothing here talks to a model, a
database or a phone: the drivers do, with what these functions return.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pydantic import BaseModel, Field

from spatalk.brain.ports import ItemDraft
from spatalk.brain.requests import ContactInfo, PreferredWindow
from spatalk.brain.resolve import (
    first_name_of,
    is_question,
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
    # The clinical flow opens with a yes/no offer; only after yes is the name asked.
    offer_accepted: bool = False
    pending: Pending | None = None
    misses: dict[str, int] = Field(default_factory=dict)
    ended_flow: bool = False
    # A side question the caller asked mid-step, and the step it interrupted. One frame, not
    # a stack: the stack is phase B, and one frame is all `answer_question` needs (memo §2,
    # LIT R6). It is a closed value — a `Step` — and it never reaches an item: `draft_from`
    # reads named slots and this is not one of them.
    digression: Step | None = None

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
    elif step == Step.NAME and slots.flow == "clinical" and not slots.offer_accepted:
        tools.append(slot_tool("answer", cfg))  # the clinical offer is answered yes/no first
    else:
        tools.append(slot_tool(STEP_TOOL[step], cfg))
        if slots.pending is not None and STEP_TOOL[step] != "answer":
            tools.append(slot_tool("answer", cfg))
        if step == Step.ROUTE:
            tools.append(slot_tool("file_request", cfg))
            if cfg.sms_from_number and slots.phone and slots.phone_confirmed:
                tools.append(slot_tool("send_link", cfg))
    if step != Step.QA:
        tools.append(slot_tool("change_answer", cfg))
    return tools + always_tools(cfg, transfer_enabled)


class Missing(BaseModel, frozen=True):
    """What the record is waiting on, and what will take the answer.

    `description` is an instruction to a model, never a sentence the caller hears, which is
    why it lives in code (non-negotiable 3 is about what is spoken). `choices` is given only
    where the closed set is genuinely short: never the practitioner or the treatment, whose
    lists are already in the static prompt and would be bought again on every turn.
    """

    datum: str
    description: str
    choices: tuple[str, ...] = ()
    tool: str


class Readiness(BaseModel, frozen=True):
    """The one source for both the step brief and a rejection (OSS §8.2; Parlant).

    A rejection that named different choices from the brief would be a second policy, which
    is the thing the runtime exists not to have.
    """

    step: Step
    known: tuple[str, ...]
    missing: Missing | None
    tools: tuple[str, ...]


class Rejection(BaseModel, frozen=True):
    """Why a tool call was refused, in closed values the model can act on.

    Parlant's `ToolInsights` / `MissingToolData` shape: the reason, the tool, what the record
    is waiting on, and what may be called instead. It never holds a caller's or a model's
    words, it is never rendered to a channel, and it is never written to an item or the
    record — `rejection_text` turns it into the function response and nothing else reads it.
    """

    reason: Literal["not_offered", "premature", "bad_value", "already_yours"]
    tool: str
    offered: tuple[str, ...]
    missing: Missing | None = None
    detail: Literal[
        "question_shaped", "unknown_kind", "empty_slot", "not_a_choice",
        "needs_yes_or_no", "name_it_instead",
    ] | None = None


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
    # Why a refused call was refused, in words the model can act on. It goes back as the
    # function response and nowhere else: never rendered, never spoken to the caller, never
    # written to an item or the record (2026-09-11 memo, decision 6). Structured since the
    # model-words memo — a reason code, what the record is waiting on, and the legal calls —
    # and rendered by `rejection_text` on the way out.
    rejection: Rejection | None = None
    # True when the model's own words are the content of the turn (the offers, two or three
    # options from the facts) rather than a one-line acknowledgement.
    model_speaks: bool = False


# What the model is told when a call is refused. Never caller-facing, so not tenant config:
# these sentences are read by a model, not spoken by the assistant (non-negotiable 3 covers
# the wording the caller hears, which is still scripts.yaml and only scripts.yaml). They are
# the narrow fix's five `ANSWER_THE_QUESTION` sentences, split into the reason and the way
# the value was wrong, so `rejection_text` can add what the record is waiting on underneath.
_DETAIL_TEXT = {
    "question_shaped": "what you passed was a question, not an answer",
    "unknown_kind": "that is not one of the kinds of request the system handles",
    "empty_slot": "there is nothing recorded in that slot to change",
    "not_a_choice": "that is not one of the values the system accepts",
    "needs_yes_or_no": "that question takes a yes or a no",
    "name_it_instead": "that question is answered by naming one of the two, not by yes or no",
}


def rejection_text(r: Rejection) -> str:
    """What the model is told, as the tool's result. Never spoken, never sent, never stored."""
    lines = []
    if r.reason == "premature":
        lines.append(f"{r.tool} is not available yet. Nothing was filed and nothing was recorded.")
    elif r.reason == "already_yours":
        lines.append(f"{r.tool} is already open: you have the turn. Answer them in your own words now.")
    elif r.reason == "bad_value":
        lines.append(f"{r.tool} did not take that: {_DETAIL_TEXT[r.detail]}. Nothing was recorded.")
    else:
        lines.append(f"{r.tool} is not available at this point. Nothing was recorded.")
    if r.missing is not None:
        want = f"The system is waiting on {r.missing.description}"
        if r.missing.choices:
            want += " — one of: " + ", ".join(r.missing.choices)
        lines.append(want + f". Put their answer in {r.missing.tool}.")
    lines.append("You may call: " + ", ".join(r.offered) + ".")
    return " ".join(lines)


def _reject(
    reason: str, tool: str, slots: Slots, cfg: TenantConfig, channel: str, detail: str | None = None
) -> Applied:
    """Every refused path goes through here, so the brief and the rejection agree by
    construction. `ignored` keeps its meaning and its truth value, so `tool_ignored`,
    `tool_refusal`, `run_tool` and `_finalize` are untouched."""
    report = readiness(slots, cfg, channel)
    return Applied(
        slots=slots,
        ignored=True,
        rejection=Rejection(
            reason=reason, tool=tool, offered=report.tools, missing=report.missing, detail=detail,
        ),
    )


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
    if applied.ignored or applied.file or applied.send_link:
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


def tool_refusal(
    slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> tuple[bool, str | None]:
    """Would this call change nothing and say nothing, and why? `apply` is pure, so this just
    asks it. The reason is for the model to read as the tool result; it is never spoken."""
    a = apply(slots, name, args, cfg, channel, caller_phone)
    return a.ignored, (rejection_text(a.rejection) if a.rejection is not None else None)


def tool_rejection(
    slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> Rejection | None:
    """The structured sibling of `tool_refusal`: why this call would be refused, or None."""
    return apply(slots, name, args or {}, cfg, channel, caller_phone).rejection


def tool_ignored(
    slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> bool:
    """Would this call change nothing and say nothing? The boolean half of `tool_refusal`."""
    return tool_refusal(slots, name, args, cfg, channel, caller_phone)[0]


def pop_digression(slots: Slots, cfg: TenantConfig, channel: str) -> Slots:
    """Close the side question. The frame is dropped whether or not the open step is still
    the one it interrupted: a caller who answered the question inside their own aside has
    already moved the record, and `next_step` skips a filled slot, so there is nothing to
    resume (RavenClaw's completion criterion rather than Rasa's re-ask)."""
    return slots if slots.digression is None else slots.with_(digression=None)


def _apply(
    slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None
) -> Applied:
    step = next_step(slots, cfg, channel)
    if name == "end_conversation":
        # A caller who says "no, that's all" at the last optional question is done with the
        # request, not walking away from it: the record files itself, then the goodbye.
        if slots.flow and not slots.ended_flow and slots.pending is None and step == Step.TEAM_NOTE:
            return Applied(slots=slots.with_(team_note_asked=True), end=True)
        return Applied(slots=slots, end=True)
    if name in ("escalate", "transfer_to_human"):
        return Applied(slots=slots)
    if name == "answer_question":
        # The 01:40 call's missing path (memo §2). Writes nothing, says nothing: it records
        # the step it interrupted and hands the turn to the model, which answers from the
        # facts and then asks the open question again in its own words.
        if slots.digression is not None:
            return _reject("already_yours", name, slots, cfg, channel)
        return Applied(slots=slots.with_(digression=step), model_speaks=True)
    if not _tool_allowed(name, step, slots, cfg, channel):
        # `file_request` and `send_link` are absent only because the record is not ready, and
        # the model needs that difference: "not available" says try something else, "not yet,
        # the record still needs X" says what to do.
        reason = "premature" if name in ("file_request", "send_link") else "not_offered"
        return _reject(reason, name, slots, cfg, channel)
    args = args or {}
    if name == "start_request":
        kind = args.get("kind")
        if kind not in REQUEST_KINDS:
            return _reject("bad_value", name, slots, cfg, channel, detail="unknown_kind")
        return Applied(slots=_open(kind, slots, channel, caller_phone))
    if name == "change_answer":
        slot = args.get("slot", "")
        if not _slot_filled(slots, slot):
            # Nothing is stored there, so there is nothing to change. The caller asking "what
            # was the $50 one you said?" reads as a correction to the model (founder call
            # 2026-09-10 20:54:29), and the step question came back for the second time in a
            # row with no answer in front of it. An ignored call hands the turn to the model.
            return _reject("bad_value", name, slots, cfg, channel, detail="empty_slot")
        return Applied(slots=_reopen(slots, slot))
    if name == "answer":
        # The schema's enum is the whole vocabulary of this tool. Anything else is the
        # caller's question wearing an answer's clothes, and "no" is not a safe reading of it.
        value = args.get("value", "unsure")
        if value not in ("yes", "no", "unsure"):
            return _reject("bad_value", name, slots, cfg, channel, detail="not_a_choice")
        return _answer(slots, step, value, cfg, channel, caller_phone)
    if name == "choose_practitioner":
        said = args.get("said", "")
        if is_question(said):
            return _reject("bad_value", name, slots, cfg, channel, detail="question_shaped")
        return _practitioner(slots, said, cfg)
    if name == "choose_service":
        # A question is not an answer (founder call 2026-09-11 01:41:26, where "Sorry, what
        # was the- what was the facial one again?" filled the slot and moved the step on).
        said = args.get("said", "")
        if is_question(said):
            return _reject("bad_value", name, slots, cfg, channel, detail="question_shaped")
        return _service(slots, said, cfg)
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
    # A name that passed `_tool_allowed` and is handled nowhere above: not reachable from
    # the tool list the model is given, and refused in words rather than in silence anyway.
    return _reject("not_offered", name, slots, cfg, channel)


_SLOT_FIELDS = {
    "returning_client": ("returning_client",),
    "practitioner": ("practitioner",),
    "service": ("service_id",),
    "name": ("first_name",),
    "phone": ("phone",),
    "window": ("preferred_window",),
}


def _slot_filled(slots: Slots, slot: str) -> bool:
    """Does that slot hold an answer? An unknown slot name holds nothing."""
    return any(getattr(slots, f) is not None for f in _SLOT_FIELDS.get(slot, ()))


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
            return _reject("bad_value", "answer", slots, cfg, channel, detail="name_it_instead")
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
    if slots.flow == "clinical" and not slots.offer_accepted and step == Step.NAME:
        # The clinical offer: yes goes on to the name, no closes with nothing filed.
        if yes:
            return Applied(slots=slots.with_(offer_accepted=True))
        return Applied(slots=slots.with_(ended_flow=True), say=(("clinical_declined", {}),))
    if step == Step.RETURNING:
        return Applied(slots=slots.with_(returning_client=yes))
    if step == Step.OFFERS:
        # The offers are the tenant's own words from the knowledge file, spoken by the runtime
        # (neither model recited them reliably); the SERVICE step then asks "What did you
        # have in mind?" for a new client.
        done = slots.with_(offers_done=True)
        offers = offers_text(cfg)
        if yes and offers:
            return Applied(slots=done, say=(("offers_intro", {"offers": offers}),))
        return Applied(slots=done)
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
    name = _clean_name((first_name or "")[:80])
    if name is None:
        missed = slots.miss("name")
        if missed.misses["name"] >= 2:
            return Applied(slots=missed.with_(ended_flow=True), say=(("no_name", {}),))
        return Applied(slots=missed)
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


_OFFERS_HEADING = re.compile(r"^##\s+new-client offers\s*$", re.I | re.M)


def offers_text(cfg: TenantConfig) -> str:
    """The new-client offers as one spoken sentence: the first sentence of each bullet under
    the knowledge file's "New-client offers" heading, in the order the file lists them."""
    m = _OFFERS_HEADING.search(cfg.knowledge or "")
    if not m:
        return ""
    section = cfg.knowledge[m.end():]
    nxt = re.search(r"^##\s", section, re.M)
    section = section[: nxt.start()] if nxt else section
    items = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        first = re.split(r"(?<=[.!?])\s+", line[2:].strip(), maxsplit=1)[0].rstrip(".")
        if first:
            items.append(first[0].lower() + first[1:])
    if len(items) > 1:
        return ", ".join(items[:-1]) + " and " + items[-1]
    return items[0] if items else ""


def _clean_name(text: str) -> str | None:
    """A first name from what the model passed, or None when it is not one: 'yes please',
    'actually make it the hydrabrasion' and the like are answers to other questions."""
    words = re.sub(r"[^A-Za-z' -]+", " ", text or "").split()
    lead = ("it's", "its", "this", "is", "my", "name", "i'm", "im", "call", "me", "the", "name's")
    while words and words[0].lower() in lead:
        words.pop(0)
    if not words or len(words) > 3:
        return None
    first = words[0]
    if first.lower() in NOT_A_NAME or len(first) < 2:
        return None
    return first.capitalize()


NOT_A_NAME = frozenset({
    "yes", "yeah", "yep", "yup", "no", "nope", "nah", "sure", "ok", "okay", "please", "actually",
    "um", "uh", "hi", "hello", "hey", "thanks", "thank", "what", "why", "how", "when", "can",
    "make", "change", "book", "cancel", "reschedule", "sorry", "wait", "hold", "just",
})


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


# What the record is waiting on at each step, and the closed values it will take. These are
# instructions to a model, never sentences the caller hears, which is why they are code and
# not `scripts.yaml` (non-negotiable 3 is about what is spoken). `choices` is given only
# where the closed set is genuinely short — never for the practitioner or the treatment,
# whose lists are already in the static prompt and would be bought again on every turn.
_MISSING: dict[Step, tuple[str, str, tuple[str, ...]]] = {
    Step.RETURNING: ("returning_client", "whether they have been in to the clinic before", ("yes", "no")),
    Step.OFFERS: ("offers", "whether they would like to hear the new-client offers", ("yes", "no")),
    Step.PRACTITIONER: ("practitioner", "who they would like to see: a name from the team in the facts, or anyone", ()),
    Step.SERVICE: ("service", "which treatment they want, from the SERVICES list above", ()),
    Step.NAME: ("name", "their first name", ()),
    Step.PHONE: ("phone", "the best number to reach them on", ()),
    Step.WINDOW: ("window", "which day or part of the day suits them", ("morning", "afternoon", "evening", "any")),
    Step.TEAM_NOTE: ("team_note", "whether there is anything the team should know before they call", ("yes", "no")),
    Step.ROUTE: ("route", "whether to text them the booking link or have the team call them", ("the link", "a call")),
}


# The order the tool that takes the answer is looked for in. The step's own slot tool is
# always in there; `answer` wins wherever a yes or no is what the record wants.
_ANSWER_TOOL_ORDER = (
    "answer", "choose_practitioner", "choose_service", "give_name", "give_phone",
    "choose_window", "file_request",
)


def _answer_tool(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> str:
    """The tool the caller's answer to the open question goes in."""
    offered = {t.name for t in step_tools(step, slots, cfg, channel)}
    return next((n for n in _ANSWER_TOOL_ORDER if n in offered), "answer")


def _known(slots: Slots, cfg: TenantConfig) -> list[str]:
    """What the record already holds, in the model's reading order."""
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
    return known


def _missing(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> Missing | None:
    """What the record is waiting on at this step, or None when it is waiting on nothing.

    Four of these `_MISSING` cannot express, and they are exactly the four the model got
    wrong on the founder's calls: an open confirmation, a choice between two candidates, the
    "is the number you're calling from the best one" question, and the clinical offer that
    comes before the name.
    """
    p = slots.pending
    if p is not None:
        if p.kind == "which":
            # A choice between two is answered by naming one, through the slot tool.
            tool = "choose_practitioner" if p.slot == "practitioner" else "choose_service"
            return Missing(
                datum=p.slot,
                description="which of the two the system has just read back they meant",
                tool=tool,
            )
        return Missing(
            datum="confirmation",
            description="a yes or no to the confirmation the system has just read back",
            choices=("yes", "no"),
            tool="answer",
        )
    if step not in _MISSING:
        return None
    if step == Step.PHONE and slots.phone and not slots.misses.get("phone"):
        return Missing(
            datum="phone",
            description="whether the number they are calling from is the best one to reach them on",
            choices=("yes", "no"),
            tool="answer",
        )
    if step == Step.NAME and slots.flow == "clinical" and not slots.offer_accepted:
        return Missing(
            datum="clinical_offer",
            description="whether they would like the clinical team to reach out to them",
            choices=("yes", "no"),
            tool="answer",
        )
    datum, description, choices = _MISSING[step]
    return Missing(
        datum=datum,
        description=description,
        choices=choices,
        tool=_answer_tool(step, slots, cfg, channel),
    )


def readiness(slots: Slots, cfg: TenantConfig, channel: str) -> Readiness:
    """What is known, what is missing with its legal choices, and what may be called.

    `tools` is built with the transfer off, because this function cannot know whether the
    clinic is staffed right now: under-naming a tool the model already has in its own list
    is safe, and naming one that would ring an empty room is not.
    """
    step = next_step(slots, cfg, channel)
    return Readiness(
        step=step,
        known=tuple(_known(slots, cfg)),
        missing=_missing(step, slots, cfg, channel),
        tools=tuple(t.name for t in step_tools(step, slots, cfg, channel)),
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
    report = readiness(slots, cfg, channel)
    known_text = ("Known: " + ", ".join(report.known) + ". ") if report.known else ""
    if step == Step.COMPLETE:
        return (
            f"{STEP_MARKER} {known_text}Everything is collected. Call file_request now. "
            "Say nothing about the result."
        )
    tool = report.missing.tool if report.missing else _answer_tool(step, slots, cfg, channel)
    if slots.digression is not None:
        # The caller asked something else, and `answer_question` recorded the step it
        # interrupted. It comes ahead of the step's own briefs because answering the caller
        # is the turn's job; the open question follows it, in the model's words.
        wanted = (
            report.missing.description
            if report.missing
            else "nothing: everything the request needs is on the record"
        )
        return (
            f"{STEP_MARKER} {known_text}They asked something else. Answer it from the facts "
            "in one or two sentences, then ask again, in your own words, for "
            f"{wanted}, and put their answer in "
            f"{tool}. Do not call answer_question again."
        )
    if step == Step.OFFERS and slots.pending is None:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether they would like to hear "
            "the new-client offers. Call answer with yes or no and say nothing else: the system "
            "reads the offers itself."
        )
    if step == Step.PHONE and slots.phone and not slots.misses.get("phone") and slots.pending is None:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether the number they are calling "
            "from is the best one. 'Yes' or 'that's fine' is answer with yes; 'no', 'use a different "
            "one' or a new number is answer with no (the system asks for the digits next). Do not "
            "call change_answer for this."
        )
    if step == Step.TEAM_NOTE:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether there is anything for the "
            "team to know. 'No', 'nothing' or 'that's all' is the answer to that question: call "
            "answer with no. Do not end the conversation; the system files the request next."
        )
    if slots.pending is not None and slots.pending.kind == "offers":
        return (
            f"{STEP_MARKER} {known_text}The caller named a kind of treatment. The system just "
            "offered two or three options or a consultation. If they want options, name two or "
            "three from the facts with prices in one breath and then wait; when they choose one, "
            "call choose_service."
        )
    return (
        f"{STEP_MARKER} {known_text}The system has just asked the caller a question. Put their "
        f"answer in {tool}. If instead they change an earlier answer, call change_answer with "
        "that slot. Do not ask a question yourself; one short acknowledgement at most."
    )
