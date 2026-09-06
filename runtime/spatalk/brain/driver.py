"""The text-mode brain: one turn in, one rendered reply out.

The three structural-honesty layers are visible here, top to bottom:

1. :func:`~spatalk.brain.rules.rules_gate` runs *before* the model. A band-3 trigger never
   reaches the LLM; the reply is fixed tenant wording and the turn ends.
2. Tool calls go through :func:`run_tool`, which moves the slot record and asks the capability what actually
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
from spatalk.brain.flow import (
    Slots,
    apply,
    draft_from,
    next_step,
    open_flow,
    step_message,
    step_question,
    step_tools,
)
from spatalk.brain.requests import (
    BookingLinkRequest,
    ContactInfo,
    ConversationRef,
    EscalateRequest,
)
from spatalk.brain.rules import health_context_mentioned, rules_gate
from spatalk.brain.tools import to_genai_declarations
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
        self.calls_with_tools: list[tuple[str, list[dict], list]] = []

    async def complete(self, system, history, tools) -> LLMResponse:
        self.calls.append((system, history))
        self.calls_with_tools.append((system, history, list(tools)))
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


@dataclass(frozen=True)
class Vendor:
    """One OpenAI-compatible host: where it lives and which settings field holds its key.

    `base_url` is the default; `LLM_<VENDOR>_BASE_URL` overrides it, so moving a vendor to
    another region is an environment change like every other vendor decision.
    """

    base_url: str
    key_field: str

    @property
    def key_env(self) -> str:
        """The environment variable name the settings field is read from."""
        return self.key_field.upper()

    @property
    def base_url_field(self) -> str:
        """The settings field that overrides `base_url`."""
        return f"llm_{self.key_field.removesuffix('_api_key')}_base_url"


# The vendor table (addendum, founder decision 2026-09-03 ~21:40). Every entry speaks the
# OpenAI Chat Completions protocol, so one client and one Pipecat service serve them all and
# the cheapest model is reachable by an environment value alone. Adding a vendor is a line
# here and a key on `Settings`: no other module names one (CLAUDE.md non-negotiable 4).
#
# Google is deliberately absent. It is not OpenAI-compatible, it is the bare-name default,
# and it has its own client.
VENDORS: dict[str, Vendor] = {
    OPENAI: Vendor("https://api.openai.com/v1", "openai_api_key"),
    "openrouter": Vendor("https://openrouter.ai/api/v1", "openrouter_api_key"),
    "deepseek": Vendor("https://api.deepseek.com/v1", "deepseek_api_key"),
    "xai": Vendor("https://api.x.ai/v1", "xai_api_key"),
    "groq": Vendor("https://api.groq.com/openai/v1", "groq_api_key"),
    "together": Vendor("https://api.together.xyz/v1", "together_api_key"),
    "fireworks": Vendor("https://api.fireworks.ai/inference/v1", "fireworks_api_key"),
    # Alibaba's Qwen. The US endpoint, not the Singapore one: measured from the founder's
    # laptop 2026-09-03, dashscope-us shook hands as fast as Google's endpoint while
    # dashscope-intl took 1.2 s. Either is one LLM_DASHSCOPE_BASE_URL away.
    "dashscope": Vendor("https://dashscope-us.aliyuncs.com/compatible-mode/v1", "dashscope_api_key"),
    # The escape hatch: any other OpenAI-compatible host, including one on the VPS itself.
    # It has no default URL because there is nothing sensible to default to.
    "compat": Vendor("", "compat_api_key"),
}


def provider_for(model: str) -> str:
    """The vendor `model` names: a table prefix such as `groq:`, else `"google"`."""
    raw = (model or "").strip().lower()
    for vendor in VENDORS:
        if raw.startswith(f"{vendor}:"):
            return vendor
    return GOOGLE


def model_name(model: str) -> str:
    """`model` as the provider spells it, with any vendor prefix removed."""
    raw = (model or "").strip()
    vendor = provider_for(raw)
    if vendor == GOOGLE:
        return raw
    name = raw[len(vendor) + 1 :].strip()
    if not name:
        # An empty name would fall through to whatever the SDK defaults to, which is a
        # different model than the one the operator thought they had configured.
        raise ValueError(f"LLM_MODEL={model!r} names the {vendor} vendor but no model")
    return name


def base_url_for(settings, vendor: str) -> str:
    """The host to talk to for `vendor`: the environment's value, else the table's."""
    entry = VENDORS[vendor]
    override = (getattr(settings, entry.base_url_field, "") or "").strip()
    base_url = override or entry.base_url
    if not base_url:
        raise ValueError(
            f"LLM_MODEL names the {vendor} vendor but {entry.base_url_field.upper()} is not set"
        )
    return base_url


def vendor_key(settings, vendor: str) -> str:
    """That vendor's API key, or `""` when the environment has not been given one."""
    return (getattr(settings, VENDORS[vendor].key_field, "") or "").strip()


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


