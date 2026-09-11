"""What a call actually costs, per call and per component (cost gap C1).

The pricing calculator quotes from `rates.json` assumptions. On 2026-09-10 the ledger said a
real call cost three to four times those assumptions, and most of that turned out to be the
meter rather than the money:

* `UsageObserver` counted every `MetricsFrame` once per push, and a frame is pushed once per
  processor hop, so one turn's tokens were recorded eight times and one utterance's
  characters four times. The observer now meters a frame once, whatever the pipeline's shape.
* Gemini's `prompt_token_count` already includes `cached_content_token_count`, so billing
  the input at the full rate *and* the cached count again at the cached rate charged the
  cached tokens twice.
* `estimate_cad` priced the September 1 research "recommended" stack while the quote page
  priced `live_stack`, so the overview card and the quote disagreed about the same month.

What this suite pins is the arithmetic, not the numbers on any one call: one frame is one
reading, the cached tokens are billed once at the cached rate, the priced stack is the live
one, the components add up to the estimate, and the per-call breakdown reads the ledger the
report is written from.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_ops_latency import _ctx, _voice_session

NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


def _clock(at=NOW):
    from spatalk.clock import FixedClock

    return FixedClock(at)


def _llm_metrics(prompt: int, cached: int, completion: int):
    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData

    return MetricsFrame(
        data=[
            LLMUsageMetricsData(
                processor="GoogleLLMService#0",
                value=LLMTokenUsage(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=prompt + completion,
                    cache_read_input_tokens=cached,
                ),
            )
        ]
    )


def _tts_metrics(chars: int):
    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import TTSUsageMetricsData

    return MetricsFrame(data=[TTSUsageMetricsData(processor="SonioxTTSService#0", value=chars)])


async def _push(observer, frame):
    from pipecat.observers.base_observer import FramePushed
    from pipecat.processors.frame_processor import FrameDirection

    await observer.on_push_frame(
        FramePushed(
            source=None,
            destination=None,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
        )
    )


async def _usage(
    sf, tenant_id, conversation_id, unit, qty, channel="voice", provider="p", at=NOW
):
    """One usage row, at a stated time: `record_usage` stamps the row with the clock."""
    from spatalk.models import UsageEvent

    async with sf() as s, s.begin():
        s.add(
            UsageEvent(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                channel=channel,
                provider=provider,
                unit=unit,
                qty=qty,
                created_at=at,
            )
        )


async def _call(sf, tenant_id="skincentrix", started_at=NOW, turns=3, seconds=180.0):
    """A recorded voice conversation, with `turns` latency readings on it."""
    from spatalk.models import Conversation

    cid = uuid.uuid4()
    async with sf() as s, s.begin():
        s.add(
            Conversation(
                id=cid,
                tenant_id=tenant_id,
                channel="voice",
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=seconds),
                latency_ms=[1000] * turns,
            )
        )
    return cid


# --- the meter --------------------------------------------------------------------------


async def test_a_metrics_frame_is_metered_once_however_many_times_it_is_pushed(fixed_clock):
    """A `MetricsFrame` is pushed once per processor hop; the money was counted once per hop.

    The founder's call of 2026-09-10 recorded 667,689 input tokens for a call whose provider
    reported 83,339 — exactly eight times, the number of hops from the LLM service to the
    end of the pipeline. The observer sees every push; only the first is the reading.
    """
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)

    frame = _llm_metrics(prompt=6018, cached=4041, completion=18)
    for _ in range(8):
        await _push(observer, frame)
    utterance = _tts_metrics(116)
    for _ in range(4):
        await _push(observer, utterance)

    assert session.usage["llm_input_tokens"] == 6018
    assert session.usage["llm_cached_tokens"] == 4041
    assert session.usage["llm_output_tokens"] == 18
    assert session.usage["tts_chars"] == 116


async def test_a_second_turn_is_a_second_reading(fixed_clock):
    """Deduplication is per frame, not per value: two turns of the same size both count."""
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)

    for _ in range(2):
        await _push(observer, _llm_metrics(prompt=6000, cached=4000, completion=20))
        await _push(observer, _tts_metrics(50))

    assert session.usage["llm_input_tokens"] == 12000
    assert session.usage["llm_cached_tokens"] == 8000
    assert session.usage["tts_chars"] == 100


async def test_a_latency_reading_is_taken_once_per_frame_too(fixed_clock):
    """The same double count inflated the per-stage p95 arrays with eight copies of a turn."""
    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import TTFBMetricsData
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)
    frame = MetricsFrame(data=[TTFBMetricsData(processor="GoogleLLMService#0", value=0.84)])
    for _ in range(8):
        await _push(observer, frame)

    assert session.stage_ttfb_ms["llm"] == [840]


async def test_the_seconds_the_assistant_spoke_are_metered(fixed_clock):
    """The vendor bills speech by the hour it generates; we counted characters we sent.

    On the founder's call of 2026-09-10 the runtime sent 2,691 characters to be spoken and
    the line carried 107.1 seconds of audio: at the 1,087 characters a spoken minute the
    uninterrupted spans of that call actually run at, 751 of those characters (28%) were
    cut off by a barge-in and never heard. The websocket is torn down on an interruption
    (`WebsocketTTSService._handle_interruption` disconnects and reconnects), so the audio
    the vendor never generated is audio it cannot bill for. Seconds of speech are what the
    price is quoted in, so seconds are what we meter.
    """
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)

    await _push(observer, BotStartedSpeakingFrame())
    fixed_clock.advance(seconds=11)
    await _push(observer, BotStoppedSpeakingFrame())
    await _push(observer, BotStartedSpeakingFrame())
    fixed_clock.advance(seconds=6.5)
    await _push(observer, BotStoppedSpeakingFrame())

    assert session.usage["tts_seconds"] == pytest.approx(17.5, abs=0.01)


async def test_a_speaking_span_is_counted_once_per_frame_too(fixed_clock):
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)
    started, stopped = BotStartedSpeakingFrame(), BotStoppedSpeakingFrame()

    # Both frames travel the pipeline and are seen at every hop; upstream and downstream.
    for _ in range(3):
        await _push(observer, started)
    fixed_clock.advance(seconds=4)
    for _ in range(3):
        await _push(observer, stopped)

    assert session.usage["tts_seconds"] == pytest.approx(4.0, abs=0.01)


async def test_a_stop_with_no_start_is_not_a_span(fixed_clock):
    """The disclosure can finish before the observer sees its start on a cold pipeline."""
    from pipecat.frames.frames import BotStoppedSpeakingFrame
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)
    await _push(observer, BotStoppedSpeakingFrame())
    assert session.usage["tts_seconds"] == 0.0


# --- the estimate -----------------------------------------------------------------------


def test_the_cached_tokens_are_billed_once_at_the_cached_rate():
    """`prompt_token_count` already holds `cached_content_token_count` (pipecat's Google
    service maps them straight across), so the full-rate half is the difference."""
    from spatalk.rates import components_cad, live_stack, load_rates

    r = load_rates()
    llm = r["llm"][live_stack(r)["llm"]]
    fx = float(r["usd_to_cad"])

    split = components_cad({"llm_input_tokens": 6000, "llm_cached_tokens": 4000})
    assert split["llm_input"] == pytest.approx(2000 * llm["in"] / 1_000_000 * fx, abs=1e-6)
    assert split["llm_cached"] == pytest.approx(4000 * llm["cached_in"] / 1_000_000 * fx, abs=1e-6)
    # The old arithmetic charged all 6000 at the full rate and the 4000 again on top.
    assert split["llm_input"] + split["llm_cached"] < (
        6000 * llm["in"] + 4000 * llm["cached_in"]
    ) / 1_000_000 * fx


def test_a_cached_count_larger_than_the_input_never_bills_a_negative():
    from spatalk.rates import components_cad, live_stack, load_rates

    r = load_rates()
    llm = r["llm"][live_stack(r)["llm"]]
    split = components_cad({"llm_input_tokens": 1000, "llm_cached_tokens": 4000})
    assert split["llm_input"] == 0.0
    assert split["llm_cached"] == pytest.approx(
        4000 * llm["cached_in"] / 1_000_000 * float(r["usd_to_cad"]), abs=1e-6
    )


def test_the_estimate_prices_the_live_stack_not_the_research_recommendation():
    """The overview card and the quote page must agree about the same month."""
    from spatalk.rates import estimate_cad, live_stack, load_rates, recommended_stack

    r = load_rates()
    live = live_stack(r)
    research = recommended_stack(r["voice_stacks"])
    # The two disagree today: the quote prices Soniox TTS and Flash-Lite, the research row
    # prices Inworld and 2.5 Flash. If they ever agree this test proves nothing, so it says so.
    assert (live["tts"], live["llm"]) != (research["tts"], research["llm"])

    tts = r["tts"][live["tts"]]
    assert estimate_cad({"tts_chars": 1_000_000}) == pytest.approx(
        tts["per_1m_chars"] * float(r["usd_to_cad"]), abs=1e-4
    )


def test_speech_is_priced_by_the_second_when_the_seconds_are_there():
    """`tts_seconds` is to `tts_chars` what `telephony_seconds` is to `call_minutes`: the
    exact unit when the call recorded it, the older one when it did not. Characters are a
    proxy for audio and the proxy over-states an interrupted turn."""
    from spatalk.rates import components_cad, live_stack, load_rates

    r = load_rates()
    tts = r["tts"][live_stack(r)["tts"]]
    fx = float(r["usd_to_cad"])

    by_second = components_cad({"tts_seconds": 107.1, "tts_chars": 2691})
    assert by_second["tts"] == pytest.approx(107.1 / 60 * tts["per_spoken_min"] * fx, abs=1e-6)
    # The characters this call sent price it higher, because 28% of them were never spoken.
    by_char = components_cad({"tts_chars": 2691})
    assert by_char["tts"] > by_second["tts"]
    assert by_char["tts"] == pytest.approx(2691 / 1_000_000 * tts["per_1m_chars"] * fx, abs=1e-6)


def test_the_per_second_and_per_character_prices_are_the_same_price():
    """The per-character rate is the per-hour rate divided by the measured speaking rate;
    if the two drift the quote and the invoice stop agreeing."""
    from spatalk.rates import live_stack, load_rates

    r = load_rates()
    tts = r["tts"][live_stack(r)["tts"]]
    chars_per_spoken_min = r["assumptions"]["chars_per_spoken_minute"]
    assert tts["per_1m_chars"] == pytest.approx(
        tts["per_spoken_min"] / chars_per_spoken_min * 1_000_000, abs=0.05
    )


def test_the_components_add_up_to_the_estimate():
    from spatalk.rates import COMPONENTS, components_cad, estimate_cad

    usage = {
        "telephony_seconds": 185,
        "stt_seconds": 185,
        "tts_chars": 2691,
        "llm_input_tokens": 83339,
        "llm_cached_tokens": 32069,
        "llm_output_tokens": 516,
        "sms_in": 1,
        "sms_out": 2,
    }
    split = components_cad(usage)
    assert set(split) == set(COMPONENTS)
    assert all(v >= 0 for v in split.values())
    assert sum(split.values()) == pytest.approx(estimate_cad(usage), abs=5e-4)


def test_every_priced_unit_lands_in_exactly_one_component():
    """A unit priced but not attributed would vanish from the report it is written for."""
    from spatalk.rates import PRICED_UNITS, components_cad

    for unit in PRICED_UNITS:
        split = components_cad({unit: 1000})
        named = [c for c, v in split.items() if v]
        assert len(named) == 1, f"{unit} -> {named}"


# --- the per-call breakdown -------------------------------------------------------------


async def test_a_call_breakdown_reads_the_ledger_per_conversation(sf, registry):
    from spatalk.ops.cost_breakdown import call_costs

    ctx = _ctx(sf, registry, _clock())
    cid = await _call(sf, turns=13, seconds=184.8)
    await _usage(sf, "skincentrix", cid, "telephony_seconds", 184.8)
    await _usage(sf, "skincentrix", cid, "stt_seconds", 184.8)
    await _usage(sf, "skincentrix", cid, "tts_chars", 2691)
    await _usage(sf, "skincentrix", cid, "llm_input_tokens", 83339)
    await _usage(sf, "skincentrix", cid, "llm_cached_tokens", 32069)
    await _usage(sf, "skincentrix", cid, "llm_output_tokens", 516)

    calls, total = await call_costs(ctx, "skincentrix", NOW.date())
    assert len(calls) == 1
    call = calls[0]
    assert call.conversation_id == cid
    assert call.turns == 13
    assert call.minutes == pytest.approx(3.08, abs=0.01)
    assert call.units["tts_chars"] == 2691
    assert call.components["telephony"] > 0 and call.components["tts"] > 0
    assert call.total_cad == pytest.approx(sum(call.components.values()), abs=5e-4)
    assert call.cad_per_minute == pytest.approx(call.total_cad / call.minutes, abs=1e-6)
    # The totals row is the same shape, so the report prints one renderer.
    assert total.turns == 13
    assert total.total_cad == pytest.approx(call.total_cad, abs=1e-6)


async def test_the_breakdown_sums_every_call_in_the_window_and_skips_the_ones_before_it(
    sf, registry
):
    from spatalk.ops.cost_breakdown import call_costs

    ctx = _ctx(sf, registry, _clock())
    early = await _call(sf, started_at=NOW - timedelta(days=20), turns=5)
    await _usage(sf, "skincentrix", early, "tts_chars", 9999, at=NOW - timedelta(days=20))
    a = await _call(sf, turns=4, seconds=120)
    await _usage(sf, "skincentrix", a, "telephony_seconds", 120)
    await _usage(sf, "skincentrix", a, "tts_chars", 1000)
    b = await _call(sf, turns=6, seconds=240)
    await _usage(sf, "skincentrix", b, "telephony_seconds", 240)
    await _usage(sf, "skincentrix", b, "tts_chars", 2000)

    calls, total = await call_costs(ctx, "skincentrix", NOW.date())
    assert {c.conversation_id for c in calls} == {a, b}
    assert total.turns == 10
    assert total.units["tts_chars"] == 3000
    assert total.minutes == pytest.approx(6.0, abs=0.01)
    assert total.total_cad == pytest.approx(sum(c.total_cad for c in calls), abs=5e-4)


async def test_usage_that_belongs_to_no_conversation_still_reaches_the_total(sf, registry):
    """Staff texts are recorded against the tenant, not a call; the month's money is the
    month's money, so they belong in the total even though no call carries them."""
    from spatalk.ops.cost_breakdown import call_costs

    ctx = _ctx(sf, registry, _clock())
    a = await _call(sf, turns=2, seconds=60)
    await _usage(sf, "skincentrix", a, "telephony_seconds", 60)
    await _usage(sf, "skincentrix", None, "sms_out", 4, channel="sms")

    calls, total = await call_costs(ctx, "skincentrix", NOW.date())
    assert len(calls) == 1
    assert calls[0].units.get("sms_out", 0) == 0
    assert total.units["sms_out"] == 4
    assert total.components["sms"] > 0


