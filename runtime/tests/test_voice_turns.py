"""End-of-turn detection on the phone (founder call 2026-09-03: slow replies after a barge-in).

Pipecat's default stop strategy is Smart Turn with a three-second fallback: when the model
judges an utterance unfinished, it waits up to 3 s of silence before handing over. Interrupted
speech is usually fragmentary, so every barge-in cost about three seconds. The pipeline now
builds the strategy itself with a short fallback, and keeps the Smart Turn model so a
complete-sounding sentence still ends the turn at once.
"""


def _analyzer_of(strategy):
    return getattr(strategy, "_turn_analyzer", None) or getattr(strategy, "turn_analyzer", None)


def _params_of(analyzer):
    return getattr(analyzer, "_params", None) or getattr(analyzer, "params", None)


def test_the_user_turn_ends_with_smart_turn_and_a_short_fallback():
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
        TurnAnalyzerUserTurnStopStrategy,
    )

    from spatalk.voice.pipeline import TURN_END_FALLBACK_SECS, user_turn_params

    params = user_turn_params()
    stops = params.user_turn_strategies.stop
    assert len(stops) == 1 and isinstance(stops[0], TurnAnalyzerUserTurnStopStrategy)
    analyzer = _analyzer_of(stops[0])
    assert isinstance(analyzer, LocalSmartTurnAnalyzerV3)
    assert _params_of(analyzer).stop_secs == TURN_END_FALLBACK_SECS
    assert 0.8 <= TURN_END_FALLBACK_SECS <= 1.5, "the fallback is the pause a caller feels"


def test_the_disclosure_still_cannot_be_talked_over_and_vad_is_on():
    from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (
        MuteUntilFirstBotCompleteUserMuteStrategy,
    )

    from spatalk.voice.pipeline import user_turn_params

    params = user_turn_params()
    assert params.vad_analyzer is not None
    assert any(isinstance(m, MuteUntilFirstBotCompleteUserMuteStrategy) for m in params.user_mute_strategies)
    # The start strategies are Pipecat's defaults: VAD plus transcription.
    assert len(params.user_turn_strategies.start) >= 1