# Transient provider failures, retried by the SDK before anyone hears silence (founder
# calls 2026-09-03 21:03 and 21:05: every request answered 503 "high demand"). Three
# attempts with short delays: a caller is on the line, so the whole retry budget stays
# under four seconds; what still fails is spoken about (spatalk.voice.resilience).
TRANSIENT_STATUSES = (429, 500, 502, 503, 504)


def gemini_http_options():
    """HTTP options for a google-genai client: retry the transient statuses, briefly."""
    from google.genai import types

    return types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=3,
            initial_delay=0.5,
            max_delay=2.0,
            http_status_codes=list(TRANSIENT_STATUSES),
        )
    )


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

        self._http_options = gemini_http_options()
        self._client = genai.Client(api_key=api_key, http_options=self._http_options)
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
        base_url: str | None = None,
    ):
        # `base_url` is what makes every OpenAI-compatible host a vendor (addendum): the
        # protocol is the same, only the address differs. None is OpenAI's own default.
        self.base_url = base_url
        self.model = model_name(model)
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._client = client
        self._model, self._temperature = self.model, temperature

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


# --- the text-channel failover (llm failover plan, Task F1) ------------------------------


class FailoverLLMClient:
    """Two vendors behind one :class:`LLMClient`, so one of them being down is survivable.

    Founder decision 2026-09-03 ~21:20. The turn starts at whichever vendor the breaker
    says is worth trying; if that one raises — the SDK has already retried the transient
    statuses by then — the failure is recorded and the *same* turn is sent to the other
    vendor once. Only when both have raised does the exception reach the caller, and it is
    the second one's, because that is the failure the customer's message actually died on.

    Nothing here is allowed to change what the model said. The other vendor's
    :class:`LLMResponse` is returned exactly as it came back, tool calls included: the
    ledger row is the product, and a failover that quietly dropped a `capture_request`
    would lose the very thing the caller rang about.
    """

    def __init__(
        self,
        primary: LLMClient,
        secondary: LLMClient,
        breaker,
        vendors: tuple[str, str],
    ):
        self.primary, self.secondary = primary, secondary
        self.vendors = (vendors[0], vendors[1])
        self._breaker = breaker

    def _order(self) -> list[tuple[str, LLMClient]]:
        """The two vendors, the one worth trying first at the front."""
        first, second = self.vendors
        pairs = [(first, self.primary), (second, self.secondary)]
        if self._breaker.active(first, second) != first:
            pairs.reverse()
        return pairs

    async def complete(self, system, history, tools) -> LLMResponse:
        last: Exception | None = None
        for vendor, client in self._order():
            try:
                response = await client.complete(system, history, tools)
            except Exception as e:  # noqa: BLE001  any failure is this vendor's failure
                last = e
                self._breaker.record_failure(vendor)
                logger.warning("llm vendor {} failed this turn: {}", vendor, e)
                continue
            self._breaker.record_success(vendor)
            return response
        # Both vendors raised. Nothing was said and nothing was filed, so the caller of this
        # client gets the exception and decides what the customer hears.
        raise last  # type: ignore[misc]


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def first_sentence(text: str) -> str:
    """One acknowledgement at most (slot engine design, §3 invariant 4)."""
    parts = _SENTENCE_END.split(text.strip(), maxsplit=1)
    return parts[0] if parts else ""


async def run_tool(
    caps: Capabilities, ref: ConversationRef, slots: Slots, name: str, args: dict, now: datetime
) -> tuple[Slots, list[str], Outcome | None, bool]:
    """One tool call through the engine. Returns (slots, spoken lines, outcome, ended).

    Spoken lines are tenant scripts, never model text. A tool the step did not offer is
    ignored: nothing is said and nothing is written.
    """
    cfg = ref.tenant
    applied = apply(slots, name, args or {}, cfg, ref.channel, ref.caller_phone)
    if applied.ignored:
        logger.warning("tool {} ignored at this step with args {}", name, args)
        return slots, [], None, False
    spoken = [render_script(key, cfg, now, urgent=False, **fills) for key, fills in applied.say]
    outcome: Outcome | None = None
    ended = applied.end
    try:
        if name == "escalate":
            outcome = await caps.escalate(ref, EscalateRequest(reason=args.get("reason", "unsure")))
            spoken.append(render(outcome, cfg, now, channel=ref.channel))
            ended = True
        elif name == "end_conversation":
            spoken.append(render_script("goodbye", cfg, now, urgent=False))
        elif applied.file:
            draft = draft_from(applied.slots, cfg, health_context=ref.health_context)
            outcome = await caps.capture(ref, draft)
            spoken.append(render(outcome, cfg, now, channel=ref.channel))
        elif applied.send_link:
            contact = ContactInfo(name=applied.slots.first_name, phone=applied.slots.phone)
            outcome = await caps.send_booking_link(
                ref, BookingLinkRequest(service_id=applied.slots.service_id or "", contact=contact)
            )
            spoken.append(render(outcome, cfg, now, channel=ref.channel))
    except (ValueError, TypeError) as e:  # bad enum values or shapes from the model
        logger.warning("tool {} rejected args {}: {}", name, args, e)
        return slots, [], None, False
    except Exception as e:  # noqa: BLE001  ledger, SMS or database failure: nothing was saved
        logger.exception("tool {} failed: {}", name, e)
        outcome = Refused(reason="unavailable")
        spoken.append(render(outcome, cfg, now, channel=ref.channel))
    return applied.slots, spoken, outcome, ended


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
    # The slot engine's record after this turn, for the driver to persist (slot engine, §6.3).
    slots: Slots = field(default_factory=Slots)
    # The fixed lines the runtime spoke this turn, for the tests that read them.
    said: list[str] = field(default_factory=list)


