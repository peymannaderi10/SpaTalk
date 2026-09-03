"""Call notes: a few sentences about the call, drafted from its own transcript (plan N, N1).

The card a staff member opens says what the request *is*, composed from closed columns. It
has never said what the caller was hoping for in their own terms; for that, somebody has to
read the transcript. The founder's words on 2026-09-03: "a mini pre-consultation to get some
notes to help the practitioner easily know what is going on."

So a post-conversation job drafts the notes with a model and stores them on the
**conversation**, next to the transcript they came from. `items` gains no column and the tool
schemas gain no parameter: the model still has nowhere to put a symptom on a tracked item
(CLAUDE.md non-negotiable 2, as amended by this plan). What guards the rest is code, not the
prompt:

* :func:`ground` is the honesty layer. A model asked to summarise will happily add a motive
  nobody stated, and staff would read it as something the caller said. So every sentence must
  share at least three content words with what the caller actually typed or said, or it is
  dropped. Nothing survives, nothing is stored.
* :func:`scrub_health` is the health line. The assistant never asks about a condition; if a
  caller volunteers one it is a boolean flag and the detail stays in the transcript. The same
  rule applies to the notes: any sentence the health-context or clinical lexicon matches is
  replaced, once, by the tenant's fixed :attr:`Scripts.notes_health_line`, and any later one
  is dropped. So the notes can say "wants help with dark spots before a wedding in November"
  and cannot say "is on a medication".

The drafting instruction below is code, not config: it is addressed to a model, and no
customer ever hears a word of it. The health line and the label are tenant scripts, because
staff read those (CLAUDE.md non-negotiable 3).
"""

from __future__ import annotations

import re
import uuid

from loguru import logger

from spatalk import jobs
from spatalk.brain.driver import LLMClient
from spatalk.brain.rules import DEFAULT_LEXICONS, _pattern, health_context_mentioned
from spatalk.conversations import get_transcript, record_usage, set_notes
from spatalk.models import Conversation, Message
from spatalk.tenants.schema import TenantConfig

# The job kind the voice call's end and the text channels' close both queue.
JOB_KIND = "call_notes"

# At most four sentences reach staff, whatever the model returns. The instruction asks for
# four; this is the enforcement, because an instruction is not a limit.
MAX_SENTENCES = 4

# How many content words a sentence must share with the caller's own turns to be kept.
MIN_GROUNDED_WORDS = 3

# A content word is four letters or more and not in this list. The list is deliberately
# small: the common connectives, plus the framing words the drafting instruction itself
# supplies ("caller", "wants", "asked", "team"). Without those the frame of every drafted
# sentence would count as grounding and an invented clause would ride in on it.
STOP_WORDS = frozenset(
    {
        "about", "after", "also", "another", "anything", "asked", "asking", "back", "because",
        "been", "before", "being", "both", "call", "called", "caller", "callers", "calling",
        "client", "clinic", "come", "coming", "could", "does", "doing", "down", "during",
        "each", "else", "even", "ever", "from", "gets", "getting", "give", "given", "going",
        "have", "having", "here", "hope", "hopes", "hoping", "into", "just", "know", "like",
        "likes", "made", "make", "many", "mentioned", "more", "most", "much", "must", "next",
        "onto", "only", "other", "over", "please", "said", "same", "says", "should", "since",
        "some", "someone", "something", "such", "take", "team", "tell", "than", "that",
        "their", "them", "then", "there", "these", "they", "thing", "things", "think",
        "this", "those", "through", "time", "told", "took", "upon", "very", "visit", "want",
        "wanted", "wants", "were", "what", "when", "where", "which", "while", "will",
        "with", "would", "your", "yours",
    }
)

_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

DRAFTING_SYSTEM = (
    "You are reading the transcript of one conversation between a clinic's front desk "
    "assistant and a customer, after it ended. Write notes for the staff member who will "
    "call this person back, so they know what the call was about before they dial.\n"
    "Write at most four plain sentences, in the third person, covering only: what the "
    "customer wants, what they said they are hoping to get out of it, and anything they "
    "asked the team to know.\n"
    "Use only what the customer actually said. Do not infer a motive, a mood or a "
    "circumstance they did not state. Do not describe the customer. Do not give advice or "
    "an opinion. Do not mention a price, an availability, a date you were not given, or "
    "anything the assistant said.\n"
    "Never write about a health condition, a medication, a symptom, a pregnancy or a past "
    "procedure, even if the customer mentioned one.\n"
    "If the customer said nothing worth passing on, answer with nothing at all."
)

# Roles as the model reads them: a conversation, not a database dump.
ROLE_LABELS = {"user": "customer", "assistant": "assistant", "staff": "staff", "system": "system"}


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP_WORDS]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def ground(notes: str, user_turns: list[str]) -> str | None:
    """Keep only the sentences the caller's own words support; ``None`` when none survive.

    A sentence stays when at least :data:`MIN_GROUNDED_WORDS` of its content words appear in
    what the caller said. Three is the threshold because one or two shared words is what any
    sentence about the same subject would share; three is a claim traceable to the turn it
    came from.
    """
    said = set()
    for turn in user_turns:
        said.update(_content_words(turn))
    kept = [
        sentence
        for sentence in _sentences(notes or "")
        if len(set(_content_words(sentence)) & said) >= MIN_GROUNDED_WORDS
    ]
    return " ".join(kept) or None


