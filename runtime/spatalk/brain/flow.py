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

from spatalk.brain.breath import item_lexicon
from spatalk.brain.ports import ItemDraft
from spatalk.brain.requests import ContactInfo, PreferredWindow
from spatalk.brain.rules import GateDecision, is_cosmetic_concern, rules_gate
from spatalk.brain.resolve import (
    Match,
    spelled_name,
    first_name_of,
    is_question,
    match_practitioner,
    match_service,
    normalise_phone,
    sounds_like,
    spoken_digits,
    turn_asked,
    typed_digits,
)
from spatalk.brain.tools import REQUEST_KINDS, always_tools, slot_tool
from spatalk.tenants.schema import TenantConfig

Flow = Literal[
    "new_booking", "callback", "reschedule", "cancel", "question", "training_enquiry", "clinical"
]
NAME_REQUIRED_FLOWS = ("new_booking", "callback", "reschedule", "cancel", "question", "clinical")
BOOKING_LIKE = ("new_booking", "callback")

# On the founder's call of 2026-09-11 15:55:02 the model rewrote "How much does it cost?" into
# a treatment name it had inferred two turns earlier, so `is_question` — which runs on the
# ARGUMENT — saw no question at all and the price went unanswered for three turns. `apply`
# therefore also looks at what the caller actually said, not only at the argument. The debt
# follows the WRITE rather than the name of the tool that made it: nothing distinguishes the
# name, window or returning step from the treatment step once the detector reads the caller's
# own transcript, and the same question is lost at each of them.


class Step(str, Enum):
    QA = "qa"
    RETURNING = "returning"
    OFFERS = "offers"
    CLINICAL_OFFER = "clinical_offer"
    PRACTITIONER = "practitioner"
    SERVICE = "service"
    NAME = "name"
    PHONE = "phone"
    WINDOW = "window"
    TEAM_NOTE = "team_note"
    LINK_OFFER = "link_offer"
    COMPLETE = "complete"


class Pending(BaseModel, frozen=True):
    """A confirmation the caller owes an answer to before the slot can be filled."""

    kind: Literal["match", "which", "name_staff", "phone", "not_service", "offers"]
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
    name_spelled: bool = False
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
    # Two more facts about the record rather than values on it, behind the same fence as
    # `digression`: `draft_from` never reads either, so neither can reach an item.
    # An item exists on the ledger for this record; it can never be written twice.
    filed: bool = False
    # The post-filing link offer has been put and answered.
    link_offered: bool = False
    # The request that was in progress when this one interrupted it (slot engine spec line
    # 65: the record in progress is kept, not thrown away). One frame, not a stack: `_open`
    # parks only when the previous flow is open and of a different kind, so nesting is bounded
    # at depth 1 and a persisted record cannot grow without limit. `close_flow` hands it back.
    # It is behind the same fence as `digression`: `draft_from` never reads it.
    parked: "Slots | None" = None

    def with_(self, **changes) -> Slots:
        return self.model_copy(update=changes)

    def miss(self, slot: str) -> Slots:
        misses = dict(self.misses)
        misses[slot] = misses.get(slot, 0) + 1
        return self.with_(misses=misses)


# The self-reference resolves here rather than at first validation, because the module is
# under `from __future__ import annotations` and `text/service.py` validates a stored row.
Slots.model_rebuild()


def _phone_needed(slots: Slots, channel: str) -> bool:
    if channel == "sms":
        return False
    return not (slots.phone and slots.phone_confirmed)


def link_offer_open(slots: Slots, cfg: TenantConfig, channel: str) -> bool:
    """The booking is already filed and the team already has it; the only thing left is
    whether to text the caller the link as well."""
    return (
        cfg.offer_booking_link
        and channel == "voice"
        and slots.flow == "new_booking"
        and slots.filed
        and not slots.link_offered
        and not slots.ended_flow
        and bool(cfg.sms_from_number)
        and bool(slots.service_id)
        and bool(slots.phone)
        and slots.phone_confirmed
    )


def next_step(slots: Slots, cfg: TenantConfig, channel: str) -> Step:
    """The fixed order (slot engine design, §4). A step already answered is skipped."""
    if slots.flow is None or slots.ended_flow:
        return Step.QA
    # A step of its own, not a special case of NAME: mid-booking the name and the number are
    # already on the record, and the offer used to be skipped entirely (founder call
    # 14ea2579, 2026-09-11 15:56:30), filing an urgent item nobody had agreed to.
    if slots.flow == "clinical" and not slots.offer_accepted:
        return Step.CLINICAL_OFFER
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
    # The link question comes *after* the filing, never before it (founder call 14ea2579,
    # 2026-09-11 15:56): a step in front of the ledger is a booking the team never sees.
    if link_offer_open(slots, cfg, channel):
        return Step.LINK_OFFER
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
    if step == Step.CLINICAL_OFFER:
        return "clinical_offer", {}
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
    if step == Step.LINK_OFFER:
        return "link_offer", {}
    return None