class Brain:
    """One turn of conversation, channel-agnostic. Voice drives the same logic through Pipecat."""

    def __init__(self, llm: LLMClient, caps: Capabilities, clock: Clock):
        self._llm, self._caps, self._clock = llm, caps, clock

    async def turn(
        self, ref: ConversationRef, history: list[dict], user_text: str, slots: Slots | None = None
    ) -> TurnResult:
        cfg, now = ref.tenant, self._clock.now()
        slots = slots or Slots()
        if health_context_mentioned(user_text, cfg) and not ref.health_context:
            ref = ref.model_copy(update={"health_context": True})
        gate = rules_gate(user_text, cfg)
        if gate and gate.reason != "clinical":
            out = await self._caps.escalate(ref, EscalateRequest(reason=gate.reason))
            return TurnResult(
                reply=render(out, cfg, now, channel=ref.channel),
                band=3,
                gate_reason=gate.reason,
                tool_calls=["escalate"],
                outcomes=[out],
                ended=True,
                health_context=ref.health_context,
                slots=slots,
            )
        if gate:
            # Clinical: the offer first, filed only on yes (slot engine design, §4.2).
            opened = open_flow("clinical", slots, ref.channel, ref.caller_phone)
            return TurnResult(
                reply=render_script("clinical_offer", cfg, now, urgent=False),
                band=3,
                gate_reason="clinical",
                health_context=ref.health_context,
                slots=opened,
            )
        step = next_step(slots, cfg, ref.channel)
        # The step brief rides at the end of the system prompt: the static prefix stays
        # cacheable, and both vendors keep it as an instruction rather than a model turn.
        system = build_system_prompt(cfg, ref.channel, now) + "\n\n" + step_message(step, slots, cfg, ref.channel)
        resp = await self._llm.complete(
            system,
            history + [{"role": "user", "content": user_text}],
            step_tools(step, slots, cfg, ref.channel),
        )
        said: list[str] = []
        outcomes: list[Outcome] = []
        names: list[str] = []
        ended, band = False, 1
        for tc in resp.tool_calls:
            names.append(tc.name)
            slots, spoken, out, did_end = await run_tool(
                self._caps, ref, slots, tc.name, tc.arguments, now
            )
            said.extend(spoken)
            if out is not None:
                outcomes.append(out)
                if isinstance(out, Captured):
                    band = 3 if out.item_type.startswith("escalation_") else max(band, 2)
            ended = ended or did_end
        ack, blocked = "", False
        if resp.text:
            has_completed = any(isinstance(o, Completed) for o in outcomes)
            g = guard(resp.text, has_completed, cfg, replacement="")
            if g.blocked:
                blocked = True
                try:
                    out = await self._caps.capture(ref, draft_from(Slots(flow="question"), cfg))
                    said.insert(0, render_script("cannot_complete", cfg, now, urgent=False))
                except Exception as e:  # noqa: BLE001  ledger down: nothing was filed, promise nothing
                    logger.exception("guard could not file the blocked claim: {}", e)
                    out = Refused(reason="unavailable")
                    said.insert(0, render(out, cfg, now, channel=ref.channel))
                outcomes.append(out)
                band = max(band, 2)
                logger.warning("guard blocked model text ({}): {!r}", g.matched, resp.text)
            else:
                ack = first_sentence(g.text) if names else g.text
        question = ""
        if not ended and slots.flow and not slots.ended_flow:
            q = step_question(next_step(slots, cfg, ref.channel), slots, cfg, ref.channel)
            if q is not None:
                question = render_script(q[0], cfg, now, urgent=False, **q[1])
        if slots.ended_flow:
            slots = slots.with_(flow=None, ended_flow=False)
        reply = " ".join(p for p in [ack, *said, question] if p).strip()
        return TurnResult(
            reply=reply,
            band=band,
            gate_reason=None,
            tool_calls=names,
            outcomes=outcomes,
            guard_blocked=blocked,
            ended=ended,
            health_context=ref.health_context,
            slots=slots,
            said=said,
        )