def _clinical_pattern(cfg: TenantConfig):
    return _pattern(DEFAULT_LEXICONS["clinical"] + list(cfg.lexicons.clinical))


def scrub_health(notes: str, cfg: TenantConfig) -> str:
    """Replace the first health sentence with the tenant's fixed line and drop any others.

    One replacement, not one per sentence: the line tells staff to read the transcript, and
    it only needs saying once. Everything after it that touches health simply goes, because
    the transcript is where that detail belongs and the fixed line already points there.
    """
    clinical = _clinical_pattern(cfg)
    out: list[str] = []
    replaced = False
    for sentence in _sentences(notes or ""):
        if health_context_mentioned(sentence, cfg) or clinical.search(sentence):
            if not replaced:
                out.append(cfg.scripts.notes_health_line)
                replaced = True
            continue
        out.append(sentence)
    return " ".join(out)


def _history(messages: list[Message]) -> list[dict]:
    """The transcript as the model reads it, with the roles named."""
    return [
        {
            "role": "user" if m.role != "assistant" else "assistant",
            "content": f"{ROLE_LABELS.get(m.role, m.role)}: {m.text}",
        }
        for m in messages
        if (m.text or "").strip()
    ]


async def draft_notes(messages: list[Message], cfg: TenantConfig, llm: LLMClient) -> str | None:
    """Draft the notes for one conversation, or ``None`` when there is nothing to store.

    ``None`` for a transcript with no customer turns (the model is not called at all), for an
    empty answer, and for an answer where no sentence survived :func:`ground`.
    """
    user_turns = [m.text for m in messages if m.role == "user" and (m.text or "").strip()]
    if not user_turns:
        return None
    response = await llm.complete(DRAFTING_SYSTEM, _history(messages), [])
    grounded = ground(response.text or "", user_turns)
    if grounded is None:
        return None
    scrubbed = scrub_health(grounded, cfg).strip()
    if not scrubbed:
        return None
    return " ".join(_sentences(scrubbed)[:MAX_SENTENCES])


# --- the job ------------------------------------------------------------------------------
# One attempt, then dead. A drafting failure is a missing paragraph on a card, not a lost
# request: retrying it five times would cost five model calls and tell nobody anything the
# first `last_error` did not.

# Characters per token, for the usage the drafting cost. The `LLMClient` protocol carries no
# usage counts (it is the same client the conversational turns use, where the Pipecat
# observer meters the pipeline instead), so this is an estimate and `usage_events` records it
# as one, the same four-characters-a-token rule the cost model plans with.
CHARS_PER_TOKEN = 4


def _tokens(text: str) -> float:
    return round(len(text or "") / CHARS_PER_TOKEN, 1)


def _llm_for(ctx: jobs.JobContext) -> LLMClient | None:
    """The configured client, through the same `LLM_MODEL` switch as every other channel.

    `voice.pipeline.make_llm` builds a Pipecat service for the audio pipeline, which is not
    an `LLMClient`; `text.service.make_text_llm` reads the identical vendor switch and
    returns one, so the notes follow the runtime's model wherever it is pointed.
    """
    if ctx.llm is not None:
        return ctx.llm
    from spatalk.text.service import make_text_llm

    return make_text_llm(ctx.settings)


@jobs.register_handler(JOB_KIND)
async def _call_notes_job(payload: dict, ctx: jobs.JobContext) -> None:
    conversation_id = uuid.UUID(str(payload["conversation_id"]))
    async with ctx.sf() as s:
        conv = await s.get(Conversation, conversation_id)
    if conv is None:
        raise jobs.DeadLetter(f"unknown conversation {conversation_id}")
    if conv.notes_at is not None:
        logger.debug("conversation {} already has notes; skipping", conversation_id)
        return
    cfg = await ctx.registry.get(conv.tenant_id)
    if not cfg.call_notes:
        return
    llm = _llm_for(ctx)
    if llm is None:
        raise jobs.DeadLetter("no LLM client is configured; notes cannot be drafted")

    messages = await get_transcript(ctx.sf, conversation_id)
    spoke = any(m.role == "user" and (m.text or "").strip() for m in messages)
    try:
        notes = await draft_notes(messages, cfg, llm)
    except Exception as e:  # noqa: BLE001 - one attempt, then a dead letter with the reason
        raise jobs.DeadLetter(f"{type(e).__name__}: {e}") from e

    at = ctx.clock.now()
    model = ctx.settings.llm_model
    # `notes_at` is stamped even when nothing was stored: the drafting happened, and it
    # happens once. `notes` stays null rather than carrying a placeholder.
    await set_notes(ctx.sf, conversation_id, notes, model, at)
    if not spoke:
        # `draft_notes` returned before calling the model, so there is nothing to meter.
        return
    await record_usage(
        ctx.sf, conv.tenant_id, conversation_id, conv.channel, model, "llm_input_tokens",
        _tokens(DRAFTING_SYSTEM + "".join(m["content"] for m in _history(messages))),
    )
    await record_usage(
        ctx.sf, conv.tenant_id, conversation_id, conv.channel, model, "llm_output_tokens",
        _tokens(notes or ""),
    )