# The slot tool each step offers. PHONE and COMPLETE are decided in `step_tools` itself.
STEP_TOOL = {
    Step.RETURNING: "answer",
    Step.OFFERS: "answer",
    Step.CLINICAL_OFFER: "answer",
    Step.PRACTITIONER: "choose_practitioner",
    Step.SERVICE: "choose_service",
    Step.NAME: "give_name",
    Step.WINDOW: "choose_window",
    Step.TEAM_NOTE: "answer",
    Step.LINK_OFFER: "answer",
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
        if slots.filed and slots.service_id and slots.phone and slots.phone_confirmed and cfg.sms_from_number:
            # A booking already filed on this call: the link is not offered, but a caller who
            # asks for it gets it (founder, 2026-09-12).
            tools.append(slot_tool("send_link", cfg))
    elif step == Step.PHONE:
        if slots.pending is not None and slots.pending.kind == "phone":
            tools.append(slot_tool("answer", cfg))
        elif slots.phone and not slots.misses.get("phone"):
            tools.append(slot_tool("answer", cfg))   # "is the number you're calling from ok?"
        else:
            tools.append(slot_tool("give_phone", cfg))
    elif step == Step.COMPLETE:
        tools.append(slot_tool("file_request", cfg))
    elif step == Step.LINK_OFFER:
        # No `file_request` and no `change_answer`: the item is already on the ledger, a
        # second filing is a second job for the team, and the ledger has no amend path, so a
        # reopened slot would leave a stale row. A correction here reaches the clinic through
        # the transcript and the callback `captured_booking` promises.
        tools.append(slot_tool("answer", cfg))
        if cfg.sms_from_number and slots.phone and slots.phone_confirmed:
            tools.append(slot_tool("send_link", cfg))
    else:
        tools.append(slot_tool(STEP_TOOL[step], cfg))
        if slots.pending is not None and STEP_TOOL[step] != "answer":
            tools.append(slot_tool("answer", cfg))
    if step not in (Step.QA, Step.LINK_OFFER):
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
        "needs_yes_or_no", "name_it_instead", "no_change_named",
        "no_match", "cosmetic_not_clinical", "spelled_name_stands",
    ] | None = None


