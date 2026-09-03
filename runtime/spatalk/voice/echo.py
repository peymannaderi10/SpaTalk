"""Echo scrubbing: the assistant's own voice, heard back through the caller's phone.

On a speakerphone or a leaky handset the assistant's greeting comes back down the line, the
transcriber hears it as the caller, and it lands in front of the caller's real words
(founder call 2026-09-03: the transcript showed the caller saying "Thanks for calling ...
I'm Ava"). Echo always arrives as a PREFIX of what the caller then says, so the scrub only
ever trims the front: the longest run of words at the start of a transcription that also
occurs in what the assistant just said, allowing a few misheard words inside the run.
Words the caller repeats later in a sentence ("the classic facial") are never touched.

Deterministic, no model, and it fails safe: with nothing recent from the assistant, or with
too little overlap, the transcription passes through unchanged.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WORD = re.compile(r"[A-Za-z0-9']+")

# A run needs this many words in common with the assistant's speech to count as echo, may
# contain gaps of up to MAX_GAP_WORDS words the transcriber misheard ("Skid Subjects"), and
# must begin within the first MAX_LEAD_GAP_WORDS words: echo is what the phone heard first.
# A match that only starts later is the caller repeating the assistant's phrasing ("Um,
# have the team give me a call", founder call 2026-09-03). Timing, the other half of the
# test, lives in RulesGateProcessor: only speech heard while the assistant was talking
# is scrubbed at all.
MIN_MATCHED_WORDS = 3
MAX_GAP_WORDS = 3
MAX_LEAD_GAP_WORDS = 1
# How much of the assistant's recent speech is kept for comparison.
RECENT_WORDS = 120


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def remember(recent: str, spoken: str) -> str:
    """Append what the assistant just said, keeping the last RECENT_WORDS words."""
    words = _words(recent) + _words(spoken)
    return " ".join(words[-RECENT_WORDS:])


def scrub_echo(transcript: str, recent_bot: str) -> str:
    """Return the transcription without its echoed prefix; "" when it was all echo."""
    if not recent_bot or not transcript.strip():
        return transcript
    spans = list(_WORD.finditer(transcript))
    tw = [m.group(0).lower() for m in spans]
    bw = _words(recent_bot)
    if len(tw) < MIN_MATCHED_WORDS or not bw:
        return transcript

    covered: set[int] = set()
    for block in SequenceMatcher(None, tw, bw, autojunk=False).get_matching_blocks():
        if block.size >= 2:
            covered.update(range(block.a, block.a + block.size))
    if not covered or min(covered) > MAX_LEAD_GAP_WORDS:
        return transcript

    end, gap, matched = -1, 0, 0
    for i in range(len(tw)):
        if i in covered:
            matched, gap, end = matched + 1, 0, i
        else:
            gap += 1
            if gap > MAX_GAP_WORDS:
                break
    if matched < MIN_MATCHED_WORDS or end < 0:
        return transcript
    if end + 1 >= len(spans):
        return ""
    return transcript[spans[end + 1].start() :].strip()
