"""What the static half of every model request costs, and what is allowed to move (cost gap C1).

Nine tenths of a call's input tokens are the same bytes on every turn: the system prompt, the
clinic's services and facts, and the tool declarations. Measured from the runtime log of
conversation 85b942b6 by regressing the provider's own `prompt tokens` against the context it
was sent, that static half is **5,930 tokens**, and the growing history is the other 480 to 920:

    ctx chars   prompt tokens        fitted
          284            6018          5974
          ...
         5793            6851          6817
    slope 0.153 tokens per logged context character, intercept 5,930 tokens

At 3 turns a call-minute and $0.25 per million input tokens, every 1,000 tokens of static
prompt costs CA$0.00104 a call minute — 3% of a minute that costs CA$0.035. That is the
number this suite exists to keep honest: a prompt is not free prose, and the test says what a
paragraph costs before it is added.

The vendor's implicit cache takes the sting out of the first ~4,050 tokens of it and no more.
Measured across four real calls, the `cache read input tokens` figure is 3,985 to 4,063 every
single time it appears, whether the static half was 5,930 tokens (2026-09-10) or 7,400
(2026-09-03), so it is a ceiling and not a divergence point — everything above it is billed at
the full rate on every turn. It is also best effort: it appeared on 8 of 13 turns, 7 of 11,
6 of 13 and 8 of 12, and the misses do not line up with the step changes (turn 2 changed step
and missed at 6,046 tokens; turn 3 changed step and hit 4,041).

So there is no prefix trick to play here, only bytes to not send. What this suite pins:

* the request's static half is byte-identical at every step — only the step brief after
  `STEP_MARKER` and the step's tool list move, which is what a prefix cache needs and what
  `spatalk.voice.steps` promises in its module docstring;
* the static half stays inside a stated budget, with the money named, so a prompt edit that
  costs a cent a minute cannot land unnoticed;
* a service id is never spent on it: no tool takes an id from the model (`choose_service`
  takes the caller's words and `spatalk.brain.resolve` matches them), so the 779 characters
  of ids that used to sit in the SERVICES block bought nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)

# The static half of a request, in characters, measured against the provider's own token
# count: 20,809 characters of system message plus tool declarations came to 5,930 tokens,
# so 3.7 characters a token for this prompt's mixture of prose, names and prices.
CHARS_PER_TOKEN = 3.7

# What the static half is allowed to grow to. Today's Skincentrix bundle renders 19,644
# characters (20,428 before the service ids came out); the ceiling leaves room for a clinic
# with a longer list without leaving room for a prompt that doubles. Raising it is a cost
# decision, so raise it deliberately.
STATIC_PROMPT_BUDGET_CHARS = 22_000

# The arithmetic the budget is for: input tokens at the live stack, three turns a minute.
INPUT_USD_PER_1M = 0.25
TURNS_PER_MINUTE = 3.0


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def cad_per_minute(tokens: float) -> float:
    """What carrying `tokens` of static prompt costs per call minute on the live stack."""
    from spatalk.rates import load_rates

    return tokens / 1_000_000 * INPUT_USD_PER_1M * TURNS_PER_MINUTE * load_rates()["usd_to_cad"]


def test_the_static_half_of_the_request_is_byte_identical_at_every_step():
    """`spatalk.voice.steps`: "The static prefix of the system message never changes."

    The step brief rides at the end, after `STEP_MARKER`, so everything before it is the same
    bytes at the name step as at the first question. This is the shape a prefix cache wants;
    it is also the shape that makes a prompt edit's cost predictable.
    """
    from spatalk.brain.flow import STEP_MARKER, Slots, Step, step_message
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    static = build_system_prompt(cfg, "voice", NOW)
    prefixes = set()
    for step in Step:
        message = static + "\n\n" + step_message(step, Slots(flow="new_booking"), cfg, "voice")
        head, marker, brief = message.partition(STEP_MARKER)
        assert marker == STEP_MARKER, f"{step.name} has no step marker"
        assert brief, f"{step.name} has an empty brief"
        prefixes.add(head)
    assert len(prefixes) == 1, "the bytes before the step brief differ between steps"
    assert prefixes.pop() == static + "\n\n"


async def test_the_call_only_rewrites_the_brief_and_the_tools_as_the_step_moves(fixed_clock):
    """The same thing again on a live session, so the wiring is pinned and not just the pure
    functions: `sync_context` replaces the brief and the tool list and nothing else."""
    from spatalk.brain.flow import STEP_MARKER, Slots
    from spatalk.voice.steps import sync_context
    from tests.test_voice_steps import _session

    s, _ = _session(fixed_clock)
    heads, briefs, tools = set(), set(), set()
    for slots in (
        Slots(),
        Slots(flow="new_booking"),
        Slots(flow="new_booking", returning_client=True),
        Slots(flow="new_booking", returning_client=True, practitioner="any"),
        Slots(
            flow="new_booking", returning_client=True, practitioner="any",
            service_id="classic_facial", first_name="Dana",
        ),
    ):
        s.slots = slots
        sync_context(s, fixed_clock.now())
        system = s.context.messages[0]["content"]
        head, _, brief = system.partition(STEP_MARKER)
        heads.add(head)
        briefs.add(brief)
        tools.add(tuple(t.name for t in s.context.tools.standard_tools))
    assert len(heads) == 1, "the static half of the system message moved between steps"
    assert len(briefs) > 1 and len(tools) > 1, "the test is not exercising different steps"


def test_the_static_half_of_the_request_stays_inside_its_budget():
    """The cost of the prompt, stated in money, so an edit cannot quietly spend it."""
    from spatalk.brain.flow import Slots, Step, step_message
    from spatalk.brain.prompt import build_system_prompt
    from spatalk.brain.tools import build_tools, to_genai_declarations

    cfg = _cfg()
    system = build_system_prompt(cfg, "voice", NOW)
    brief = step_message(Step.QA, Slots(), cfg, "voice")
    declarations = repr(to_genai_declarations(build_tools(cfg)))
    chars = len(system) + len("\n\n") + len(brief) + len(declarations)
    tokens = chars / CHARS_PER_TOKEN

    assert len(system) < STATIC_PROMPT_BUDGET_CHARS, (
        f"the system prompt is {len(system)} characters, {cad_per_minute(tokens):.4f} CAD a "
        f"call minute; the budget is {STATIC_PROMPT_BUDGET_CHARS}"
    )
    # The measured static request was 5,930 tokens against the provider's own count. If this
    # estimate drifts far from that the calibration is stale and the money in the report is
    # wrong, so the band is tight on purpose.
    assert 5_000 < tokens < 6_500, f"{tokens:.0f} tokens estimated; 5,930 was measured"
    assert cad_per_minute(tokens) < 0.010


def test_three_in_a_breath_covers_people_as_well_as_treatments():
    """A list of names is a monologue the caller pays for by the second.

    On the founder's call of 2026-09-10 "who is available?" was answered with nine
    practitioners in one breath — 248 characters, 13 seconds of speech, the second longest
    utterance of the call. "Never list more than three options" did not obviously cover
    people, so the rule now says both. No fact leaves the prompt: the team is still in the
    knowledge base and `spatalk.brain.resolve.match_practitioner` still matches any of them
    by name, whether or not the assistant read the list out.
    """
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    p = build_system_prompt(cfg, "voice", NOW).lower()
    assert "more than three" in p
    assert "treatments or three people" in p
    assert "offer to go through more if they want" in p
    # Every practitioner is still a fact the assistant holds.
    for member in cfg.team:
        assert member.name in build_system_prompt(cfg, "voice", NOW)


def test_a_service_line_says_what_it_does_before_it_says_the_price():
    """Purpose first, price last, under a heading that says when a price is wanted.

    On founder call 14ea2579 at 15:53:14 the assistant read seven names and three prices back
    in one breath. The catalogue it read from was rendered `- {name}: {price}.{description}`
    under `SERVICES (name: price):`, which is a price list with a note attached. Reordered, a
    row reads as the answer the caller wanted: what it is, then what it costs.
    """
    from spatalk.brain.prompt import _services_text, build_system_prompt

    cfg = _cfg()
    text = _services_text(cfg)
    lines = {line.split(":", 1)[0]: line for line in text.splitlines()}
    for service in cfg.services:
        if not (service.description or "").strip():
            continue
        line = lines[f"- {service.name}"]
        # Normalised the way `_services_text` normalises it: a description that is exactly
        # one sentence loses its full stop to the em dash that introduces the price.
        head = " ".join((service.description or "").strip().rstrip(".").split()[:6])
        assert head in line, service.id
        assert line.index(head) < line.rindex(service.price_text), service.id

    prompt = build_system_prompt(cfg, "voice", NOW)
    assert "SERVICES (name: price):" not in prompt
    heading = next(ln for ln in prompt.splitlines() if ln.startswith("SERVICES"))
    assert "what it does" in heading
    assert "when they ask or when they have chosen" in heading


def test_a_service_id_is_never_spent_on_the_prompt():
    """No tool takes a service id from the model, so the ids bought nothing but tokens.

    `choose_service` takes `said`, the caller's own words, and `spatalk.brain.resolve` matches
    them against the catalogue in code. The names and the prices stay, because those are what
    the assistant answers with.
    """
    from spatalk.brain.prompt import build_system_prompt
    from spatalk.brain.tools import build_tools, slot_tool

    cfg = _cfg()
    prompt = build_system_prompt(cfg, "voice", NOW)
    for service in cfg.services:
        assert f"[{service.id}]" not in prompt
        assert service.name in prompt
        assert service.price_text in prompt
    # Nothing in the schema the model sees would take an id even if it knew one.
    assert "said" in slot_tool("choose_service", cfg).properties
    for tool in build_tools(cfg):
        assert "service_id" not in tool.properties
        assert "service_id" not in (tool.description or "")