class Applied(BaseModel, frozen=True):
    """What one tool call did: the new record, the fixed lines to say, and the acts the
    driver must perform (escalate, file, send the link, end). `ignored` means the model called
    a tool the step did not offer: nothing is said and nothing is written."""

    slots: Slots
    say: tuple[tuple[str, dict], ...] = ()
    # Hand the conversation to a person now, through the escalate capability. Only the
    # emergency reason also sets `end`: it is the only script that tells the caller to hang up.
    escalate: bool = False
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
    # A fact about the turn, never a value on the record: the slot was recorded and the
    # caller's own words in that same turn asked something the reply has not answered.
    # `draft_from` does not read it and `Slots` does not carry it.
    answer_owed: bool = False


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
    "no_match": (
        "nothing on the list matches what they said; ask them, in your own words, what they "
        "are after, or answer what they asked"
    ),
    "cosmetic_not_clinical": (
        "that is a cosmetic concern the clinic treats, not a clinical question: answer it from "
        "the services list, say what is offered and what is not, and suggest the offer that "
        "plans a first visit"
    ),
    "spelled_name_stands": (
        "the caller spelled their name letter by letter and that spelling is on the record; "
        "it changes only if they spell it again"
    ),
    "name_it_instead": "that question is answered by naming one of the two, not by yes or no",
    "no_change_named": (
        "nothing in what they said names that answer or gives a new one, so it stands as it "
        "is — ask them what they would like to change"
    ),
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
    still gets its own treatment and practitioner.

    A request that was still open is parked rather than thrown away (slot engine spec line
    65): on the founder's call of 2026-09-11 a clinical question one answer from the end of a
    booking lost the booking. Parking is automatic because `start_request` — the only other
    caller — is offered at `Step.QA` alone, where the previous flow is None or ended and the
    guard below is False; so nothing it opens can park anything.

    A flow re-opened over itself keeps the frame it is already holding. The clinical flow is
    opened twice by two doors that need no model judgement — the rules gate on every clinical
    word (`voice/processors.py`) and `escalate`, which every step offers — so the caller who
    re-asks the question instead of answering the offer used to take the parked booking down
    with the rebuilt record. Depth stays at one, because the frame's own `parked` is cleared.
    """
    on_sms = channel == "sms" and bool(caller_phone)
    parked = previous.parked
    if previous.flow is not None and not previous.ended_flow and previous.flow != kind:
        parked = previous.with_(parked=None, digression=None)
    return Slots(
        flow=kind,
        returning_client=previous.returning_client,
        first_name=previous.first_name,
        # The caller id is the number to confirm ("is this the best one?"); on SMS the
        # sender's number needs no confirming.
        phone=previous.phone or caller_phone,
        phone_confirmed=previous.phone_confirmed or on_sms,
        parked=parked,
    )


open_flow = _open


def close_flow(slots: Slots) -> Slots:
    """The flow is done. A parked request comes back; otherwise the record drops to Q&A."""
    if slots.parked is None:
        return slots.with_(flow=None, ended_flow=False, offer_accepted=False, parked=None)
    p = slots.parked
    return p.with_(
        parked=None,
        first_name=slots.first_name or p.first_name,
        phone=slots.phone or p.phone,
        phone_confirmed=slots.phone_confirmed or p.phone_confirmed,
    )


def _finalize(applied: Applied, cfg: TenantConfig, channel: str, name: str = "") -> Applied:
    """The record files itself the moment the last required slot lands, with nothing asked
    in front of it (founder call 14ea2579, 2026-09-11 15:56). The link question comes after,
    as an extra, and the flow stays open across it."""
    s = applied.slots
    if applied.ignored or applied.escalate or applied.file or applied.send_link:
        return applied
    if s.flow is None or s.ended_flow or s.pending is not None or s.filed:
        return applied
    if name in ("escalate", "transfer_to_human"):
        # `transfer_to_human` files its own callback from `_transfer`, and an escalate that
        # opened the clinical flow has an offer to put first. Neither may quietly file the
        # booking the caller was in the middle of.
        return applied
    if next_step(s, cfg, channel) != Step.COMPLETE:
        return applied
    if s.flow == "new_booking" and channel != "voice" and cfg.offer_booking_link:
        # Text channels show the booking link in the conversation itself (Task B4) when the
        # tenant offers links; otherwise the request is filed like any other.
        return applied.model_copy(update={"slots": s.with_(ended_flow=True), "send_link": True})
    filed = s.with_(filed=True)
    if next_step(filed, cfg, channel) == Step.LINK_OFFER:
        return applied.model_copy(update={"slots": filed, "file": True})
    return applied.model_copy(update={"slots": filed.with_(ended_flow=True), "file": True})


def unfiled_record(slots: Slots, cfg: TenantConfig, channel: str) -> bool:
    """Every required slot is on the record and no item was ever written for it."""
    if slots.flow is None or slots.filed or slots.pending is not None:
        return False
    # The team-note question stores nothing on the item (the answer lives in the transcript),
    # so a record that is short of only that answer has given the ledger everything it needs:
    # a caller who hangs up while it is open is still filed (founder call 14ea2579, 15:56).
    probe = slots if slots.team_note_asked else slots.with_(team_note_asked=True)
    return next_step(probe, cfg, channel) in (Step.COMPLETE, Step.LINK_OFFER)


def apply(
    slots: Slots,
    name: str,
    args: dict,
    cfg: TenantConfig,
    channel: str,
    caller_phone: str | None,
    *,
    caller_said: str = "",
) -> Applied:
    """Move the record on one tool call. Answers land only in the open slot (§3.3).

    `caller_said` is the caller's own final transcription for this turn, read and thrown
    away: it decides nothing about the record, only whether the turn left a question of
    theirs unanswered. Nothing of it is stored.
    """
    a = _finalize(
        _apply(slots, name, args, cfg, channel, caller_phone, caller_said=caller_said),
        cfg, channel, name,
    )
    if (
        _slot_recorded(slots, a.slots)
        and not a.ignored
        and not a.file
        and not a.send_link
        and not a.end
        and not a.escalate
        and a.slots.pending is None
        and turn_asked(caller_said)
    ):
        return a.model_copy(update={"answer_owed": True})
    return a


def answer_owed(
    slots: Slots,
    name: str,
    args: dict,
    cfg: TenantConfig,
    channel: str,
    caller_phone: str | None,
    *,
    caller_said: str,
) -> bool:
    """Would this call record a slot while leaving a question of the caller's unanswered?

    The boolean sibling of `tool_rejection`; `apply` is pure, so this just asks it.
    """
    return apply(
        slots, name, args or {}, cfg, channel, caller_phone, caller_said=caller_said
    ).answer_owed


def answer_first_text(slots: Slots, cfg: TenantConfig, channel: str) -> str:
    """What the model is told when it recorded an answer and left the caller's question
    unanswered. A function response, like `rejection_text`: never spoken, never sent, never
    stored, never on an item. Built from the record AFTER the write."""
    r = readiness(slots, cfg, channel)
    lines = [
        "Recorded. The caller asked you something in that same turn and has not been "
        "answered. Answer it now from the facts, in one or two sentences, and say nothing "
        "about what the system recorded."
    ]
    if r.missing is not None:
        lines.append(
            f"Then ask for {r.missing.description} in your own words and put their answer "
            f"in {r.missing.tool}."
        )
    return " ".join(lines)


def tool_refusal(
    slots: Slots,
    name: str,
    args: dict,
    cfg: TenantConfig,
    channel: str,
    caller_phone: str | None,
    *,
    caller_said: str = "",
) -> tuple[bool, str | None]:
    """Would this call change nothing and say nothing, and why? `apply` is pure, so this just
    asks it. The reason is for the model to read as the tool result; it is never spoken."""
    a = apply(slots, name, args, cfg, channel, caller_phone, caller_said=caller_said)
    return a.ignored, (rejection_text(a.rejection) if a.rejection is not None else None)


def tool_rejection(
    slots: Slots,
    name: str,
    args: dict,
    cfg: TenantConfig,
    channel: str,
    caller_phone: str | None,
    *,
    caller_said: str = "",
) -> Rejection | None:
    """The structured sibling of `tool_refusal`: why this call would be refused, or None."""
    return apply(
        slots, name, args or {}, cfg, channel, caller_phone, caller_said=caller_said
    ).rejection


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
    slots: Slots,
    name: str,
    args: dict,
    cfg: TenantConfig,
    channel: str,
    caller_phone: str | None,
    *,
    caller_said: str = "",
) -> Applied:
    if (
        slots.flow == "clinical"
        and not slots.offer_accepted
        and name not in ("answer", "end_conversation", "transfer_to_human", "escalate")
    ):
        # The caller did not take the clinical offer and moved on (founder call 23aad062,
        # 2026-09-11 23:50-23:51: every later turn was refused or dropped for a yes/no the
        # caller never gave, until the line went silent). Moving on is a no: the offer closes
        # without a word, the parked request comes back, and this tool runs against it.
        slots = close_flow(slots)
    step = next_step(slots, cfg, channel)
    if name == "end_conversation":
        # A caller who says "no, that's all" at the last optional question is done with the
        # request, not walking away from it: the record files itself, then the goodbye.
        if slots.flow and not slots.ended_flow and slots.pending is None and step == Step.TEAM_NOTE:
            return Applied(slots=slots.with_(team_note_asked=True), end=True)
        return Applied(slots=slots, end=True)
    if name == "escalate":
        reason = (args or {}).get("reason", "unsure")
        if reason == "clinical":
            if (
                caller_said
                and is_cosmetic_concern(caller_said)
                and (rules_gate(caller_said, cfg) or GateDecision(reason="none", matched="")).reason
                not in ("clinical", "emergency")
            ):
                # "Do you have anything for pigmentation on my arms?" is what the clinic
                # sells, not a clinical question (founder call 23aad062, 23:50:39).
                return _reject("bad_value", name, slots, cfg, channel, detail="cosmetic_not_clinical")
            # The offer first, filed only on yes (slot engine design §4.2, flows.md §1.8).
            # The request in progress is parked, not thrown away (slot engine spec line 65).
            return Applied(slots=_open("clinical", slots, channel, caller_phone))
        # Only the emergency script tells the caller to hang up and dial 911, so it is the
        # only reason that ends anything (flows.md §1.8; voice-regression-V1).
        return Applied(slots=slots, escalate=True, end=reason == "emergency")
    if name == "transfer_to_human":
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
        # The caller's own transcription decides, and the model's `said` is the fallback for a
        # channel that has none: on the founder's call the model rewrote the caller's words
        # once already (15:55:02), so an argument cannot be the evidence for destroying an
        # answer the caller gave.
        if slot == "name" and slots.name_spelled and not spelled_name(caller_said):
            # The recogniser's "Payman" after the caller spelled P-E-Y-M-A-N (call 23aad062,
            # 23:52:09): a spelled name changes only when it is spelled again.
            return _reject("bad_value", name, slots, cfg, channel, detail="spelled_name_stands")
        respelled = slot == "name" and spelled_name(caller_said) is not None
        if not respelled and not _change_evidence(slot, caller_said or args.get("said", ""), cfg):
            return _reject("bad_value", name, slots, cfg, channel, detail="no_change_named")
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
        heard = _heard(said, caller_said, lambda t: match_practitioner(t, cfg))
        if heard is None:
            return _reject("bad_value", name, slots, cfg, channel, detail="question_shaped")
        return _practitioner(slots, heard, cfg, caller_said=caller_said, channel=channel)
    if name == "choose_service":
        # A question is not an answer (founder call 2026-09-11 01:41:26, where "Sorry, what
        # was the- what was the facial one again?" filled the slot and moved the step on).
        said = args.get("said", "")
        if is_question(said):
            return _reject("bad_value", name, slots, cfg, channel, detail="question_shaped")
        heard = _heard(said, caller_said, lambda t: match_service(t, cfg))
        if heard is None:
            return _reject("bad_value", name, slots, cfg, channel, detail="question_shaped")
        return _service(slots, heard, cfg, caller_said=caller_said, channel=channel)
    if name == "give_name":
        return _name(slots, args.get("first_name", ""), cfg, caller_said=caller_said)
    if name == "give_phone":
        return _phone(slots, args.get("digits", ""), caller_phone, channel)
    if name == "choose_window":
        window = PreferredWindow(
            date=args.get("date") or "any", part_of_day=args.get("part_of_day") or "any"
        )
        return Applied(slots=slots.with_(preferred_window=window))
    if name == "file_request":
        return Applied(slots=slots.with_(ended_flow=True, filed=True), file=True)
    if name == "send_link":
        return Applied(slots=slots.with_(ended_flow=True, link_offered=True), send_link=True)
    # A name that passed `_tool_allowed` and is handled nowhere above: not reachable from
    # the tool list the model is given, and refused in words rather than in silence anyway.
    return _reject("not_offered", name, slots, cfg, channel)


def _heard(said: str, caller_said: str, match) -> str | None:
    """What the resolver should read: the model's argument, which strips "uh, sure, the ...
    one" so the resolver sees a clean name — or None when the caller asked a question that
    nothing resolves (founder call dc229ede, 2026-09-11 22:49: "I have pigmentation on my
    arms, do you have anything for that?" became `choose_service('pigmentation on my arms')`
    and the runtime re-asked "which treatment" instead of answering). A miss on a question
    is the question, and the turn goes back to the model.
    """
    if caller_said and match(said).kind == "none" and is_question(caller_said):
        return None
    return said


def _caller_near_miss(caller_said: str, value: str, match) -> bool:
    """Did the caller say something that *almost* names the value the model recorded, without
    ever naming it? "Ellen" for Helen, "MiroJet" for MesoJet. Read word by word, because the
    whole sentence resolves to nothing under its own noise. A caller who named it ("the
    MesoJet one") or who said nothing like it at all ("how much does it cost?" while the
    model carried the treatment over from earlier) is not a near miss.
    """
    named = False
    near = False
    for word in re.findall(r"[a-z]{4,}", caller_said.lower()):
        m = match(word)
        if m.value != value:
            continue
        if m.kind == "exact":
            named = True
        elif m.kind == "confirm":
            near = True
    return near and not named


_SLOT_FIELDS = {
    "returning_client": ("returning_client",),
    "practitioner": ("practitioner",),
    "service": ("service_id",),
    "name": ("first_name",),
    "phone": ("phone",),
    "window": ("preferred_window",),
}


_SLOT_VALUES: tuple[str, ...] = tuple(f for fields in _SLOT_FIELDS.values() for f in fields)

# What the caller's own words have to carry before a filled slot is reopened. Two closed
# vocabularies per slot, because a question that names a slot is a request to be told, not a
# correction: `_SLOT_NAMED` is the slot itself ("what day did I say?") and `_SLOT_VALUE_WORDS`
# is an answer that replaces the one on the record ("make it Wednesday"). A value wins even
# inside a question ("can we do Wednesday instead?"); a name alone does not.
_SLOT_NAMED = {
    "window": ("day", "days", "date", "time", "times", "when", "schedule", "appointment"),
    "service": ("treatment", "treatments", "service", "services", "procedure", "session"),
    "name": ("name", "spelled", "spelling", "misspelled", "called"),
    "phone": ("number", "phone", "cell", "mobile", "digits", "line"),
    "practitioner": (
        "who", "practitioner", "esthetician", "aesthetician", "therapist", "nurse", "doctor",
    ),
    "returning_client": ("client", "before", "first", "new", "returning", "been"),
}
_SLOT_VALUE_WORDS = {
    "window": (
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "morning", "mornings", "afternoon", "afternoons", "evening", "evenings", "night",
        "today", "tomorrow", "tonight", "weekend", "weekday", "noon", "am", "pm",
        "earlier", "later", "sooner",
    ),
    # "anyone" is an answer to the practitioner question in the tenant's own script, so it is
    # a new value there and nowhere else.
    "practitioner": ("anyone", "anybody", "someone", "somebody", "whoever", "any"),
}
_DIGITS = re.compile(r"\d")


def _change_evidence(slot: str, said: str, cfg: TenantConfig) -> bool:
    """Do the caller's own words ask for that answer to be changed?

    Founder call 14ea2579, 2026-09-11 15:56:05: "Oh, actually, you know." became
    `change_answer{'slot': 'window'}`, the filled window was cleared and the day question came
    back for the second time; the caller's next words were "What? I already-". The tool used to
    take a slot name and nothing else, so the runtime had no way to tell a correction from a
    filler. Read and thrown away, like every other transient: nothing here is stored.
    """
    words = re.sub(r"[^a-z0-9' ]+", " ", (said or "").lower()).split()
    if not words:
        return False
    joined = " ".join(words)
    value = any(w in _SLOT_VALUE_WORDS.get(slot, ()) for w in words)
    if slot == "phone":
        value = value or len(_DIGITS.findall(joined)) >= 7
    if not value and slot in ("service", "practitioner"):
        match = match_service(said, cfg) if slot == "service" else match_practitioner(said, cfg)
        # "kind" is a category — "what facial did I say?" names no treatment to change to.
        value = match.kind in ("exact", "confirm", "which")
        if not value:
            # The resolver reads a whole sentence as one answer, so "make it the hydrabrasion
            # one" scores as no match at all. A distinctive catalogue word in the turn is the
            # other half: the same lexicon the breath budget counts names with, and it holds
            # only words that belong to exactly one entry and are four characters or longer.
            lexicon = item_lexicon(cfg)
            service_ids = {sv.id for sv in cfg.services}
            hits = {lexicon[w] for w in words if w in lexicon}
            value = any((h in service_ids) == (slot == "service") for h in hits)
    if value:
        return True
    named = any(w in _SLOT_NAMED.get(slot, ()) for w in words)
    return named and not turn_asked(said)


def _slot_recorded(before: Slots, after: Slots) -> bool:
    """Did this call put an answer of the caller's into a slot that was empty?

    The question the caller asked in the same words is owed an answer when their answer was
    recorded — whichever tool recorded it. A call that refused, confirmed, filed or only
    re-opened a slot records nothing and is not a write.
    """
    return any(
        getattr(before, f) is None and getattr(after, f) is not None for f in _SLOT_VALUES
    )


def _slot_filled(slots: Slots, slot: str) -> bool:
    """Does that slot hold an answer? An unknown slot name holds nothing."""
    return any(getattr(slots, f) is not None for f in _SLOT_FIELDS.get(slot, ()))


def _reopen(slots: Slots, slot: str) -> Slots:
    clear = {
        # The offers question hangs off the returning answer: a caller who corrects "I have
        # not been in before" is a new client again and is offered what a new client is
        # (founder call 1565370e, 2026-09-11 21:40:25).
        "returning_client": {"returning_client": None, "offers_done": False},
        "practitioner": {"practitioner": None},
        "service": {"service_id": None},
        "name": {"first_name": None, "name_spelled": False},
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
    if step == Step.CLINICAL_OFFER:
        # The clinical offer: yes goes on to the name, no closes with nothing filed.
        if yes:
            return Applied(slots=slots.with_(offer_accepted=True))
        return Applied(slots=slots.with_(ended_flow=True), say=(("clinical_declined", {}),))
    if step == Step.RETURNING:
        if value == "unsure":
            # "Okay." to "have you been in before?" (founder call 1565370e, 2026-09-11
            # 21:40:17) is not an answer, and storing it as one sent the call on with the
            # wrong client on the record. The first non-answer is refused so the model asks
            # again in its own words; the second settles as a new client, who is offered
            # everything a new client is, so a caller who will not say is still helped.
            if slots.misses.get("returning_client", 0) >= 1:
                return Applied(slots=slots.with_(returning_client=False))
            return _reject(
                "bad_value", "answer", slots.miss("returning_client"), cfg, channel,
                detail="needs_yes_or_no",
            )
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
    if step == Step.LINK_OFFER:
        return _link_offer(slots, yes, cfg)
    return Applied(slots=slots, ignored=True)


def _link_offer(slots: Slots, yes: bool, cfg: TenantConfig) -> Applied:
    """The extra after the filing. Neither branch files: the item already exists."""
    done = slots.with_(ended_flow=True, link_offered=True)
    if yes and cfg.sms_from_number and slots.phone_confirmed:
        return Applied(slots=done, send_link=True)
    return Applied(slots=done, say=(("link_declined", {}),))


def _after_slot(slots: Slots, cfg: TenantConfig) -> Applied:
    """A practitioner and a service both known: check the pairing (§4.3)."""
    if slots.practitioner and slots.practitioner != "any" and slots.service_id:
        if not cfg.member_does(slots.practitioner, slots.service_id):
            pending = Pending(kind="not_service", slot="practitioner", value=slots.practitioner)
            return Applied(slots=slots.with_(practitioner=None, pending=pending))
    return Applied(slots=slots)


def _practitioner(
    slots: Slots, said: str, cfg: TenantConfig, *, caller_said: str = "", channel: str = "voice"
) -> Applied:
    m = match_practitioner(said, cfg)
    if m.kind == "exact" and _caller_near_miss(caller_said, m.value or "", lambda t: match_practitioner(t, cfg)):
        # Founder call dc229ede (2026-09-11 22:51): "is there an Ellen?" reached the tool as
        # `said='Helen Courbetis'`, exact, and the spec's "Did you mean Helen?" never
        # happened because the model had corrected the name first. A name the caller almost
        # said is a slip until they say yes to it.
        m = Match(kind="confirm", value=m.value, candidates=(m.value,))
    if m.kind == "exact":
        return _after_slot(slots.with_(pending=None, practitioner=m.value), cfg)
    if m.kind == "confirm":
        pending = Pending(kind="match", slot="practitioner", value=m.value)
        return Applied(slots=slots.with_(pending=pending))
    if m.kind == "which":
        pending = Pending(kind="which", slot="practitioner", candidates=m.candidates)
        return Applied(slots=slots.with_(pending=pending))
    # Nothing on the list: the model asks again in its own words, or answers what was asked
    # (founder direction 2026-09-11: fewer fixed re-asks; the ladder went with them).
    return _reject("bad_value", "choose_practitioner", slots.with_(pending=None), cfg, channel, detail="no_match")


def _service(
    slots: Slots, said: str, cfg: TenantConfig, *, caller_said: str = "", channel: str = "voice"
) -> Applied:
    m = match_service(said, cfg)
    if m.kind == "exact" and _caller_near_miss(caller_said, m.value or "", lambda t: match_service(t, cfg)):
        # The same rule as a name: "the MiroJet one" almost said MesoJet, so it is read back.
        m = Match(kind="confirm", value=m.value, candidates=(m.value,))
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
    return _reject("bad_value", "choose_service", slots.with_(pending=None), cfg, channel, detail="no_match")


def _name(slots: Slots, first_name: str, cfg: TenantConfig, *, caller_said: str = "") -> Applied:
    spelled = spelled_name(caller_said)
    if spelled:
        # Letters the caller gave one by one beat any rendering of the sound (call 23aad062).
        return Applied(slots=slots.with_(first_name=spelled, name_spelled=True, pending=None))
    if slots.name_spelled and slots.first_name:
        # Already spelled; the recogniser's next guess at the sound does not overwrite it.
        return Applied(slots=slots)
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
    Step.CLINICAL_OFFER: (
        "clinical_offer",
        "whether they would like the clinical team to reach out to them",
        ("yes", "no"),
    ),
    Step.PRACTITIONER: ("practitioner", "who they would like to see: a name from the team in the facts, or anyone", ()),
    Step.SERVICE: ("service", "which treatment they want, from the SERVICES list above", ()),
    Step.NAME: ("name", "their first name", ()),
    Step.PHONE: ("phone", "the best number to reach them on", ()),
    Step.WINDOW: ("window", "which day or part of the day suits them", ("morning", "afternoon", "evening", "any")),
    Step.TEAM_NOTE: ("team_note", "whether there is anything the team should know before they call", ("yes", "no")),
    Step.LINK_OFFER: (
        "link",
        "whether they would ALSO like the booking link texted to them. Their request is "
        "already filed and the team will call either way, so this is an extra and never a "
        "condition: a no changes nothing",
        ("yes", "no"),
    ),
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

    Three of these `_MISSING` cannot express, and they are three the model got wrong on the
    founder's calls: an open confirmation, a choice between two candidates, and the "is the
    number you're calling from the best one" question. The fourth, the clinical offer, is a
    step of its own since 2026-09-11 and so has a `_MISSING` row like any other.
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
    datum, description, choices = _MISSING[step]
    return Missing(
        datum=datum,
        description=description,
        choices=choices,
        tool=_answer_tool(step, slots, cfg, channel),
    )


class OpenQuestion(BaseModel, frozen=True):
    """The question the record is waiting on, and who owns its wording.

    `fixed` is True when a `Pending` is open — a value the resolver could not settle is read
    back in the tenant's own words, because a wrong read-back is a wrong record
    (candidates-not-verdicts is phase B) — and at `Step.LINK_OFFER`, where the question names
    an action the runtime performs. Leaving the link offer to the model re-creates the very
    defect of 2026-09-11 15:56 (a link-first forced binary), and an unfixed offer a model
    wrapped in its own trailing question would leave the record sitting at that step for the
    rest of the call. Everything else is a plain step question, and the model words it from
    the readiness report (memo §7 decision 1).
    """

    key: str
    fills: dict
    fixed: bool


def open_question(slots: Slots, cfg: TenantConfig, channel: str) -> OpenQuestion | None:
    """The open step's question as a script key, or None when no flow is open."""
    if slots.flow is None or slots.ended_flow:
        return None
    step = next_step(slots, cfg, channel)
    q = step_question(step, slots, cfg, channel)
    if q is None:
        return None
    return OpenQuestion(
        key=q[0],
        fills=q[1],
        fixed=slots.pending is not None or step in (Step.CLINICAL_OFFER, Step.LINK_OFFER),
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


# What every mid-request brief ends with. The side-question path and the honesty rule are
# the same at every step, and a brief that left either out would be the one place the model
# could believe it may claim an outcome (memo §7 decision 1).
_BRIEF_TAIL = (
    " If they ask you something else, call answer_question and answer them. The system "
    "decides what is stored and what is asked next, and the system speaks every outcome "
    "itself: never say a request has been sent, filed, passed on or booked."
)

# Vapi's anti-autocorrect rule, in effect: a recogniser's "payment" for Peyman is a
# transcription problem, and a model that tidies it up hides it (voice-regression-V1, open
# item 2). The steps whose value is a person's own words get it said out loud.
_STEP_EXTRA = {
    # Founder call dc229ede (2026-09-11 22:50): "would you like to hear more about any of
    # those?" — "sure, the MesoJet one" — and the runtime moved straight to the practitioner.
    Step.SERVICE: (
        " If your last question offered to say more about a treatment and they name one, "
        "describe it in two sentences first and ask whether they would like it set up; call "
        "choose_service only once they say they want it."
    ),
    Step.NAME: (
        " Take the name exactly as they say it: never modify it, never autocorrect it, "
        "never guess a spelling."
    ),
    Step.PHONE: (
        " Pass the digits exactly as they say them: never modify, autocorrect or guess."
    ),
}


def step_message(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> str:
    """The readiness report as one paragraph: what is known, what is still needed with its
    legal choices, and which tool takes the answer.

    It used to end "Do not ask a question yourself; one short acknowledgement at most",
    which was the prompt half of the answering machine the founder heard. It now *invites*
    the question: the runtime keeps which slot is open and what may be stored, and gives up
    choosing the words (memo §7 decision 1; OSS §8.2).
    """
    if step == Step.QA:
        return (
            f"{STEP_MARKER} No request is open. Answer questions from the facts. The moment the "
            "caller wants to book, be called back, reschedule, cancel, ask about a course, or "
            "asks something the facts do not answer, call start_request with no words of your "
            "own: never say that you will start, file or pass on a request, and never ask for "
            "their name or number; the system asks the questions from there."
        )
    known_text = ("Known: " + ", ".join(_known(slots, cfg)) + ". ") if _known(slots, cfg) else ""
    if step == Step.COMPLETE:
        return (
            f"{STEP_MARKER} {known_text}Everything is collected. Call file_request now. "
            "Say nothing about the result."
        )
    m = _missing(step, slots, cfg, channel)
    tool = m.tool if m else _answer_tool(step, slots, cfg, channel)
    wanted = m.description if m else "nothing: everything the request needs is on the record"
    if slots.digression is not None:
        # The caller asked something else, and `answer_question` recorded the step it
        # interrupted. It comes ahead of the step's own briefs because answering the caller
        # is the turn's job; the open question follows it, in the model's words.
        return (
            f"{STEP_MARKER} {known_text}They asked something else. Answer it from the facts "
            "in one or two sentences, then ask again, in your own words, for "
            f"{wanted}, and put their answer in {tool}. Do not call answer_question again."
            + _BRIEF_TAIL
        )
    if step == Step.CLINICAL_OFFER:
        # The wording is the tenant's law (non-negotiable 3), so the model must not paraphrase
        # it: the system has already asked, in `scripts.clinical_offer`.
        return (
            f"{STEP_MARKER} {known_text}The caller asked something clinical. The system has "
            "just asked, in its own words, whether they would like the clinical team to reach "
            "out to them. Call answer with yes or no and say nothing else." + _BRIEF_TAIL
        )
    if step == Step.LINK_OFFER:
        return (
            f"{STEP_MARKER} {known_text}The request is filed and the system has already said so. "
            "The only thing left is whether they would also like the booking link texted to "
            "them now. Ask that as an extra, never as a choice between the link and a callback, "
            "and never lead with the link. Call answer with yes or no and say nothing else."
            + _BRIEF_TAIL
        )
    if slots.pending is not None and slots.pending.kind not in ("offers", "which"):
        # A value the resolver could not settle is read back in the tenant's own words, so
        # the runtime has this question and the model must not guess at it.
        return (
            f"{STEP_MARKER} {known_text}The system has just read something back to the caller "
            "in its own words and is waiting for a yes or a no. Call answer with yes or no and "
            "say nothing else." + _BRIEF_TAIL
        )
    if step == Step.OFFERS and slots.pending is None:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether they would like to hear "
            "the new-client offers. Call answer with yes or no and say nothing else: the system "
            "reads the offers itself." + _BRIEF_TAIL
        )
    if step == Step.PHONE and slots.phone and not slots.misses.get("phone") and slots.pending is None:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether the number they are calling "
            "from is the best one. 'Yes' or 'that's fine' is answer with yes; 'no', 'use a different "
            "one' or a new number is answer with no (the system asks for the digits next). Do not "
            "call change_answer for this." + _BRIEF_TAIL
        )
    if step == Step.TEAM_NOTE:
        return (
            f"{STEP_MARKER} {known_text}The system has just asked whether there is anything for the "
            "team to know. 'No', 'nothing' or 'that's all' is the answer to that question: call "
            "answer with no. Do not end the conversation; the system files the request next."
            + _BRIEF_TAIL
        )
    if slots.pending is not None and slots.pending.kind == "offers":
        # The turn brief is the last thing the model reads, so it must say what the
        # consultative section says rather than the opposite: this one used to order the
        # recital that section exists to stop (founder call 14ea2579, 2026-09-11 15:53:14).
        return (
            f"{STEP_MARKER} {known_text}The caller named a kind of treatment. The system just "
            "offered two or three options or a consultation. If they want options, name two or "
            "three that suit what they have said, each with the few words from the services "
            "list that say what it does and no price, then ask whether they would like to hear "
            "more; when they choose one, call choose_service." + _BRIEF_TAIL
        )
    choices = (" — one of: " + ", ".join(m.choices)) if (m and m.choices) else ""
    return (
        f"{STEP_MARKER} {known_text}Still needed: {wanted}{choices}. Ask for it in one short "
        f"question, in your own words, and put their answer in {tool}; when you record an "
        "answer with a tool, ask the next question in the same reply. If instead they change "
        "an earlier answer, call change_answer with that slot and their own words: the system "
        "checks that those words name that answer or give the new one, and refuses the rest."
        + _BRIEF_TAIL
        + _STEP_EXTRA.get(step, "")
    )
