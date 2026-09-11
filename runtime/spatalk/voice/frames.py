"""One frame of our own: the tool handler telling the guard its half of the turn is done.

The question the caller hears on a tool turn is decided in `OutputGuardProcessor`, because
that is the one place that knows whether the model asked one. The handler is the one place
that knows what the tool did and what the record now needs. Neither can wait for the other:
Pipecat *queues* function calls and pushes `LLMFullResponseEndFrame` without waiting for
them — `pipecat/services/google/llm.py` calls `run_function_calls(function_calls)` and then
pushes the end frame in its `finally`, and `LLMService._run_sequential_function_calls` only
puts the calls on a queue for a background task — so the end frame reaches the guard before
the handler has run, and the handler's own frames reach it afterwards.

This frame closes that gap. The handler pushes it once, last, after its own fixed lines, so
a guard that has seen both the end frame and this one knows the whole turn and can put its
question *after* whatever the runtime already said. `handed_back` is True when the turn was
given back to the model (a rejection, a side question): a fresh completion is coming, so the
runtime asks nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import Frame


@dataclass
class ToolTurnDoneFrame(Frame):
    """The tool handler has finished its half of this model turn."""

    handed_back: bool = False
