"""The text-mode brain: one turn in, one rendered reply out.

The three structural-honesty layers are visible here, top to bottom:

1. :func:`~spatalk.brain.rules.rules_gate` runs *before* the model. A band-3 trigger never
   reaches the LLM; the reply is fixed tenant wording and the turn ends.
2. Tool calls go through :func:`dispatch_tool`, which asks the capability what actually
   happened and renders the sentence from the tenant scripts. The model's own words are
   never spoken for an outcome.
3. Free model text passes :func:`~spatalk.brain.guard.guard`. A blocked utterance is replaced
   by the cannot_complete script *and* a real item is filed, so the replacement is true.
"""

from __future__ import annotations

import re

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema

from spatalk.brain.capabilities import Capabilities
from spatalk.brain.guard import guard
from spatalk.brain.outcomes import Captured, Completed, Outcome, Refused
from spatalk.brain.prompt import build_system_prompt
from spatalk.brain.renderer import render, render_script
from spatalk.brain.requests import (
    AppointmentChangeRequest,
    BookingLinkRequest,
    CaptureRequest,
    ContactInfo,
    ConversationRef,
    EscalateRequest,
    PreferredWindow,
)
from spatalk.brain.rules import health_context_mentioned, rules_gate
from spatalk.brain.tools import build_tools, to_genai_declarations
from spatalk.clock import Clock


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]


class LLMClient(Protocol):
    async def complete(
        self, system: str, history: list[dict], tools: list[FunctionSchema]
    ) -> LLMResponse: ...


