"""Rung 0 of the evaluation ladder: what went wrong on a call, as counts (memo §6).

Every signal here is free to record and needs no model. Together they are the only thing
that turns "it isn't as human sounding" into a number, and they are the inputs the phase-C
trouble score will read. The hard rule, enforced by :meth:`SignalLog.record`: a signal is a
count and a closed label, never a word anybody said. This is the same fence non-negotiable 2
puts round a tracked item, applied to the only other per-call record the runtime keeps.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - types only, so this module stays a leaf
    from spatalk.brain.flow import Slots

SIGNAL_KINDS = (
    "repeat",              # the runtime was about to say words it had just said, on an unchanged record
    "reprompt",            # the same step asked again after a miss (an `*_again` script)
    "repair",              # the resolver could not settle a value: a confirmation, or a miss
    "tool_rejected",       # a call the step did not allow, answered in words the model can read
    "model_rerun",         # the turn was handed back so the model could word the question
    "digression",          # `answer_question`: the caller asked something else mid-step
    "bargein",             # the caller interrupted the assistant
    "caller_repeat",       # the caller's words repeated their previous turn
    "guard_block",         # the guard replaced a sentence
    "turn_prediction",     # the turn analyser returned a verdict, with its probability
    "turn_no_prediction",  # the turn closed on the silence fallback, with no verdict
    "truncated",           # the turn ran past its sentence or item budget; the rest of its words were dropped
)

# Everything a signal may carry. There is no key here that could hold a sentence, and
# `CLOSED_VALUE` below rejects any value that looks like one.
DETAIL_KEYS = frozenset({
    "reason", "tool", "script", "datum", "step", "family",
    "probability", "is_complete", "ms", "similarity",
})
CLOSED_VALUE = re.compile(r"^[a-z_]{1,40}$")
MAX_SIGNALS = 200

# The kinds whose values are numbers rather than closed labels, and how each is rounded: a
# probability to two places, a duration to whole milliseconds. Everything else is a label.
_RATIO_KEYS = frozenset({"probability", "similarity"})
_INT_KEYS = frozenset({"ms"})
_BOOL_KEYS = frozenset({"is_complete"})

# The derived signal: the caller was cut off and said it again. It predicted dissatisfaction
# in deployed systems, and it is derived rather than stored so it cannot drift from its two
# parts. A repeat counts when it lands on the turn a barge-in happened or the one after it.
_BARGEIN_WINDOW = 1


class Signal(BaseModel, frozen=True):
    """One thing that went wrong, on one turn, in closed values only."""

    kind: str
    turn: int
    detail: dict[str, float | int | bool | str] = {}


class SignalLog:
    """A call's signals: exact counts, and a capped tail of the events themselves.

    The counter is never capped, so `counts()` stays exact on a long call; only the event
    list is, because a call that produces two hundred events has already said everything a
    threshold needs to know.
    """

    def __init__(self) -> None:
        self.turn = 0
        self._counts: Counter[str] = Counter()
        self._signals: list[Signal] = []

    def next_turn(self) -> None:
        """The caller spoke. Signals recorded from here belong to the new turn."""
        self.turn += 1

    def record(self, kind: str, **detail) -> None:
        if kind not in SIGNAL_KINDS:
            raise ValueError(f"unknown signal kind {kind!r}")
        clean: dict[str, float | int | bool | str] = {}
        for key, value in detail.items():
            if key not in DETAIL_KEYS:
                raise ValueError(f"{key!r} is not a signal detail key")
            clean[key] = _closed(key, value)
        self._counts[kind] += 1
        self._signals.append(Signal(kind=kind, turn=self.turn, detail=clean))
        if len(self._signals) > MAX_SIGNALS:
            del self._signals[0]

    def counts(self) -> dict[str, int]:
        """Every kind that happened, plus the derived `bargein_repeat`."""
        rolled = dict(self._counts)
        bargeins = {s.turn for s in self._signals if s.kind == "bargein"}
        rolled["bargein_repeat"] = sum(
            1
            for s in self._signals
            if s.kind == "caller_repeat"
            and any(s.turn - t in range(_BARGEIN_WINDOW + 1) for t in bargeins)
        )
        return rolled

    def as_json(self) -> dict:
        """What the conversation record stores: the counts, the turns, the capped tail."""
        return {
            "counts": self.counts(),
            "turns": self.turn,
            "signals": [s.model_dump() for s in self._signals],
        }


def _closed(key: str, value) -> float | int | bool | str:
    if key in _BOOL_KEYS:
        return bool(value)
    if key in _RATIO_KEYS:
        return round(float(value), 2)
    if key in _INT_KEYS:
        return int(round(float(value)))
    if not isinstance(value, str) or not CLOSED_VALUE.match(value):
        raise ValueError(f"{key}={value!r} is not a closed value")
    return value


def signals_for(before: Slots, after: Slots) -> list[tuple[str, dict]]:
    """The repairs one tool call produced, derived from what `apply` returned.

    `flow.apply` is pure and cannot log, so the drivers ask this instead: one pure function,
    two callers, one definition of a repair (LIT R3). Exactly two shapes count — a miss
    counter that went up, and a confirmation that appeared — and neither carries a word
    anybody said. A slot that *filled* is not a repair.
    """
    out: list[tuple[str, dict]] = []
    for slot, count in after.misses.items():
        if count > before.misses.get(slot, 0):
            out.append(("repair", {"datum": slot}))
    if after.pending is not None and after.pending != before.pending:
        out.append(("repair", {"datum": after.pending.slot}))
    return out


__all__ = [
    "CLOSED_VALUE",
    "DETAIL_KEYS",
    "MAX_SIGNALS",
    "SIGNAL_KINDS",
    "Signal",
    "SignalLog",
    "signals_for",
]