async def test_a_call_with_no_minutes_reports_no_cost_per_minute_rather_than_dividing(
    sf, registry
):
    from spatalk.ops.cost_breakdown import call_costs

    ctx = _ctx(sf, registry, _clock())
    cid = await _call(sf, turns=0, seconds=0)
    await _usage(sf, "skincentrix", cid, "tts_chars", 100)

    calls, _ = await call_costs(ctx, "skincentrix", NOW.date())
    assert calls[0].minutes == 0
    assert calls[0].cad_per_minute is None


async def test_the_report_lines_name_every_component_and_the_cost_per_minute(sf, registry):
    from spatalk.ops.cost_breakdown import call_costs, lines

    ctx = _ctx(sf, registry, _clock())
    cid = await _call(sf, turns=13, seconds=184.8)
    await _usage(sf, "skincentrix", cid, "telephony_seconds", 184.8)
    await _usage(sf, "skincentrix", cid, "tts_chars", 2691)
    calls, total = await call_costs(ctx, "skincentrix", NOW.date())

    out = "\n".join(lines(calls, total, "skincentrix"))
    assert "skincentrix" in out
    assert str(cid)[:8] in out
    for component in ("telephony", "tts", "llm"):
        assert component in out
    assert "per minute" in out
    # The stack that was priced is named, so a reader knows what the numbers mean.
    from spatalk.rates import live_stack, load_rates

    assert live_stack(load_rates())["label"] in out
