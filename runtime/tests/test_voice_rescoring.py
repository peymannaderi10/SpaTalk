"""The detector asks twice (founder, 2026-09-12: response time). On the calls of 2026-09-11
the Smart Turn fallback fired on a third to a half of turns, and every one of them waited the
full second. A second look at 0.45 s of silence ends most of them there."""


import numpy as np
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams

from spatalk.voice.turns import TURN_RESCORE_SECS, RescoringSmartTurnAnalyzer

CHUNK_MS = 20


def _chunk(ms: int = CHUNK_MS, speech: bool = False) -> bytes:
    n = 16000 * ms // 1000
    if speech:
        return (np.sin(np.arange(n) * 0.3) * 8000).astype(np.int16).tobytes()
    return np.zeros(n, dtype=np.int16).tobytes()


def _analyzer(verdicts):
    a = RescoringSmartTurnAnalyzer(
        sample_rate=16000,
        params=SmartTurnParams(stop_secs=1.0, pre_speech_ms=0),
    )
    a.set_sample_rate(16000)  # what the StartFrame does on a live call
    calls = []

    def fake(audio_buffer):
        calls.append(len(audio_buffer))
        return verdicts.pop(0), None

    a._process_speech_segment = fake  # the model is the only thing faked
    return a, calls


def _feed_silence(a, ms_total: int):
    """Silence in 20 ms chunks, letting the second look's thread finish between chunks."""
    states = []
    for _ in range(ms_total // CHUNK_MS):
        states.append(a.append_audio(_chunk(), is_speech=False))
        if a._rescore is not None:
            a._rescore.result(timeout=2)  # the fake is instant; wait for the pool, not the clock
    return states


def test_a_second_look_that_says_complete_ends_the_turn_before_the_fallback():
    a, calls = _analyzer([EndOfTurnState.COMPLETE])
    for _ in range(10):
        a.append_audio(_chunk(speech=True), is_speech=True)
    states = _feed_silence(a, 1000)
    first_complete_ms = (states.index(EndOfTurnState.COMPLETE) + 1) * CHUNK_MS
    assert TURN_RESCORE_SECS * 1000 <= first_complete_ms <= TURN_RESCORE_SECS * 1000 + 3 * CHUNK_MS
    assert calls == [10 + first_complete_ms // CHUNK_MS - 1] or len(calls) == 1
    assert a.rescored_complete == 1


def test_a_second_look_that_still_says_incomplete_leaves_the_fallback_alone():
    a, calls = _analyzer([EndOfTurnState.INCOMPLETE])
    for _ in range(10):
        a.append_audio(_chunk(speech=True), is_speech=True)
    states = _feed_silence(a, 1000)
    # The base fallback ends the turn at stop_secs; the second look changed nothing and ran once.
    assert states.index(EndOfTurnState.COMPLETE) == len(states) - 1
    assert len(calls) == 1 and a.rescored_complete == 0


def test_speech_during_the_second_look_discards_it_and_a_new_pause_looks_again():
    a, calls = _analyzer([EndOfTurnState.INCOMPLETE, EndOfTurnState.COMPLETE])
    for _ in range(10):
        a.append_audio(_chunk(speech=True), is_speech=True)
    _feed_silence(a, 500)          # first look, judged incomplete
    a.append_audio(_chunk(speech=True), is_speech=True)   # the caller carries on
    assert a._rescore is None and a._rescored is False
    states = _feed_silence(a, 1000)  # a new pause: looks again, and this time it is complete
    assert EndOfTurnState.COMPLETE in states
    assert (states.index(EndOfTurnState.COMPLETE) + 1) * CHUNK_MS < 1000
    assert len(calls) == 2


def test_the_pipeline_uses_the_rescoring_detector_and_streams_the_voice_by_token():
    """The wiring: `pipeline.py` builds this analyser with the rescore constant, and the
    Soniox voice takes text a token at a time so the first audio starts sooner."""
    import inspect

    from spatalk.voice import pipeline

    src = inspect.getsource(pipeline)
    assert "RescoringSmartTurnAnalyzer(" in src and "rescore_secs=TURN_RESCORE_SECS" in src
    assert "text_aggregation_mode=TextAggregationMode.TOKEN" in src
    assert 0.3 <= TURN_RESCORE_SECS <= 0.6 < pipeline.TURN_END_FALLBACK_SECS
