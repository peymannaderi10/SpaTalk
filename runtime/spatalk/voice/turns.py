"""End-of-turn detection that asks the detector twice.

Pipecat's Smart Turn analyser scores the caller's audio once, when the VAD reports silence.
If it says INCOMPLETE, nothing scores it again: the turn ends only when the silence reaches
``stop_secs`` (our ``TURN_END_FALLBACK_SECS``), and the caller waits the whole of it. On the
founder's calls of 2026-09-11 that fallback fired on a third to a half of turns, because a
caller who pauses mid-sentence looks unfinished at the instant they stop, and less so half a
second later. This analyser scores the segment a second time once the silence has grown past
``rescore_secs``, in the analyser's own thread pool so the audio path never blocks; a COMPLETE
verdict ends the turn there, roughly half a second before the fallback would have.

Pipecat 1.8 API only. Nothing here names a vendor.
"""

from __future__ import annotations

from concurrent.futures import Future

from loguru import logger
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

# Where the second look happens. Below ~0.4 s the model sees the same pause it already
# judged; above ~0.6 s the saving over the 1.0 s fallback stops being worth a second inference.
TURN_RESCORE_SECS = 0.45


class RescoringSmartTurnAnalyzer(LocalSmartTurnAnalyzerV3):
    """Smart Turn v3 with one extra look at the segment after ``rescore_secs`` of silence."""

    def __init__(self, *, rescore_secs: float = TURN_RESCORE_SECS, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rescore_ms = rescore_secs * 1000
        self._rescore: Future | None = None
        self._rescored = False
        self.rescored_complete = 0  # how many turns this analyser ended early, for the log

    def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
        state = super().append_audio(buffer, is_speech)
        if is_speech:
            # The caller spoke again: whatever the second look was judging is stale.
            self._drop_rescore()
            return state
        if state != EndOfTurnState.INCOMPLETE or not self.speech_triggered:
            return state
        if self._rescore is not None:
            if not self._rescore.done():
                return state
            verdict, _ = self._rescore.result()
            self._rescore = None
            if verdict == EndOfTurnState.COMPLETE:
                self.rescored_complete += 1
                logger.debug(
                    "End of Turn complete on the second look, after {} ms of silence",
                    int(self._silence_ms),
                )
                self._clear(EndOfTurnState.COMPLETE)
                return EndOfTurnState.COMPLETE
            return state
        if not self._rescored and self._silence_ms >= self._rescore_ms:
            self._rescored = True
            self._rescore = self._model_executor.submit(
                self._process_speech_segment, list(self._audio_buffer)
            )
        return state

    def _clear(self, turn_state: EndOfTurnState) -> None:
        super()._clear(turn_state)
        self._drop_rescore()

    def _drop_rescore(self) -> None:
        self._rescore = None
        self._rescored = False
