"""Keeping the call's LLM context on the open step (slot engine design, §6.5).

The spec's fallback, chosen up front: Pipecat Flows would move the system prompt onto the
LLM service's settings, and this pipeline keeps it as the first context message where the
gate, the guard and the transcript expect it. So the step is synced by hand: the step brief
rides at the end of the system message, replaced each time, and the step's tools are set on
the context. The static prefix of the system message never changes, so the vendor's prompt
cache keeps matching.
"""
from __future__ import annotations

from datetime import datetime

from pipecat.adapters.schemas.tools_schema import ToolsSchema

from spatalk.brain.flow import STEP_MARKER, next_step, step_message, step_question, step_tools
from spatalk.brain.prompt import build_system_prompt
from spatalk.brain.renderer import render_script
from spatalk.voice.session import VoiceSession

_JOIN = "\n\n"


def system_text(session: VoiceSession, now: datetime) -> str:
    """The system message for the open step: the static prompt, then the step brief."""
    step = next_step(session.slots, session.cfg, "voice")
    return (
        build_system_prompt(session.cfg, "voice", now)
        + _JOIN
        + step_message(step, session.slots, session.cfg, "voice")
    )


def sync_context(session: VoiceSession, now: datetime | None = None) -> None:
    """Rewrite the system message's step brief and set the step's tools on the context."""
    ctx = session.context
    if ctx is None:
        return
    now = now or session.clock.now()
    messages = list(ctx.messages)
    fresh = system_text(session, now)
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        first["content"] = fresh
        messages[0] = first
    else:
        messages.insert(0, {"role": "system", "content": fresh})
    ctx.set_messages(messages)
    step = next_step(session.slots, session.cfg, "voice")
    ctx.set_tools(
        ToolsSchema(
            standard_tools=step_tools(
                step, session.slots, session.cfg, "voice", session.transfer_enabled
            )
        )
    )


def step_brief(session: VoiceSession) -> str:
    """The brief alone, for tests that read the context."""
    step = next_step(session.slots, session.cfg, "voice")
    return step_message(step, session.slots, session.cfg, "voice")


def next_question(session: VoiceSession, now: datetime) -> str | None:
    """The fixed question for the open step, rendered, or None when no flow is open."""
    if session.slots.flow is None or session.slots.ended_flow:
        return None
    q = step_question(
        next_step(session.slots, session.cfg, "voice"), session.slots, session.cfg, "voice"
    )
    if q is None:
        return None
    return render_script(q[0], session.cfg, now, urgent=False, **q[1])


__all__ = ["STEP_MARKER", "next_question", "step_brief", "sync_context", "system_text"]