class FakeLLM:
    """Scripted client for tests. Records every (system, history) pair it was asked to complete."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, list[dict]]] = []

    async def complete(self, system, history, tools) -> LLMResponse:
        self.calls.append((system, history))
        if not self._responses:
            return LLMResponse(text="", tool_calls=[])
        return self._responses.pop(0)


# --- which vendor a model string names (operations plan, Task E6) ------------------------
# Spec §10 weakness 3: the model this runtime talks through is retired on the vendor's
# schedule, not ours. `LLM_MODEL` therefore names the vendor as well as the model, so the
# swap is an environment change: a bare name is Google, `openai:<model>` is OpenAI. Both
# `make_llm` (voice) and `make_text_llm` (text) read it through these two functions, and so
# does `spatalk.ops.model_check`, which is the only way the three can never disagree.

OPENAI_PREFIX = "openai:"
GOOGLE = "google"
OPENAI = "openai"


def provider_for(model: str) -> str:
    """The vendor `model` names: `"openai"` for the `openai:` prefix, else `"google"`."""
    return OPENAI if (model or "").strip().lower().startswith(OPENAI_PREFIX) else GOOGLE


def model_name(model: str) -> str:
    """`model` as the provider spells it, with any vendor prefix removed."""
    raw = (model or "").strip()
    if provider_for(raw) != OPENAI:
        return raw
    name = raw[len(OPENAI_PREFIX) :].strip()
    if not name:
        # An empty name would fall through to whatever the SDK defaults to, which is a
        # different model than the one the operator thought they had configured.
        raise ValueError(f"LLM_MODEL={model!r} names the openai vendor but no model")
    return name


_NO_MINIMAL = re.compile(r"gemini-3\.(7|8|9)")


def gemini_thinking_kwargs(model: str, budget: int) -> dict:
    """The thinking field a Gemini model accepts, from the budget the caller means.

    Gemini 2.5 takes ``thinking_budget`` (0 = answer at once, -1 = unbounded). The 3.x
    generation and the ``-latest`` aliases reject that field with ``400 INVALID_ARGUMENT``
    and take ``thinking_level`` instead (founder call 2026-09-03: every turn went 400 and
    the caller heard silence). ``minimal`` is the closest to "answer at once" they allow.
    """
    if "2.5" in model or "2.0" in model:
        return {"thinking_budget": budget}
    if budget == 0:
        # 3.7 and 3.8 reject "minimal" (400: Thinking level MINIMAL not supported); "low" is
        # their floor. Probed 2026-09-03.
        return {"thinking_level": "low" if _NO_MINIMAL.search(model) else "minimal"}
    if budget < 0:
        return {"thinking_level": "high"}
    return {"thinking_level": "medium"}


class GeminiClient:
    """One swappable LLM vendor. The SDK is imported lazily so tests never need the package."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.3,
        thinking_budget: int = 0,
    ):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model, self._temperature = model, temperature
        # 0 for a caller who is waiting; -1 (unbounded) for the nightly audit's judge, where
        # reasoning time is free and only the token price is not (operations plan, Task E4).
        self._thinking_budget = thinking_budget

    async def complete(self, system, history, tools) -> LLMResponse:
        from google.genai import types

        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in history
        ]
        decls = [
            types.FunctionDeclaration(
                name=d["name"],
                description=d["description"],
                parameters_json_schema=d["parameters"],
            )
            for d in to_genai_declarations(tools)
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self._temperature,
            # A caller with no tools at all is the audit judge, which must classify, not act.
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            thinking_config=types.ThinkingConfig(
                **gemini_thinking_kwargs(self._model, self._thinking_budget)
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        candidate = resp.candidates[0] if resp.candidates else None
        parts = (candidate.content.parts or []) if candidate and candidate.content else []
        for part in parts:
            if getattr(part, "function_call", None):
                calls.append(ToolCall(part.function_call.name, dict(part.function_call.args or {})))
            elif getattr(part, "text", None):
                text_parts.append(part.text)
        return LLMResponse(text=" ".join(text_parts).strip() or None, tool_calls=calls)


# --- the second vendor (operations plan, Task E6) ----------------------------------------


def parse_chat_completion(resp) -> LLMResponse:
    """One OpenAI Chat Completions answer as an :class:`LLMResponse`.

    Split out from :class:`OpenAIClient` so a recorded response can be parsed in a test
    without a client, a key or a network. The shape is the SDK's `ChatCompletion`; only
    duck-typed attribute access is used, so a recorded payload validated by the SDK's own
    model and a hand-built stub are both accepted.
    """
    choices = getattr(resp, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    text = (getattr(message, "content", None) or "").strip() or None
    calls: list[ToolCall] = []
    for call in getattr(message, "tool_calls", None) or []:
        fn = getattr(call, "function", None)
        if fn is None or not getattr(fn, "name", ""):
            continue
        raw = getattr(fn, "arguments", None) or "{}"
        try:
            args = json.loads(raw)
        except (ValueError, TypeError):
            # The same shape GeminiClient produces when the model sends no arguments: the
            # call still runs and `dispatch_tool` answers honestly about the missing
            # fields. Dropping the call instead would leave a voice caller with silence.
            logger.warning("openai tool {} sent unparseable arguments {!r}", fn.name, raw)
            args = {}
        calls.append(ToolCall(fn.name, args if isinstance(args, dict) else {}))
    return LLMResponse(text=text, tool_calls=calls)


class OpenAIClient:
    """The second LLM vendor behind the same protocol as :class:`GeminiClient`.

    Chat Completions, not Responses: it is the API the installed SDK exposes tools through
    in the shape Pipecat's own `OpenAILLMService` uses for the voice half of the same swap
    (`pipecat.services.openai.base_llm` calls `chat.completions.create`), so a drill that
    swaps `LLM_MODEL` puts both channels on one API rather than two.

    `client` is the test seam: production passes nothing and the SDK is imported lazily.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.3,
        client=None,
    ):
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key)
        self._client = client
        self._model, self._temperature = model_name(model), temperature

    async def complete(self, system, history, tools) -> LLMResponse:
        messages = [{"role": "system", "content": system}]
        messages += [
            {"role": "assistant" if m["role"] not in ("user", "system") else m["role"],
             "content": m["content"]}
            for m in history
        ]
        # `to_genai_declarations` already produces `{name, description, parameters}` with a
        # JSON-Schema object for the parameters, which is exactly what a function tool
        # carries here too; only the envelope differs.
        kwargs: dict = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": messages,
        }
        decls = to_genai_declarations(tools)
        if decls:
            # An empty list is rejected by the API, and a caller with no tools at all is the
            # nightly audit's judge, which must classify rather than act.
            kwargs["tools"] = [{"type": "function", "function": d} for d in decls]
        resp = await self._client.chat.completions.create(**kwargs)
        return parse_chat_completion(resp)


def _contact(d: dict | None) -> ContactInfo:
    d = d or {}
    return ContactInfo(
        name=d.get("name") or None, phone=d.get("phone") or None, email=d.get("email") or None
    )


def _window(d: dict | None) -> PreferredWindow:
    d = d or {}
    return PreferredWindow(
        date=d.get("date") or "any", part_of_day=d.get("part_of_day") or "any"
    )


async def dispatch_tool(
    caps: Capabilities, ref: ConversationRef, name: str, arguments: dict, now: datetime
) -> tuple[Outcome | None, str, bool]:
    """Execute one tool. Returns (outcome, spoken text, ended).

    The spoken text always comes from a tenant script via the renderer, never from the model.
    """
    cfg, args = ref.tenant, arguments
    try:
        if name == "send_booking_link":
            out = await caps.send_booking_link(
                ref,
                BookingLinkRequest(
                    service_id=args.get("service_id", ""),
                    contact=_contact(args.get("contact")),
                ),
            )
        elif name == "capture_request":
            out = await caps.capture(
                ref,
                CaptureRequest(
                    kind=args.get("kind", "question"),
                    service_id=args.get("service_id"),
                    contact=_contact(args.get("contact")),
                    preferred_window=_window(args.get("preferred_window")),
                ),
            )
        elif name == "request_appointment_change":
            out = await caps.request_appointment_change(
                ref,
                AppointmentChangeRequest(
                    kind=args.get("kind", "reschedule"),
                    contact=_contact(args.get("contact")),
                    preferred_window=_window(args.get("preferred_window")),
                ),
            )
        elif name == "escalate":
            out = await caps.escalate(ref, EscalateRequest(reason=args.get("reason", "unsure")))
        elif name == "end_conversation":
            return None, render_script("goodbye", cfg, now, urgent=False), True
        else:
            out = Refused(reason="out_of_scope")
    except (ValueError, TypeError) as e:  # bad enum values or shapes from the model
        logger.warning("tool {} rejected args {}: {}", name, args, e)
        out = Refused(reason="out_of_scope")
    except Exception as e:  # noqa: BLE001  ledger, SMS or database failure: nothing was saved
        logger.exception("tool {} failed: {}", name, e)
        out = Refused(reason="unavailable")
    return out, render(out, cfg, now, channel=ref.channel), False


@dataclass
class TurnResult:
    reply: str
    band: int
    gate_reason: str | None
    tool_calls: list[str] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    guard_blocked: bool = False
    ended: bool = False
    health_context: bool = False


class Brain:
    """One turn of conversation, channel-agnostic. Voice drives the same logic through Pipecat."""

    def __init__(self, llm: LLMClient, caps: Capabilities, clock: Clock):
        self._llm, self._caps, self._clock = llm, caps, clock

    async def turn(self, ref: ConversationRef, history: list[dict], user_text: str) -> TurnResult:
        cfg, now = ref.tenant, self._clock.now()
        if health_context_mentioned(user_text, cfg) and not ref.health_context:
            ref = ref.model_copy(update={"health_context": True})
        gate = rules_gate(user_text, cfg)
        if gate:
            out = await self._caps.escalate(ref, EscalateRequest(reason=gate.reason))
            return TurnResult(
                reply=render(out, cfg, now, channel=ref.channel),
                band=3,
                gate_reason=gate.reason,
                tool_calls=["escalate"],
                outcomes=[out],
                ended=True,
                health_context=ref.health_context,
            )
        resp = await self._llm.complete(
            build_system_prompt(cfg, ref.channel, now),
            history + [{"role": "user", "content": user_text}],
            build_tools(cfg),
        )
        parts: list[str] = []
        outcomes: list[Outcome] = []
        names: list[str] = []
        ended, band = False, 1
        for tc in resp.tool_calls:
            names.append(tc.name)
            out, spoken, did_end = await dispatch_tool(self._caps, ref, tc.name, tc.arguments, now)
            if out is not None:
                outcomes.append(out)
                if isinstance(out, Captured):
                    band = 3 if out.item_type.startswith("escalation_") else max(band, 2)
            parts.append(spoken)
            ended = ended or did_end
        blocked = False
        if resp.text:
            has_completed = any(isinstance(o, Completed) for o in outcomes)
            g = guard(resp.text, has_completed, cfg, replacement="")
            if g.blocked:
                blocked = True
                try:
                    out = await self._caps.capture(ref, CaptureRequest(kind="question"))
                    spoken = render_script("cannot_complete", cfg, now, urgent=False)
                except Exception as e:  # noqa: BLE001  ledger down: nothing was filed, promise nothing
                    logger.exception("guard could not file the blocked claim: {}", e)
                    out = Refused(reason="unavailable")
                    spoken = render(out, cfg, now, channel=ref.channel)
                outcomes.append(out)
                band = max(band, 2)
                parts.insert(0, spoken)
                logger.warning("guard blocked model text ({}): {!r}", g.matched, resp.text)
            else:
                parts.insert(0, g.text)
        reply = " ".join(p for p in parts if p).strip()
        return TurnResult(
            reply=reply,
            band=band,
            gate_reason=None,
            tool_calls=names,
            outcomes=outcomes,
            guard_blocked=blocked,
            ended=ended,
            health_context=ref.health_context,
        )
