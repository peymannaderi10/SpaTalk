# Model Words, Runtime Record — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status.** Written 2026-09-11 against `main` after the sibling agent's narrow voice fix, which **landed while this plan was being written**: `b277622` (a question is not an answer to the open slot), `117cb18` (a generic category entry resolves to a kind), `8563882` (a fragment with no content words is not a turn), `2f2a247` (the fixed step question never fires twice on an unchanged record). The plan is written against `2f2a247` and every code excerpt below quotes that tree. Its report is `docs/reports/tasks/voice-narrow-fix-V2.md`; **read it before Task 1** if it exists by then, and read the four commit messages either way — they are unusually complete.

Four things the narrow fix already put on `main`, which this plan **extends rather than introduces**. Do not re-implement any of them:

- `spatalk.brain.resolve.is_question(said)` — the shared pure predicate for a question-shaped argument. Task 5 keeps it exactly where it is.
- `Applied.rejection: str | None`, fed from the fixed `flow.ANSWER_THE_QUESTION` dict, plus `flow.tool_refusal(...) -> tuple[bool, str | None]` and the handler's `result["rejection"]` payload with `run_llm=True`. **Task 5 upgrades the type of that one field** from a flat string to the structured Parlant shape and renders it back through `tool_refusal`, so the handler's contract and the payload key do not move.
- The handler no longer appends the fixed step question on a refused turn, and consults `asked_already` before appending on any turn. **Task 6 generalises that to every turn.**
- `OutputGuardProcessor`'s repeat suppression is now conditional on the record alone (the `_spoke_this_turn` conjunct is gone), and a silent turn on an unchanged record is silent by design. Task 6 builds on that; it does not undo it.

The narrow fix also added roughly thirty tests, so the suite count in Verification below is from *before* it. **Record the real baseline yourself**: `git rev-parse HEAD` at the branch point, one full suite run, and put both in the Task 9 report.

**Goal.** The runtime keeps the record and the transitions; the model gets the words back — but only after the guard is strong enough to hold a model that words its own questions. Phase A is the half of that which alone fixes the 01:40 call of 2026-09-11: the caller who asked "what was the facial one again?" and had his words filed as a service choice because the only tool on the table asserted one.

**Architecture.** Five changes, in the memo's order. (A1) One private egress function in `OutputGuardProcessor` is the only path to TTS, with `guard()` inside it, a guard-owned re-entrancy flag, a lexicon that also rejects outcome-implying stalls, and receipt-or-retract. (A2) An always-live `answer_question` tool with no arguments that writes nothing, pushes a single digression frame on `Slots`, and hands the turn to the model. (A3) `flow.apply` returns a `Rejection` the model can read instead of a silent `ignored=True`, naming what is missing and the legal choices. (A4) The voice tool handler stops appending `next_question()` to every tool result: it speaks only fixed outcome and confirmation lines and hands the turn back with a readiness report; `next_question()` survives as the fallback for a silent model turn. (A5) Rung 0 of the evaluation ladder: repeats, re-prompts, repairs, rejected tools, barge-in-and-repeat and `TurnMetricsData` recorded as first-class per-call events, on the conversation record and in `/internal`.

**Tech stack.** Python 3.12, pydantic 2, SQLAlchemy async + Alembic, Pipecat 1.8.1 (`LLMContext`, `TTSSpeakFrame`, `FunctionCallResultProperties`, `MetricsFrame`/`TurnMetricsData`), rapidfuzz, metaphone, pytest. No new dependency.

**Spec.** `docs/superpowers/specs/2026-09-11-model-words-runtime-record-design.md` (the memo; sections cited as §N). Founder approved its §7 recommendations on 2026-09-11: adopt the target and the phase order. Research: `docs/research/2026-09-11-human-receptionist-oss-survey.md` §8, §6.4 (cited OSS §n) and `docs/research/2026-09-11-human-receptionist-literature.md` §7, §6.6 (cited LIT Rn). Superseded reading, deliberately: slot-engine invariant 4's "every question the caller hears is a tenant script" becomes "every *outcome sentence* the caller hears is a tenant script; every question realises the act the runtime named" (memo §7 decision 1). Everything else in `docs/superpowers/specs/2026-09-05-slot-engine-design.md` stands.

---

## Global Constraints

- **CLAUDE.md non-negotiables apply in full.** The ones this plan touches hardest:
  1. *Structural honesty.* Tier C never imports or constructs `Completed`. Outcome wording comes from tenant `scripts`, never from a model. **Every model utterance passes `guard()` before reaching a channel** — Task 2 makes that structural instead of conventional. A refusal never claims anything was sent or filed.
  2. *No free text on tracked items.* `ItemDraft` keeps exactly `type, urgency, service_id, contact, preferred_window, health_context, returning_client, practitioner, concern`. **Nothing in this plan widens `ItemDraft`.** `draft_from` stays the only constructor of one. **No tool schema gains a free-text argument**; `answer_question` takes none, and the three transient strings (`said`, `first_name`, `digits`) are unchanged. The `Rejection` object and the signal log are closed-value structures that never hold caller or model words, and neither is ever written to an item.
  3. *Fixed wording is config.* Disclosure, clinical, complaint, payment, callback and goodbye wording stays in `tenants/<id>/scripts.yaml`. **This plan adds no new `scripts.yaml` key and changes no existing wording** — so `tests/test_qa_gate_a.py`'s key-for-key comparison of schema, bundle and `docs/reference/tenant-config.md` needs no edit. The step briefs and the rejection texts are instructions to the model, never spoken and never sent, which is why they live in code.
  4. *Providers are swappable.* No vendor name enters `spatalk/brain/*` or `spatalk/ledger/*` (`tests/test_qa_gate_a.py::test_no_provider_is_hard_wired_into_the_brain_or_the_ledger` trips on a *comment* naming one — V1 learned that the hard way). Say "the recogniser", "the turn analyser".
  5. *Secrets never enter bundles or the repo.* `.env` is untouched. Tests use `MemoryLedger`, `MemorySms`, `MemoryDelivery`, `FakeLLM`, `FixedClock`.
  6. *Pipecat 1.8 API only:* `PipelineWorker` + `WorkerRunner`, `LLMContext` + `LLMContextAggregatorPair`, `Service.Settings(...)`. No `PipelineTask`/`PipelineRunner`.
  7. *Two planes, zero shared tables.* The new `conversations.signals` column is `runtime`-schema and Alembic-owned; the portal reads it only through `/internal`.
  8. *Business time is tenant time.* Nothing here computes a due time; `BusinessCalendar` is untouched.
  9. *Recording off by default.* No audio is persisted. `TurnMetricsData` is three numbers, not audio.
  10. *Every task ends with a commit.* Conventional message. Never `--no-verify`. Never commit `.env`.
- **Memo §3 ordering is binding: A1 lands before any model-worded question reaches TTS.** Tasks 1 and 2 are therefore prerequisites of Task 6, and a partial landing that ships Task 6 without Tasks 1–2 is a defect, not a milestone.
- **Work happens in an isolated git worktree on branch `model-words`**, cut from `main` after the narrow fix. Nothing in the main checkout, the runtime on port 8000, `runtime/.env`, `portal/.env.server` or the `spatalk` / `portal` / `spatalk_test` databases is written.
- **One fresh scratch database per implementer run**, named for the run:
  ```
  docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_mw_<hhmm>"
  ```
  Drop it at the end of the run. Never point a test at `spatalk`, `portal` or `spatalk_test`.
- **pytest from `runtime/`, with the venv's python by absolute path. No `uv run`** (it re-resolves the environment and can rewrite the main checkout's `.venv`):
  ```
  cd <worktree>/runtime
  SPATALK_NO_ENV_FILE=1 \
  PYTHONPATH=<worktree>/runtime \
  TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_mw_<hhmm> \
  C:/Users/Peyman/source/repos/SpaTalk/runtime/.venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider <files>
  ```
  `PYTHONPATH` is not optional: the venv's editable install points at the **main** checkout, so without it the worktree's edits are invisible. Before the first run, prove it:
  ```
  PYTHONPATH=<worktree>/runtime C:/.../runtime/.venv/Scripts/python.exe -c "import spatalk; print(spatalk.__file__)"
  ```
  and confirm the path is inside the worktree. Lint the same way: `... python.exe -m ruff check spatalk tests scenarios`.
- **One pytest process at a time.** The suite shares a database.
- **No paid provider APIs.** The promptfoo suite is not run in this plan (`GOOGLE_API_KEY`, one run per QA gate, the orchestrator's). No runtime restart, no bundle import, no Alembic run against `spatalk`, no DNS, no numbers, no deploy. **No pushes.** The founder's session merges and goes live.
- **Commits carry no trailers of any kind** — no `Co-Authored-By`, no `Claude-Session`, no `Generated with`. Founder decision 2026-09-03; the history was rewritten once already to remove them.
- **Preserve each file's own line endings.** `tests/test_qa_gate_a.py`, `tests/test_tier_c.py` and `spatalk/text/service.py` are CRLF.
- **No placeholder text** in shipped code: no `TODO`, `TBD`, `pass  # implement`, no commented-out code.

## File structure

| File | Responsibility in this plan |
|---|---|
| `spatalk/brain/guard.py` | Two more lexicon families: outcome-implying stalls, receipt assertions. `guard()` gains one keyword-only argument. Still pure, still lexical, still deterministic. |
| `spatalk/voice/processors.py` | `OutputGuardProcessor`: one private `_egress` is the only path to TTS; guard-owned re-entrancy flag; receipt-or-retract; the trailing-question hold narrowed to tool turns; signals recorded. `RulesGateProcessor`: the caller-repeat signal and the receipt from the gate's own item. |
| `spatalk/voice/session.py` | `receipts`, `signals`, `reran_this_turn`; `record_signal`. No new caller text is stored. |
| `spatalk/voice/handlers.py` | Readable rejections; the fixed-confirmation / hand-back split; the digression push; signals. |
| `spatalk/voice/steps.py` | `open_question_text`; `next_question` kept as the fallback. |
| `spatalk/voice/observers.py` | `TurnSignalObserver`: `TurnMetricsData` and the silence-fallback turn. |
| `spatalk/voice/pipeline.py` | Register the new observer. |
| `spatalk/brain/flow.py` | `Slots.digression`; `Missing`, `Readiness`, `readiness()`; `Rejection`, `tool_rejection()`, `rejection_text()`; `OpenQuestion`, `open_question()`; `answer_question` in `apply`; `step_message` becomes a renderer over `readiness()`. `next_step`, `step_tools`, `draft_from`, `_finalize`, `ITEM_TYPE` and every closed-value rule are untouched. |
| `spatalk/brain/tools.py` | `answer_question` in `TOOL_NAMES` and `always_tools`. No argument, no new field, nothing widened. |
| `spatalk/brain/prompt.py` | Two lines added verbatim from projects that ship them; the "never ask for a name or a number yourself" line deleted. |
| `spatalk/brain/driver.py` | The text channels take the shared changes (guard, `answer_question`, the digression pop, the rejection logged). A4 is voice-only — see "Not in this plan". |
| `spatalk/ops/signals.py` (new) | The rung-0 signal log: closed kinds, closed detail keys, counts, and the pure `signals_for(before, after)`. |
| `spatalk/models.py`, `alembic/versions/0015_call_signals.py` | `conversations.signals` JSONB, nullable. |
| `spatalk/conversations.py`, `spatalk/http/internal.py` | `end_conversation(..., signals=...)`; `ConversationFull.signals`. |
| `docs/contracts/runtime-internal.openapi.json`, `portal/src/runtime/client.ts` | Regenerated snapshots. |
| `docs/reference/flows.md`, `docs/reference/data-model.md`, `docs/roadmap.md` | Reference catches up. `tenant-config.md` and `api-surface.md` need no edit. |

## Not in this plan

Named here so nobody implements them by accident, and so the Task 9 report can say what phase B inherits.

- **Candidates-not-verdicts (phase B).** `resolve.Match` keeps returning a verdict; `exact` still writes the slot; `confirm` still produces a `Pending` and the runtime still speaks `confirm_match` **verbatim**. The confirmation wording stays law in phase A, which is exactly why Task 6 splits questions into "fixed" (a `Pending` is open) and "model-worded" (a plain step question).
- **The repair ladder (phase B).** No new script keys, no terse-options rung, no move-on-and-come-back, no filed-but-unconfirmed field. `misses`, `practitioner_any` and `ask_service_kind` behave as they do today. The `repair` signal Task 3 logs is the *measurement* the ladder will be built from, not the ladder.
- **The digression stack (phase B).** Task 4 pushes **one** frame (`Slots.digression: Step | None`), which is all `answer_question` needs. No `tuple[Flow, ...]`, no `INTERRUPT` marker, no completion-criterion resume.
- **STT confidence (phase B).** `TranscriptionFrame.result` is not read. A low-confidence name still goes straight to `give_name`; open item 2 of `voice-regression-V1` ("a mis-transcribed first name is now stored") stays open, and the founder call test says so.
- **The trouble score and Flash escalation (phase C).** Task 7 stores the inputs. Nothing computes a score, nothing switches model, `LLM_MODEL` is not touched, and no script-verbatim mode is added.
- **Turn-taking and pre-rendered audio (phase D).** `TURN_END_FALLBACK_SECS` stays at 1.5 s (V1 refused to tune it from a desk and so does this plan). No `VADUserTurnStartStrategy`, no `text_aggregation_mode=TOKEN`, no Smart Turn re-scoring, no pre-rendered script WAVs, no `SoundfileMixer`. Task 3 captures the data those decisions need.
- **Simulations and the comparison gate (phase E).** No `runtime/scenarios/` Pipecat eval YAML, no τ²-bench persona bank, no Ollama judge, no pass^k. The promptfoo suite is read, not run.
- **Gemini explicit context caching.** The −CA$0.002 to −CA$0.004/min offset for Task 6's cost needs the volatile step brief *out* of the system message, which breaks the byte-identical-prefix property `tests/test_prompt_budget.py` pins. It is a cost task of its own.
- **A4 on the text channels.** `Brain.turn` keeps appending the step question and keeps `drop_trailing_question`. Handing the turn back on SMS means a second `LLMClient.complete()` per turn for wording that is *read*, not heard, and there is no founder complaint behind it. Phase B changes both drivers together, when candidates-not-verdicts gives them a second reason to.
- **A3's delivery on the text channels.** `flow.apply` produces the `Rejection` for both channels (it is pure), and `Brain.turn` logs it — but a text turn is one completion with no tool-result round trip, so the model is not told. Phase B's driver change carries it.

---

### Task 1: The guard's lexicon grows two families — outcome-implying stalls and receipt assertions

Memo §3 items 2 and 3, the pure half. Nothing in the pipeline changes yet, so this task can be reviewed on its own.

**Files:**
- Modify: `spatalk/brain/guard.py`
- Test: `tests/test_guard.py` (extended; every existing case keeps passing)

**Interfaces:**
- Produces: `spatalk.brain.guard.DEFAULT_STALL_LEXICON: list[str]`; `spatalk.brain.guard.DEFAULT_RECEIPT_LEXICON: list[str]`; `spatalk.brain.guard.STALL_BEFORE_ACTION: re.Pattern`; `guard(text: str, has_completed: bool, cfg: TenantConfig, replacement: str, *, receipts: int = 0) -> GuardResult`; `GuardResult(text, blocked, matched, family)` where `family: Literal["completion", "stall", "receipt"] | None`.
- Consumes: `TenantConfig.lexicons.completion` (unchanged; no new tenant lexicon field, so the bundle and `tenant-config.md` do not move).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_guard.py`. The existing six cases stay exactly as they are — in particular `"Let's get you booked in with the team."` must still pass, which is what keeps the stall pattern narrow.

```python
def test_a_stall_that_implies_an_outcome_is_blocked():
    """OpenAI's chat-supervisor clause, adopted: a holding phrase "must NOT indicate whether
    you can or cannot fulfill an action; they should be neutral and not imply any outcome."
    The assistant cannot book, so "let me book that" is a claim with a delay in front of it."""
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "Let me book that for you.",
        "One moment while I book that in.",
        "I'll just put you down for Thursday.",
        "I'm going to schedule that now.",
        "Hold on while I cancel that appointment.",
        "Let me add you to Helen's book.",
    ):
        r = guard(text, False, cfg, replacement="X")
        assert r.blocked is True and r.family == "stall", text


def test_an_offer_and_a_stall_the_assistant_can_keep_are_not_blocked():
    """The line the guard must not cross. An offer names a future the *team* carries out; a
    stall the assistant can honour ("let me check the facts") promises only reading."""
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "Let's get you booked in with the team.",
        "I'd love to help you get that booked.",
        "Let me check that for you.",
        "One moment while I look at the prices.",
        "One moment, I'll connect you to the team.",      # scripts.transferring
        "I'll have the team send you the booking link.",   # scripts.link_captured
    ):
        r = guard(text, False, cfg, replacement="X")
        assert r.blocked is False and r.text == text, text


def test_an_outcome_claim_needs_a_receipt():
    """Receipt-or-retract (memo §3.3). "I've passed that to the team" is the sentence the
    completion lexicon never covered: it claims a filing, not a booking, and on the founder's
    calls the model reached for it before anything had been filed."""
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "I've passed that to the team.",
        "I've sent that over and someone will call you back.",
        "I've made a note for the team.",
        "Your request is in.",
        "I've texted you the link.",
    ):
        assert guard(text, False, cfg, "X", receipts=0).blocked is True, text
        assert guard(text, False, cfg, "X", receipts=0).family == "receipt", text
        assert guard(text, False, cfg, "X", receipts=1).blocked is False, text


def test_the_receipt_lexicon_leaves_the_tenants_own_outcome_scripts_alone_once_an_item_exists():
    """Every outcome script asserts a receipt, which is the point: with a receipt they pass,
    without one they are retracted too. Task 2 records the receipt before the frame goes out."""
    from datetime import datetime, timezone

    from spatalk.brain.guard import guard
    from spatalk.brain.renderer import render_script

    cfg = _bundle_cfg()
    now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    for key in ("captured", "clinical", "human_request", "complaint", "cannot_complete"):
        text = render_script(key, cfg, now, urgent=False)
        assert guard(text, False, cfg, "X", receipts=1).blocked is False, key
        assert guard(text, False, cfg, "X", receipts=0).blocked is True, key


def test_a_question_and_a_refusal_are_never_receipts():
    """`refuse_no_name` says "before I pass that to the team" and `refuse_unavailable` says
    the opposite of a receipt. Neither may be blocked, receipts or not."""
    from datetime import datetime, timezone

    from spatalk.brain.guard import guard
    from spatalk.brain.renderer import render_script

    cfg = _bundle_cfg()
    now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    for key in ("refuse_no_name", "refuse_unavailable", "ask_name", "ask_service", "goodbye"):
        text = render_script(key, cfg, now, urgent=False)
        assert guard(text, False, cfg, "X", receipts=0).blocked is False, key
```

- [ ] **Step 2: Run them and see them fail**

Run: `... -m pytest -q tests/test_guard.py`
Expected: the five new cases FAIL — `TypeError: guard() got an unexpected keyword argument 'receipts'` on three of them, and `AttributeError: 'GuardResult' object has no attribute 'family'` on the others. The six existing cases PASS.

- [ ] **Step 3: The stall pattern**

The distinguishing feature is a **first-person-singular immediate marker** followed inside a short span by an **action the assistant cannot perform**. "Let's", "we", "you" and a bare offer are all left alone, which is what keeps `"Let's get you booked in with the team."` passing.

```python
# An outcome-implying stall (memo §3.2; OpenAI's chat-supervisor filler clause, quoted in
# OSS §8.2): a holding phrase "must NOT indicate whether you can or cannot fulfill an
# action; they should be neutral and not imply any outcome." The assistant cannot book,
# schedule, cancel, reschedule, confirm, file or send, so "let me book that for you" is a
# claim with a delay in front of it. Narrow on purpose: first person singular and immediate
# ("let me", "I'll", "I'm going to", "one moment while I"), never "let's" or "we", so an
# offer the *team* will carry out is untouched.
_STALL_MARKER = (
    r"let me|lemme|i'?ll(?:\s+just|\s+go\s+ahead\s+and)?|i\s?am\s+going\s+to|i'?m\s+going\s+to"
    r"|i'?m|(?:one\s+moment|hold\s+on|bear\s+with\s+me|give\s+me\s+(?:a|one)\s+\w+)"
    r"(?:\s*,)?\s*(?:while|and)\s+i(?:'?ll)?"
)
_STALL_ACTION = (
    r"book|booking|schedule|scheduling|cancel|cancelling|canceling|reschedule|rescheduling"
    r"|confirm|confirming|file|filing|send|sending|text|texting"
    r"|put\s+you\s+(?:in|down)|pop\s+you\s+(?:in|down)|add\s+you|pencil\s+you|sign\s+you\s+up"
)
STALL_BEFORE_ACTION = re.compile(
    rf"(?<![\w-])(?:{_STALL_MARKER})\b[^.!?]{{0,24}}?\b(?:{_STALL_ACTION})(?![\w-])",
    re.IGNORECASE,
)

# Kept as a list beside the pattern so a reader can see the shape the pattern is for, and so
# a tenant-specific addition has an obvious home if one is ever needed.
DEFAULT_STALL_LEXICON = [
    "let me book", "let me schedule", "let me cancel", "let me file that",
    "one moment while i book", "i'll just put you down", "i'm going to schedule",
    "hold on while i cancel", "let me add you",
]
```

Note the interaction with `_mask_intent`: it must run **after** the stall check, not before, or `"Let me get that booked"` is masked into an offer. Order inside `guard()`: stall, then receipt, then completion-with-mask.

- [ ] **Step 4: The receipt lexicon**

```python
# An assertion that something has already been filed, sent or passed on. The completion
# lexicon never covered these: they claim a *filing*, not a booking, and they are what a
# confidently phrased model reaches for when it has called no tool at all. Blocked unless
# the conversation holds a receipt — an item the ledger issued, a link the provider
# accepted, a leg the carrier took (memo §3.3, OSS §8.4(g)).
DEFAULT_RECEIPT_LEXICON = [
    "i've passed", "i have passed", "i've sent", "i have sent", "i've filed", "i have filed",
    "i've flagged", "i have flagged", "i've texted", "i have texted", "i've messaged",
    "i've noted", "i have noted", "i've made a note", "i've let the team know",
    "i've added you", "i'm sending a request", "i'm flagging it",
    "passed that to the team", "sent that to the team", "sent an urgent request",
    "your request is in", "that's with the team", "the request is in",
]
```

Two rules keep the false-positive rate down and are worth a comment in the source:

1. The match is anchored the same way the completion lexicon is — `_pattern()`'s `(?<![\w-])…(?![\w-])` word boundaries — so `"Before I pass that to the team, could I get your first name?"` (`refuse_no_name`) does not match `"i've passed"` and is not a receipt.
2. A sentence that also carries a negation of the claim is not a claim. `refuse_unavailable` says "I'm having trouble saving that right now, so please don't count on me for it" — it contains no receipt phrase, so no special case is needed today; do **not** add a negation detector on speculation. If a future script needs one, that is a change with its own test.

- [ ] **Step 5: `guard()` and `GuardResult`**

```python
@dataclass(frozen=True)
class GuardResult:
    text: str
    blocked: bool
    matched: str | None
    # Which family fired, for the signal log and the log line. None when nothing did.
    family: Literal["completion", "stall", "receipt"] | None = None


def guard(
    text: str,
    has_completed: bool,
    cfg: TenantConfig,
    replacement: str,
    *,
    receipts: int = 0,
) -> GuardResult:
    """Layer 3. `receipts` is how many actions this conversation can actually show for
    itself — items the ledger issued, a link the provider accepted, a leg the carrier took.
    An utterance that asserts one and cannot be backed by one is replaced, whoever wrote it
    (memo §3.3). The default of 0 is the honest default: nothing has been done yet."""
    stall = STALL_BEFORE_ACTION.search(text)
    if stall:
        return GuardResult(replacement, True, stall.group(0).lower().strip(), "stall")
    if not (has_completed or receipts):
        m = _pattern(DEFAULT_RECEIPT_LEXICON).search(text)
        if m:
            return GuardResult(replacement, True, m.group(0).lower(), "receipt")
    if has_completed:
        return GuardResult(text, False, None)
    m = _pattern(DEFAULT_COMPLETION_LEXICON + list(cfg.lexicons.completion)).search(
        _mask_intent(text)
    )
    if m:
        return GuardResult(replacement, True, m.group(0).lower(), "completion")
    return GuardResult(text, False, None)
```

A stall is blocked **even with a receipt and even with `has_completed`**: "let me book that" is never true on this system, and a receipt for an item is not a licence to claim a booking.

- [ ] **Step 6: Run the guard suite and its neighbours**

Run: `... -m pytest -q tests/test_guard.py tests/test_renderer.py tests/test_structural_honesty.py tests/test_driver.py tests/test_voice_processors.py`
Expected: PASS. `guard()`'s two call sites still pass four positional arguments, so nothing else moves yet. If a `FakeLLM` fixture in `tests/test_driver.py` or `tests/test_text_scenarios.py` hands the driver receipt-shaped model text and now gets `cannot_complete`, **that is the bug this task exists to catch** — fix the fixture to the wording the guard permits, or set the test up so a receipt exists; do not loosen the guard.

- [ ] **Step 7: Commit**

```bash
git add spatalk/brain/guard.py tests/test_guard.py
git commit -m "feat(brain): the guard rejects the stall that implies an outcome, and the receipt nobody earned"
```

**Done when:** the five new cases pass and the six existing ones are byte-identical; `guard()` has the exact signature above; `GuardResult.family` names the family; `ruff check` clean.

**Cost:** CA$0.00/min. Pure functions, no model output, no spoken characters.

---

### Task 2: One egress to TTS, with the receipt register behind it

Memo §3 item 1, and the wiring for item 3. After this task there is exactly one line of code in the voice pipeline that can put words on the wire, and `guard()` is inside it.

**Files:**
- Modify: `spatalk/voice/processors.py` (`OutputGuardProcessor`, `RulesGateProcessor`)
- Modify: `spatalk/voice/session.py` (`receipts`, `remember_receipt`)
- Modify: `spatalk/voice/handlers.py` (record the receipt from the ledger's own answer, before the frame)
- Modify: `spatalk/brain/driver.py` (`Brain.turn` passes its own turn's receipts to `guard()`)
- Test: `tests/test_voice_processors.py` (extended), `tests/test_structural_honesty.py` (extended), `tests/test_voice_handlers.py` (extended), `tests/test_driver.py` (extended)

**Interfaces:**
- Produces: `VoiceSession.receipts: list[str]`; `VoiceSession.remember_receipt(kind: str, ref: str) -> None` (kind in `("item", "link", "transfer", "platform")`, ref coerced to `str`); `OutputGuardProcessor._egress(self, text: str, *, model_words: bool, append_to_context: bool = True) -> None` (private, the only `push_frame` of speech in the class); `OutputGuardProcessor._retract(self, sentence: str, g: GuardResult) -> None`; `Brain.turn(..., )` unchanged in signature — it computes `receipts` from the outcomes it produced this turn.
- Consumes: `guard(..., receipts=...)` and `GuardResult.family` from Task 1.

- [ ] **Step 1: Write the failing tests**

`tests/test_structural_honesty.py` — the structural fence, which is the one that matters most:

```python
def test_only_the_egress_function_can_speak_on_a_call():
    """Memo §3.1: "One private egress function is the only path to TTS, with `guard()` inside
    it and a guard-owned re-entrancy flag; no `skip_guard` parameter anywhere."

    Structural rather than behavioural on purpose. Every earlier false claim on a call
    reached the wire through a code path that had not thought about the guard; the fix that
    lasts is that there is only one path.
    """
    import ast
    from pathlib import Path as _Path

    src = (_Path(RUNTIME) / "spatalk" / "voice" / "processors.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guard_cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "OutputGuardProcessor"
    )
    speakers = set()
    for node in ast.walk(guard_cls):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not (isinstance(callee, ast.Attribute) and callee.attr in ("push_frame", "queue_frame")):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                speakers.add(arg.func.id)
    # The only frames this class constructs and pushes are speech frames, and they are
    # constructed in exactly one method.
    assert speakers <= {"LLMTextFrame", "TTSSpeakFrame"}, speakers
    methods = [
        m.name for m in guard_cls.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id in ("LLMTextFrame", "TTSSpeakFrame")
            for c in ast.walk(m)
        )
    ]
    assert methods == ["_egress"], f"speech is constructed in {methods}, not only in _egress"
    assert "skip_guard" not in src


def test_no_model_utterance_reaches_a_channel_without_the_guard():
    """`guard(` appears in `_egress` and nowhere else in the voice package."""
    from pathlib import Path as _Path

    for path in (_Path(RUNTIME) / "spatalk" / "voice").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "guard(" not in src:
            continue
        assert path.name == "processors.py", f"{path} calls guard() outside the egress"
        assert src.count("guard(self") + src.count("= guard(") == 1, "more than one guard call"
```

`tests/test_voice_processors.py`:

```python
async def test_a_paraphrased_outcome_claim_is_retracted_when_nothing_was_filed(fixed_clock):
    """The failure every surveyed project has (memo §6.3). The model says the true-sounding
    thing before any tool ran; the completion lexicon never covered it."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("I've passed that to the team and someone will call you back. "),
        LLMTextFrame("Anything else?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [session.cfg.scripts.cannot_complete]
    # The replacement sentence is true: an item exists, and its id is now a receipt.
    assert len(ledger.items) == 1 and session.receipts == [f"item:{ledger.items[0].id}"]
    assert session.guard_blocks == 1


async def test_the_replacement_sentence_is_not_guarded_again(fixed_clock):
    """`cannot_complete` itself says "I've passed it to the team". Without a guard-owned
    re-entrancy flag the retraction retracts itself, forever."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("I've booked you in for Thursday."),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [session.cfg.scripts.cannot_complete]
    assert len(ledger.items) == 1, "the retraction filed exactly one item"


async def test_a_stall_that_implies_an_outcome_never_reaches_the_wire(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Let me book that in for you."),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [session.cfg.scripts.cannot_complete]


async def test_a_fixed_script_from_upstream_goes_out_with_its_receipt_and_is_held_without_one(fixed_clock):
    """A `TTSSpeakFrame` the gate or a tool handler pushed passes through the same egress.
    With a receipt it goes out untouched; with none, the outcome script is retracted too —
    which is what makes the guarantee structural rather than a matter of call order."""
    from pipecat.frames.frames import TTSSpeakFrame

    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    captured = session.cfg.scripts.captured.format(confirm_by="by 4 pm")
    session.remember_receipt("item", "42")
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=[TTSSpeakFrame(text=captured, append_to_context=True)],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [captured]
    assert ledger.items == []

    session2, ledger2 = _session(fixed_clock)
    down2, _ = await run_test(
        OutputGuardProcessor(session2),
        frames_to_send=[TTSSpeakFrame(text=captured, append_to_context=True)],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert [f.text for f in down2 if isinstance(f, TTSSpeakFrame)] == [
        session2.cfg.scripts.cannot_complete
    ]
```

`tests/test_voice_handlers.py`:

```python
async def test_the_receipt_is_recorded_before_the_outcome_is_spoken(fixed_clock):
    """The order is the honest one: the ledger answers, the receipt is written, then the
    sentence that asserts it goes out. A ledger that returns nothing gets no receipt and the
    refusal wording, which asserts nothing."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    llm = _LLM()
    await _make_handler(s)(_Params("file_request", {}, llm))
    assert s.receipts == [f"item:{ledger.items[0].id}"]
```

`tests/test_driver.py`:

```python
async def test_a_text_reply_that_claims_a_filing_with_nothing_filed_is_retracted(fixed_clock):
    """The same rule on SMS. The model called no tool and asserted a receipt."""
    from spatalk.brain.driver import Brain, FakeLLM, LLMResponse

    llm = FakeLLM([LLMResponse(text="I've passed that to the team for you.", tool_calls=[])])
    ...  # the file's existing _brain/_ref helpers
    r = await brain.turn(ref, [], "can someone call me")
    assert r.guard_blocked is True
    assert r.reply.startswith(ref.tenant.scripts.cannot_complete.split(".")[0])
```

- [ ] **Step 2: Run to see them fail**

Run: `... -m pytest -q tests/test_structural_honesty.py tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_driver.py`
Expected: the new cases FAIL — `AttributeError: 'VoiceSession' object has no attribute 'receipts'`; `assert methods == ["_egress"]` fails with `['_speak', '_emit', 'process_frame']`; the paraphrased claim goes out unretracted.

- [ ] **Step 3: The receipt register on the session**

```python
    # What this call can actually show for itself: `item:<id>` for every item the ledger
    # issued, `link:<service_id>` for a booking link the provider accepted, `transfer:<n>`
    # for a leg the carrier took, `platform:<ref>` for a Tier A completion. Receipt-or-
    # retract (memo §3.3) reads the length of this list and nothing else — the refs are here
    # so a log line can name one, never so a sentence can. Per call, never persisted.
    receipts: list[str] = field(default_factory=list)

    def remember_receipt(self, kind: str, ref: str) -> None:
        """Record proof of an action, before the sentence that asserts it is spoken."""
        if kind not in ("item", "link", "transfer", "platform"):
            raise ValueError(f"unknown receipt kind {kind!r}")
        self.receipts.append(f"{kind}:{ref}")
```

- [ ] **Step 4: The single egress**

Rewrite `OutputGuardProcessor`'s speaking half. `_speak` and the inline `guard()` in `_emit` go; `_egress` and `_retract` replace them. Keep `_emit`'s sentence-splitting, `_dropping` and `_held` logic exactly as it is — `_emit` becomes a *caller* of `_egress`.

```python
    def __init__(self, session: VoiceSession):
        ...
        # Guard-owned, not a parameter: set only while the guard's own replacement is on its
        # way out, because `cannot_complete` asserts a receipt itself and would otherwise
        # retract the retraction. Nothing outside this class can set it, and there is no
        # `skip_guard` argument for anything outside this class to pass (memo §3.1).
        self._retracting = False

    async def _egress(self, text: str, *, model_words: bool, append_to_context: bool = True) -> None:
        """The only path from this processor to TTS.

        Everything the caller hears on a call passes through here — the model's own words,
        a tenant script a tool handler or the rules gate pushed from upstream, the step
        question, the guard's own replacement — and everything that passes through here is
        guarded first. That is the whole of non-negotiable 1's "every model utterance passes
        `guard()` before reaching a channel", made structural.
        """
        text = drop_unknown_tags(text.strip())
        if not text:
            return
        if not self._retracting:
            g = guard(
                text, self._s.has_completed, self._s.cfg,
                replacement="", receipts=len(self._s.receipts),
            )
            if g.blocked:
                await self._retract(text, g)
                return
        self._spoke_this_turn = True
        self._s.remember_spoken(text)
        frame = (
            LLMTextFrame(text=text + " ")     # the trailing space is for the TTS aggregator
            if model_words
            else TTSSpeakFrame(text=text, append_to_context=append_to_context)
        )
        await self.push_frame(frame)

    async def _retract(self, sentence: str, g) -> None:
        """File a real item, then speak the tenant's replacement, so the sentence the caller
        hears is true. Everything after a blocked sentence belonged to the same false claim,
        so the rest of the turn is dropped rather than half-spoken."""
        self._dropping = True
        self._held = None
        self._s.guard_blocks += 1
        self._s.band = max(self._s.band, 2)
        now = self._s.clock.now()
        try:
            out = await self._s.caps.capture(self._s.ref, draft_from(Slots(flow="question"), self._s.cfg))
            self._s.remember_receipt("item", str(out.item_id))
            spoken = render_script("cannot_complete", self._s.cfg, now, urgent=False)
        except Exception as e:  # noqa: BLE001  ledger down: nothing was filed, promise nothing
            logger.exception("guard could not file the blocked claim: {}", e)
            spoken = render(Refused(reason="unavailable"), self._s.cfg, now, channel=self._s.ref.channel)
        logger.warning("guard blocked {} ({}): {!r}", g.family, g.matched, sentence)
        self._retracting = True
        try:
            await self._egress(spoken, model_words=True)
        finally:
            self._retracting = False
```

`_retract` speaks with `model_words=True` so the replacement takes the same frame the blocked sentence would have taken, and the existing tests that read `LLMTextFrame` keep reading it there.

In `process_frame`, the pass-through branch for a `TTSSpeakFrame` arriving from upstream becomes an egress instead of a push:

```python
            if isinstance(frame, TTSSpeakFrame) and direction == FrameDirection.DOWNSTREAM:
                # Fixed scripts (the disclosure, outcomes, confirmations) reach TTS through
                # the same one door as the model's words.
                await self._egress(
                    frame.text, model_words=False, append_to_context=frame.append_to_context
                )
                return
            await self.push_frame(frame, direction)
```

`_retracting` is also set around the `TTSSpeakFrame` the processor pushes for the step question, because a script is not a model utterance and the runtime's own question has no receipt to show — **no.** Do not do that. The step questions carry no receipt phrase (Task 1 Step 1 pins it), so they pass the guard on their own merits, and giving them a bypass would be a `skip_guard` by another name.

- [ ] **Step 5: The receipt at the ledger's own word**

Three sites, all of which already hold the outcome object:

`spatalk/voice/handlers.py`, in `_make_handler` where `Captured` is already inspected for the band:

```python
        if isinstance(outcome, Captured):
            session.remember_receipt("item", str(outcome.item_id))
            session.band = 3 if outcome.item_type.startswith("escalation_") else max(session.band, 2)
        elif isinstance(outcome, LinkSent):
            session.remember_receipt("link", outcome.service_id)
        elif isinstance(outcome, Completed):
            session.remember_receipt("platform", outcome.platform_ref)
```

`_make_transfer_handler`: `session.remember_receipt("transfer", outcome.number_masked)` on the `Transferred` branch and `remember_receipt("item", str(outcome.item_id))` on the `Captured` fallback — before the frame that asserts it.

`spatalk/voice/processors.py`, `RulesGateProcessor`, on the successful `caps.escalate` branch: `self._s.remember_receipt("item", str(out.item_id))` immediately after the `logger.info`, before the `push_frame`. The `Refused` branch records nothing, which is correct: `refuse_unavailable` asserts nothing.

`Completed` must not be imported into `handlers.py` if it is not already — check first. It is not Tier C, so the import is legal, but prefer `getattr(outcome, "platform_ref", None)` over a new import if the file does not already carry it, and record the receipt from `outcome.kind == "completed"`.

- [ ] **Step 6: The text driver**

In `Brain.turn`, `guard()` is called after the tool loop, so the turn's own outcomes are in hand:

```python
            receipts = sum(
                1 for o in outcomes if o.kind in ("captured", "link_sent", "transferred", "completed")
            )
            g = guard(resp.text, has_completed, cfg, replacement="", receipts=receipts)
```

This is the turn's receipts, not the conversation's, and that is a **deliberate deviation to record**: a text reply that restates a filing made on an earlier turn is retracted (and files a second item). It has not been seen, the model is told "say nothing about the result", and the alternative — threading a conversation-wide count from `text/service.py` — is a change to a second driver for a hazard nobody has hit. Note it in the Task 9 report as the one place phase A is stricter than it needs to be, and as phase B's job when both drivers change together.

- [ ] **Step 7: Run the voice and text suites**

Run: `... -m pytest -q tests/test_structural_honesty.py tests/test_guard.py tests/test_renderer.py tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_voice_steps.py tests/test_voice_turns.py tests/test_voice_echo.py tests/test_voice_filler.py tests/test_voice_transfer.py tests/test_driver.py tests/test_driver_flow.py tests/test_text_service.py tests/test_text_scenarios.py tests/test_text_sms.py tests/test_tier_c.py`
Expected: PASS. Two things will need attention and neither is a licence to weaken a test: a test that pushed a `TTSSpeakFrame` through the guard and read the *same frame object* out the other side now reads an equal-but-new frame (assert on `.text`); and a fixture whose canned model text asserts a receipt with nothing filed is now retracted (fix the fixture's wording, or give it a receipt).

- [ ] **Step 8: Commit**

```bash
git add spatalk/voice/processors.py spatalk/voice/session.py spatalk/voice/handlers.py \
        spatalk/brain/driver.py tests/test_voice_processors.py tests/test_voice_handlers.py \
        tests/test_structural_honesty.py tests/test_driver.py
git commit -m "feat(voice): one door to the wire, and no outcome sentence without a receipt"
```

**Done when:** `test_only_the_egress_function_can_speak_on_a_call` passes and `grep -n "skip_guard" spatalk` is empty; a paraphrased outcome claim is retracted and the retraction is not retracted; a receipt exists before every sentence that asserts one; `ruff check` clean.

**Cost:** CA$0.00/min. No model call added or removed. A retraction swaps a model sentence for a script of similar length; the item it files costs nothing in provider terms. The only measurable change is fewer characters spoken on the calls where the model was about to lie, which is a saving nobody should plan on.

---

### Task 3: Rung 0 — the signal log and the turn-metrics observer

Memo §6 rung 0; OSS §8.4(a); LIT §6.3 (the LEGO corpus's 53 logged parameters, "this is SpaTalk's log schema") and §6.6. Lands before A3 and A4 so those tasks record their own signals as they arrive, and so the founder's next call produces the numbers the phase-C trouble score is built from.

**Files:**
- Create: `spatalk/ops/signals.py`
- Modify: `spatalk/voice/session.py`, `spatalk/voice/observers.py`, `spatalk/voice/pipeline.py`, `spatalk/voice/processors.py`
- Test: `tests/test_ops_signals.py` (new), `tests/test_voice_processors.py` (extended), `tests/test_structural_honesty.py` (extended)

**Interfaces:**
- Produces: `spatalk.ops.signals.SIGNAL_KINDS: tuple[str, ...]`; `spatalk.ops.signals.DETAIL_KEYS: frozenset[str]`; `spatalk.ops.signals.CLOSED_VALUE: re.Pattern`; `spatalk.ops.signals.Signal` (pydantic, frozen: `kind: str`, `turn: int`, `detail: dict[str, float | int | bool | str]`); `spatalk.ops.signals.SignalLog` with `turn: int`, `next_turn() -> None`, `record(kind: str, **detail) -> None`, `counts() -> dict[str, int]`, `as_json() -> dict`; `spatalk.ops.signals.signals_for(before: Slots, after: Slots) -> list[tuple[str, dict]]` (pure); `spatalk.ops.signals.MAX_SIGNALS: int = 200`; `VoiceSession.signals: SignalLog`; `VoiceSession.record_signal(kind: str, **detail) -> None`; `spatalk.voice.observers.TurnSignalObserver`.
- Consumes: `spatalk.brain.flow.Slots`, `spatalk.brain.flow.step_question`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ops_signals.py`:

```python
"""Rung 0 of the evaluation ladder (memo §6; LIT §6.6).

Every signal here is free to record and needs no model. Together they are the only thing
that turns "it isn't as human sounding" into a number, and they are the inputs the phase-C
trouble score reads. The hard rule the first test pins: a signal is a count and a closed
label, never a word anybody said.
"""


def test_a_signal_can_never_carry_a_word_anybody_said():
    import pytest

    from spatalk.ops.signals import SignalLog

    log = SignalLog()
    log.record("repeat", script="ask_service")
    log.record("turn_prediction", is_complete=True, probability=0.91, ms=42)
    with pytest.raises(ValueError):
        log.record("repeat", script="what did you have in mind?")   # a sentence, not a key
    with pytest.raises(ValueError):
        log.record("repeat", text="I have a rash after my peel")    # not a detail key at all
    with pytest.raises(ValueError):
        log.record("nonsense", script="ask_service")                # not a kind


def test_counts_roll_up_and_barge_in_and_repeat_is_derived():
    from spatalk.ops.signals import SignalLog

    log = SignalLog()
    log.next_turn()
    log.record("bargein")
    log.next_turn()
    log.record("caller_repeat", similarity=0.94)
    log.next_turn()
    log.record("caller_repeat", similarity=0.91)
    c = log.counts()
    assert c["bargein"] == 1 and c["caller_repeat"] == 2
    # The signal that predicted dissatisfaction in deployed systems: the caller was cut off
    # and said it again. Derived, so it cannot drift from its two parts.
    assert c["bargein_repeat"] == 1


def test_the_log_is_bounded_and_serialises_to_counts_plus_the_tail():
    from spatalk.ops.signals import MAX_SIGNALS, SignalLog

    log = SignalLog()
    for _ in range(MAX_SIGNALS + 50):
        log.record("repeat", script="ask_name")
    doc = log.as_json()
    assert doc["counts"]["repeat"] == MAX_SIGNALS + 50, "counts are exact"
    assert len(doc["signals"]) == MAX_SIGNALS, "the event list is capped"
    assert doc["turns"] == log.turn


def test_a_new_miss_and_a_new_confirmation_are_repairs():
    """`flow.apply` is pure and cannot log, so the drivers derive the repair from what it
    returned. One pure function, two callers, one definition of a repair."""
    from spatalk.brain.flow import Pending, Slots
    from spatalk.ops.signals import signals_for

    before = Slots(flow="new_booking", returning_client=True)
    missed = before.miss("practitioner")
    assert signals_for(before, missed) == [("repair", {"datum": "practitioner"})]

    pending = before.with_(pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"))
    assert signals_for(before, pending) == [("repair", {"datum": "practitioner"})]
    assert signals_for(before, before) == []
    # A slot that filled is not a repair.
    assert signals_for(before, before.with_(practitioner="any")) == []
```

`tests/test_voice_processors.py`:

```python
async def test_a_caller_who_repeats_himself_is_recorded(fixed_clock):
    """Sandbank et al.: repetition and re-prompt counts are the cheapest members of the
    feature family that added about 20% F1 to failure detection. The comparison happens in
    memory and only its similarity is kept."""
    from pipecat.frames.frames import TranscriptionFrame

    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    proc = RulesGateProcessor(session)
    pushed = []
    proc.push_frame = _capture(pushed)
    for text in ("can you book me that facial", "can you book me that facial, the mesojet one"):
        await proc.process_frame(
            TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM
        )
    assert session.signals.counts()["caller_repeat"] == 1
    assert session.signals.turn == 2
    for s in session.signals.as_json()["signals"]:
        assert set(s["detail"]) <= {"similarity"}


async def test_the_turn_analysers_verdict_is_recorded_and_so_is_its_absence(fixed_clock):
    """OSS §8.4(a): five fields, free, and the prerequisite for every turn-taking decision.
    The silence fallback emits no prediction at all — verified in the installed source: on a
    timeout `_process_speech_segment` returns `result_data = None` and the strategy pushes no
    `MetricsFrame` — so "the fallback fired" is a turn with no verdict, and that is the shape
    this records."""
    from pipecat.frames.frames import MetricsFrame, UserStoppedSpeakingFrame
    from pipecat.metrics.metrics import TurnMetricsData
    from pipecat.observers.base_observer import FramePushed

    from spatalk.voice.observers import TurnSignalObserver

    session, _ = _session(fixed_clock)
    obs = TurnSignalObserver(session)
    md = TurnMetricsData(
        processor="BaseSmartTurn", is_complete=False, probability=0.22, e2e_processing_time_ms=13.4
    )
    await obs.on_push_frame(_pushed(MetricsFrame(data=[md])))
    await obs.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    await obs.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    c = session.signals.counts()
    assert c["turn_prediction"] == 1 and c["turn_no_prediction"] == 1
    detail = session.signals.as_json()["signals"][0]["detail"]
    assert detail["is_complete"] is False and detail["probability"] == 0.22 and detail["ms"] == 13
```

`_pushed` is a one-line helper building a `FramePushed` the way `tests/test_ops_latency.py` already does for `UsageObserver`; read that file and reuse its helper rather than inventing a second one.

`tests/test_structural_honesty.py`:

```python
def test_the_signal_log_is_a_second_place_free_text_cannot_reach():
    """The log is a new per-call record, so it gets the same fence the notes got."""
    from pathlib import Path as _Path

    from spatalk.ops.signals import CLOSED_VALUE, DETAIL_KEYS, SIGNAL_KINDS

    assert "text" not in DETAIL_KEYS and "said" not in DETAIL_KEYS and "notes" not in DETAIL_KEYS
    assert CLOSED_VALUE.pattern == r"^[a-z_]{1,40}$"
    src = (_Path(RUNTIME) / "spatalk" / "ops" / "signals.py").read_text(encoding="utf-8")
    for forbidden in ("TTSSpeakFrame", "render_script", "SmsPort", "send_text", "ItemDraft("):
        assert forbidden not in src, forbidden
    assert all(k == k.lower() and " " not in k for k in SIGNAL_KINDS)
```

- [ ] **Step 2: Run to see them fail**

Run: `... -m pytest -q tests/test_ops_signals.py tests/test_voice_processors.py tests/test_structural_honesty.py`
Expected: `ModuleNotFoundError: No module named 'spatalk.ops.signals'`.

- [ ] **Step 3: `spatalk/ops/signals.py`**

```python
SIGNAL_KINDS = (
    "repeat",              # the runtime was about to say words it had just said, on an unchanged record
    "reprompt",            # the same step asked again after a miss (an `*_again` script)
    "repair",              # the resolver could not settle a value: a confirmation, or a miss
    "tool_rejected",       # a call the step did not allow, answered in words the model can read
    "model_rerun",         # the turn was handed back so the model could word the question
    "digression",          # `answer_question`: the caller asked something else mid-step
    "bargein",             # the caller interrupted the assistant
    "caller_repeat",       # the caller's words repeated their previous turn
    "guard_block",         # the guard replaced a sentence
    "turn_prediction",     # the turn analyser returned a verdict, with its probability
    "turn_no_prediction",  # the turn closed on the silence fallback, with no verdict
)

# Everything a signal may carry. There is no key here that could hold a sentence, and the
# one below rejects any value that looks like one. This is the same fence non-negotiable 2
# puts round a tracked item, applied to the only other per-call record the runtime keeps.
DETAIL_KEYS = frozenset({
    "reason", "tool", "script", "datum", "step", "family",
    "probability", "is_complete", "ms", "similarity",
})
CLOSED_VALUE = re.compile(r"^[a-z_]{1,40}$")
MAX_SIGNALS = 200
```

`SignalLog.record` validates the kind, every detail key, and every string value against `CLOSED_VALUE`; numbers are coerced (`float` for `probability`/`similarity`, `int` for `ms`) and rounded to two places / whole milliseconds. Counts are kept in a `Counter` that is never capped; only the event list is, so `as_json()["counts"]` stays exact on a long call. `counts()` adds the derived `bargein_repeat`: the number of `caller_repeat` signals whose `turn` is the turn of a `bargein` or the one after it.

`signals_for(before, after)` is pure and covers exactly two shapes, both of which are a repair in the literature's sense (LIT R3): a miss counter that went up, and a `Pending` that appeared. It returns `("repair", {"datum": <slot>})` and nothing else — it is not a general diff, and a slot that *filled* is not a repair.

- [ ] **Step 4: The session and the recording sites**

`VoiceSession`: `signals: SignalLog = field(default_factory=SignalLog)` and a `record_signal(self, kind, **detail)` one-liner that forwards, so the processors do not reach two levels deep.

`RulesGateProcessor.process_frame`, on a final `TranscriptionFrame` — beside the existing `idle_nudges`/`ignored_tools` reset:

```python
            self._s.signals.next_turn()
            previous, self._last_final = self._last_final, frame.text
            if previous:
                similarity = fuzz.ratio(previous.lower(), frame.text.lower()) / 100.0
                if similarity >= CALLER_REPEAT:
                    self._s.record_signal("caller_repeat", similarity=similarity)
```

`CALLER_REPEAT = 0.80`, beside `ECHO_TAIL_SECS`, with `rapidfuzz.fuzz` already a dependency. `self._last_final` lives on the processor for one turn, exactly as `recent_bot_text` does for the assistant's side, and is never persisted.

`OutputGuardProcessor`: `record_signal("guard_block", family=g.family)` in `_retract`; `record_signal("bargein")` on `InterruptionFrame`; `record_signal("repeat", script=key)` where `asked_already` suppresses a question — the key comes from `step_question(next_step(...), ...)[0]`, which already exists today, so this task does not need Task 6's `open_question`. Where `step_question` returns a key ending in `_again`, record `reprompt` with the same key at the moment it is spoken.

- [ ] **Step 5: `TurnSignalObserver`**

In `spatalk/voice/observers.py`, a third observer beside `UsageObserver` and `TurnLatencyObserver`, with its own frame-id `_seen` set (a `MetricsFrame` is pushed once per processor hop, which is what mis-metered the founder's call by 8×):

```python
class TurnSignalObserver(BaseObserver):
    """What the turn analyser thought, and when it never got to think.

    `TurnMetricsData` carries `is_complete`, `probability` and `e2e_processing_time_ms`; the
    silence fallback carries nothing at all, because on a timeout the analyser returns no
    metrics and the turn strategy pushes no `MetricsFrame`. So a `UserStoppedSpeakingFrame`
    with no verdict since the last one *is* the fallback firing, and that is the reading
    `TURN_END_FALLBACK_SECS` needs before anyone touches it (voice-regression-V1 refused to
    tune it from a desk; this is the instrument that ends the argument).
    """
```

Register it in `pipeline.py`: `observers=[UsageObserver(session), TurnLatencyObserver(session), TurnSignalObserver(session)]`.

- [ ] **Step 6: Run**

Run: `... -m pytest -q tests/test_ops_signals.py tests/test_voice_processors.py tests/test_structural_honesty.py tests/test_ops_latency.py tests/test_voice_turns.py tests/test_smoke_imports.py`
Expected: PASS. `tests/test_ops_latency.py::test_the_eval_bot_runs_the_production_pipeline_in_the_production_order` may assert the observer list; extend it to three rather than loosening it.

- [ ] **Step 7: Commit**

```bash
git add spatalk/ops/signals.py spatalk/voice/session.py spatalk/voice/observers.py \
        spatalk/voice/pipeline.py spatalk/voice/processors.py \
        tests/test_ops_signals.py tests/test_voice_processors.py tests/test_structural_honesty.py
git commit -m "feat(ops): rung zero — every repeat, repair and turn verdict is an event on the call"
```

**Done when:** the signal log refuses a sentence and an unknown kind; `bargein_repeat` is derived, not stored; the turn analyser's verdict and its absence are both recorded; the log holds no caller or model words anywhere; `ruff check` clean.

**Cost:** CA$0.00/min. No model call, no spoken character, no database write on the hot path (Task 7 writes once at the end of the call).

---

### Task 4: `answer_question` — the side question gets a turn of its own

The single change that fixes the 01:40 call (memo §2; OSS §8.3(a), `global_functions` in Flows, `ToolScope.GLOBAL` in Bolna, `KnowledgeAnswerCommand` in Rasa; LIT R6, Grosz & Sidner's stack of focus spaces).

**Files:**
- Modify: `spatalk/brain/tools.py`, `spatalk/brain/flow.py`, `spatalk/voice/handlers.py`, `spatalk/voice/processors.py`, `spatalk/brain/driver.py`
- Test: `tests/test_flow_apply.py`, `tests/test_flow_tools.py`, `tests/test_tools_prompt.py`, `tests/test_voice_steps.py`, `tests/test_structural_honesty.py`

**Interfaces:**
- Produces: `"answer_question"` in `spatalk.brain.tools.TOOL_NAMES` and in `always_tools(cfg, transfer_enabled)`; `slot_tool("answer_question", cfg) -> FunctionSchema` with `properties == {}` and `required == []`; `Slots.digression: Step | None = None`; `spatalk.brain.flow.apply(..., "answer_question", {}, ...) -> Applied(slots=slots.with_(digression=<open step>), model_speaks=True)`; `spatalk.brain.flow.pop_digression(slots: Slots, cfg: TenantConfig, channel: str) -> Slots`.
- Consumes: `Step`, `next_step`.

- [ ] **Step 1: Write the failing tests**

`tests/test_flow_apply.py`:

```python
def test_answer_question_writes_nothing_and_pushes_one_frame():
    """Founder call 2026-09-11 01:40. "Uh, what was the facial one again?" had nowhere to go
    but `choose_service`, and the resolver matched the generic `facial` entry as exact. The
    tool that fixes it takes no arguments and writes nothing: its only effect is to record
    what the runtime was about to ask and hand the turn to the model."""
    from spatalk.brain.flow import Slots, Step, apply, next_step

    cfg = _cfg()
    before = Slots(flow="new_booking", returning_client=False, offers_done=True)
    assert next_step(before, cfg, "voice") == Step.SERVICE
    a = apply(before, "answer_question", {}, cfg, "voice", "+19055550101")
    assert a.ignored is False and a.say == () and a.file is False and a.send_link is False
    assert a.model_speaks is True
    assert a.slots.digression == Step.SERVICE
    # Not one slot moved, and the open step is where it was.
    assert a.slots.with_(digression=None) == before
    assert next_step(a.slots, cfg, "voice") == Step.SERVICE


def test_the_frame_pops_when_the_record_is_still_at_the_same_step_and_is_dropped_when_it_moved():
    """Resume by completion criterion, not by re-asking (RavenClaw, not Rasa): a caller who
    answered the open question *inside* the side question does not get asked it again."""
    from spatalk.brain.flow import Slots, Step, pop_digression

    cfg = _cfg()
    opened = Slots(flow="new_booking", returning_client=False, offers_done=True, digression=Step.SERVICE)
    assert pop_digression(opened, cfg, "voice").digression is None
    moved = opened.with_(service_id="classic_facial")
    assert pop_digression(moved, cfg, "voice").digression is None
    assert pop_digression(moved, cfg, "voice").service_id == "classic_facial"


def test_the_tool_is_offered_at_every_step_and_carries_no_argument():
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    for step in Step:
        tool = next(
            t for t in step_tools(step, Slots(flow="new_booking"), cfg, "voice", transfer_enabled=True)
            if t.name == "answer_question"
        )
        assert tool.properties == {} and tool.required == []
```

`tests/test_tools_prompt.py::test_the_qa_tool_set_is_start_request_and_the_always_tools` **moves** — the QA set becomes `["start_request", "escalate", "end_conversation", "answer_question"]`. Extend the assertion; keep the free-text check underneath it exactly as it is.

`tests/test_voice_steps.py`:

```python
async def test_a_side_question_hands_the_turn_over_and_says_nothing(fixed_clock):
    from spatalk.brain.flow import Slots, Step
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    llm = _LLM()
    params = _Params("answer_question", {}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [] and ledger.items == []
    assert s.slots.digression == Step.SERVICE and s.slots.service_id is None
    assert params.results[0][1].run_llm is True
    assert s.signals.counts()["digression"] == 1
    # The brief the model is about to read names what the runtime was about to ask.
    brief = s.context.messages[0]["content"]
    assert "asked something else" in brief and "which treatment" in brief
```

- [ ] **Step 2: Run to see them fail**

Run: `... -m pytest -q tests/test_flow_apply.py tests/test_flow_tools.py tests/test_tools_prompt.py tests/test_voice_steps.py`
Expected: FAIL — `ValueError: answer_question` from `slot_tool`; `Slots` has no `digression`.

- [ ] **Step 3: The tool**

In `tools.py`, add `"answer_question"` to `TOOL_NAMES` (after `"end_conversation"`, so the QA list order is stable) and to `always_tools` between `end_conversation` and the conditional transfer. The description, verbatim:

```python
        FunctionSchema(
            name="answer_question",
            description=(
                "The caller asked you something else — a price, what a treatment is, hours, "
                "or a repeat of something you said. Call this and then answer them in your "
                "own words from the facts. It records nothing and changes nothing about "
                "their request; it only gives you the turn. Do not call it twice in a row, "
                "and never use it to record an answer to the question the system just asked."
            ),
            properties={},
            required=[],
        ),
```

No argument, no free text, nothing widened: non-negotiable 2 is untouched and `tests/test_structural_honesty.py::test_no_tool_schema_has_a_notes_parameter` covers it for free.

- [ ] **Step 4: The frame**

On `Slots`:

```python
    # A side question the caller asked mid-step, and the step it interrupted. One frame, not
    # a stack: the stack is phase B, and one frame is all `answer_question` needs (memo §2,
    # LIT R6). It is a closed value — a `Step` — and it never reaches an item: `draft_from`
    # reads named slots and this is not one of them.
    digression: Step | None = None
```

In `_apply`, before the `_tool_allowed` check (it is an always-tool, so it is allowed at every step, but keep it beside `escalate` and `end_conversation` where the reader expects it):

```python
    if name == "answer_question":
        if slots.digression is not None:
            return _reject("already_yours", name, step, slots, cfg, channel)   # Task 5
        return Applied(slots=slots.with_(digression=step), model_speaks=True)
```

Until Task 5 lands, the `already_yours` branch is `Applied(slots=slots, ignored=True)`; Task 5 replaces it. Say so in the commit body rather than leaving a `TODO`.

```python
def pop_digression(slots: Slots, cfg: TenantConfig, channel: str) -> Slots:
    """Close the side question. The frame is dropped whether or not the open step is still
    the one it interrupted: a caller who answered the question inside their own aside has
    already moved the record, and `next_step` skips a filled slot, so there is nothing to
    resume (RavenClaw's completion criterion rather than Rasa's re-ask)."""
    return slots if slots.digression is None else slots.with_(digression=None)
```

- [ ] **Step 5: The handler and the pop**

`handlers.py`: `answer_question` needs no `run_tool` — it writes nothing and speaks nothing. Handle it ahead of the rejection check:

```python
        if params.function_name == "answer_question" and session.slots.digression is None:
            session.slots = session.slots.with_(digression=next_step(session.slots, session.cfg, "voice"))
            session.record_signal("digression", step=session.slots.digression.value)
            sync_context(session, now)
            await params.result_callback(
                {"spoken": False, "outcome": "none", "ignored": False},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
```

The pop happens where the model's turn ends and the runtime has the full picture — `OutputGuardProcessor`, in the `LLMFullResponseEndFrame` branch, after the question decision:

```python
            if self._s.slots.digression is not None and self._spoke_this_turn:
                # `_spoke_this_turn` is set inside Task 2's `_egress`. The narrow fix removed it
                # from the *repeat suppression* condition, deliberately; it is still the right
                # test for "did the model actually answer the side question".
                self._s.slots = pop_digression(self._s.slots, self._s.cfg, "voice")
```

`Brain.turn` (text) pops the same way, once the reply is assembled: `slots = pop_digression(slots, cfg, ref.channel)` immediately before the `ended_flow` reset. On text the model both answers and calls the tool in one completion, so the frame lives for exactly one turn — which is correct, and is the honest reason A4 is voice-only.

- [ ] **Step 6: The brief line**

In `step_message`, one branch ahead of the general case (Task 6 rewrites the general case; this branch survives it):

```python
    if slots.digression is not None:
        return (
            f"{STEP_MARKER} {known_text}They asked something else. Answer it from the facts "
            "in one or two sentences, then ask again, in your own words, for "
            f"{_missing_description(step, slots, cfg, channel)}, and put their answer in "
            f"{tool}. Do not call answer_question again."
        )
```

Task 6 replaces `_missing_description` with `readiness().missing.description`; until it lands, a small private helper over the same strings is fine and is deleted in Task 6. The phrase "which treatment" that the Task 4 test asserts comes from the SERVICE step's description, so the two tasks must agree on that string: **"which treatment they want, from the SERVICES list above"**.

- [ ] **Step 7: Run**

Run: `... -m pytest -q tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_flow_draft.py tests/test_tools_prompt.py tests/test_voice_steps.py tests/test_voice_handlers.py tests/test_structural_honesty.py tests/test_driver_flow.py tests/test_text_service.py tests/test_prompt_budget.py`
Expected: PASS. `tests/test_prompt_budget.py::test_the_static_half_of_the_request_stays_inside_its_budget` gains about 68 tokens from the new declaration and must stay inside `5_000 < tokens < 6_500`; if it does not, the declaration is too long — shorten it, do not raise the band.

- [ ] **Step 8: Commit**

```bash
git add spatalk/brain/tools.py spatalk/brain/flow.py spatalk/voice/handlers.py \
        spatalk/voice/processors.py spatalk/brain/driver.py tests/
git commit -m "feat(brain): a side question gets a turn of its own, and writes nothing"
```

**Done when:** `answer_question` is offered at every step with no arguments; it writes no slot and speaks no line; the frame is pushed, the brief names what the runtime was about to ask, and the frame is gone by the next caller turn; nothing in `ItemDraft` or any tool schema widened.

**Cost:** +CA$0.0001/min, and that figure is the whole of it. The declaration adds ~250 characters (~68 tokens) to the static request: at 3 turns a minute, $0.30 per million uncached input tokens and 1.3896 CAD/USD, that is CA$0.000085 a call-minute. The handler's `run_llm=True` **replaces** the `run_llm=True` the narrow fix already spends on the first ignored tool of a turn, so the side question buys no new model call — which is why the memo's §5 "≈ 0" is right for A2 and, as Task 6 says plainly, not right for A4.

---

### Task 5: Readable rejections — `Readiness`, `Missing`, `Rejection`

OSS §8.1(e) and Parlant's `ToolInsights` / `MissingToolData`: an un-offered, premature or malformed call comes back as something the model can read, naming what is missing and the legal choices, so it cannot proceed believing it filed something.

**This task is an upgrade, not an introduction.** The narrow fix already put the mechanism on `main`: `Applied.rejection: str | None`, the fixed `flow.ANSWER_THE_QUESTION` dict of five sentences, `flow.tool_refusal(...) -> tuple[bool, str | None]`, and the handler's `result["rejection"]` with `run_llm=True`. What it does not have is Parlant's *shape* — a reason code, what the record is waiting on, and the legal choices — so the model is told "that tool is not available at this point" without being told what is. This task gives the field a structure and keeps everything around it byte-compatible:

- `Applied.rejection` changes type from `str | None` to `Rejection | None`. It stays one field with one job; there is no second field.
- `tool_refusal(...)` keeps its exact signature and return type — it renders the structure with `rejection_text` on the way out. The handler's call site and the payload key `"rejection"` do not move.
- `ANSWER_THE_QUESTION`'s five sentences are not thrown away: they become the reason-and-detail text `rejection_text` builds from, so nothing the model already reads gets worse, and the comment above the dict (why it is code and not `scripts.yaml`) stays exactly as written.
- `IGNORED_TOOL_RETRIES = 1` becomes `MAX_REJECTIONS_PER_TURN = 3`: the counter stops being the strategy and becomes only a ceiling.

**Files:**
- Modify: `spatalk/brain/flow.py`, `spatalk/voice/handlers.py`, `spatalk/brain/driver.py`
- Test: `tests/test_flow_rejections.py` (new), `tests/test_flow_apply.py` (extended), `tests/test_voice_steps.py` (moved), `tests/test_voice_handlers.py` (moved)

**Interfaces:**
- Produces:
  - `spatalk.brain.flow.Missing` (pydantic, frozen): `datum: str`, `description: str`, `choices: tuple[str, ...] = ()`, `tool: str`
  - `spatalk.brain.flow.Readiness` (pydantic, frozen): `step: Step`, `known: tuple[str, ...]`, `missing: Missing | None`, `tools: tuple[str, ...]`
  - `spatalk.brain.flow.readiness(slots: Slots, cfg: TenantConfig, channel: str) -> Readiness`
  - `spatalk.brain.flow.Rejection` (pydantic, frozen): `reason: Literal["not_offered", "premature", "bad_value", "already_yours"]`, `tool: str`, `offered: tuple[str, ...]`, `missing: Missing | None = None`, `detail: Literal["question_shaped", "unknown_kind", "empty_slot", "not_a_choice", "needs_yes_or_no", "name_it_instead"] | None = None`
  - `spatalk.brain.flow.rejection_text(r: Rejection) -> str`
  - `spatalk.brain.flow.tool_rejection(slots, name, args, cfg, channel, caller_phone) -> Rejection | None` (the structured sibling of the existing `tool_refusal`, which keeps its `tuple[bool, str | None]` contract)
  - `Applied.rejection: Rejection | None = None` — the existing field, re-typed. `ignored: bool` keeps its meaning and its truth value, so `tool_ignored`, `run_tool`, `_finalize` and every existing consumer are untouched.
  - `spatalk.voice.handlers.MAX_REJECTIONS_PER_TURN: int = 3`, replacing `IGNORED_TOOL_RETRIES = 1`
- Consumes: `spatalk.brain.resolve.is_question` — the narrow fix's predicate, kept exactly where it is. Change only what its two call sites in `_apply` (`choose_practitioner`, `choose_service`) return: `Applied(..., rejection=ANSWER_THE_QUESTION["service"])` becomes `_reject("bad_value", name, step, slots, cfg, channel, detail="question_shaped")`. **Do not write a second question-shaped check.**

- [ ] **Step 1: Write the failing tests**

`tests/test_flow_rejections.py`:

```python
"""A refusal the model can read (OSS §8.1(e); Parlant's `ToolInsights`).

Silence was the old answer and it cost the founder's call of 2026-09-10 four identical
questions: the model called a tool the step did not offer, nothing happened, nothing was
said, and it had no way to know why. Every rejection here names the tool, what the record is
waiting on, and what may be called instead — in closed values only. A rejection is a message
to the model. It is never spoken, never sent, and never written anywhere.
"""


def test_an_un_offered_tool_names_what_is_missing_and_what_is_legal():
    from spatalk.brain.flow import Slots, tool_rejection, rejection_text

    cfg = _cfg()
    r = tool_rejection(Slots(flow="new_booking"), "give_name", {"first_name": "Ellen"}, cfg, "voice", None)
    assert r is not None and r.reason == "not_offered" and r.tool == "give_name"
    assert r.missing.datum == "returning_client" and r.missing.tool == "answer"
    assert r.missing.choices == ("yes", "no")
    assert "answer_question" in r.offered and "give_name" not in r.offered
    text = rejection_text(r)
    assert "give_name" in text and "answer" in text and "yes" in text
    assert "nothing was recorded" in text.lower()


def test_filing_before_the_slots_are_filled_is_premature_not_merely_un_offered():
    """The distinction is worth the enum value: "not available" tells the model to try
    something else, "not yet, the record still needs X" tells it what to do."""
    from spatalk.brain.flow import Slots, tool_rejection, rejection_text

    cfg = _cfg()
    r = tool_rejection(Slots(flow="callback", returning_client=True), "file_request", {}, cfg, "voice", None)
    assert r.reason == "premature" and r.missing.datum == "name"
    assert "nothing was filed" in rejection_text(r).lower()


def test_a_malformed_value_says_which_way_it_was_wrong():
    from spatalk.brain.flow import Pending, Slots, tool_rejection

    cfg = _cfg()
    empty = tool_rejection(Slots(flow="new_booking", returning_client=True), "change_answer",
                           {"slot": "service"}, cfg, "voice", None)
    assert empty.reason == "bad_value" and empty.detail == "empty_slot"
    kind = tool_rejection(Slots(), "start_request", {"kind": "haircut"}, cfg, "voice", None)
    assert kind.reason == "bad_value" and kind.detail == "unknown_kind"
    which = Slots(flow="new_booking", returning_client=True,
                  pending=Pending(kind="which", slot="practitioner", candidates=("A B", "C D")))
    named = tool_rejection(which, "answer", {"value": "yes"}, cfg, "voice", None)
    assert named.reason == "bad_value" and named.detail == "name_it_instead"


def test_a_legal_call_earns_no_rejection():
    from spatalk.brain.flow import Slots, tool_rejection

    cfg = _cfg()
    assert tool_rejection(Slots(flow="new_booking"), "answer", {"value": "yes"}, cfg, "voice", None) is None
    assert tool_rejection(Slots(), "start_request", {"kind": "callback"}, cfg, "voice", None) is None
    assert tool_rejection(Slots(flow="new_booking"), "answer_question", {}, cfg, "voice", None) is None


def test_a_rejection_carries_no_caller_words_anywhere():
    """Structural. The model passed a sentence; nothing of it survives into the rejection."""
    from spatalk.brain.flow import Rejection, Slots, rejection_text, tool_rejection

    cfg = _cfg()
    said = "so what was the fifty dollar one you mentioned earlier"
    r = tool_rejection(Slots(flow="new_booking"), "choose_service", {"said": said}, cfg, "voice", None)
    assert r is not None
    blob = r.model_dump_json() + rejection_text(r)
    for word in ("fifty", "dollar", "mentioned", "earlier"):
        assert word not in blob.lower(), word
    assert set(Rejection.model_fields) == {"reason", "tool", "offered", "missing", "detail"}


def test_the_readiness_report_is_the_one_source_for_both_the_brief_and_the_rejection():
    """One function, two consumers: a rejection that named different choices from the brief
    would be a second policy, which is the thing the runtime exists not to have."""
    from spatalk.brain.flow import Slots, readiness, tool_rejection

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=True, practitioner="any")
    report = readiness(s, cfg, "voice")
    assert report.missing.datum == "service" and "treatment" in report.missing.description
    assert report.missing.tool == "choose_service" and "choose_service" in report.tools
    assert tool_rejection(s, "give_phone", {"digits": "9055550101"}, cfg, "voice", None).missing == report.missing
```

`tests/test_flow_apply.py` — the narrow fix's three cases at the end of the file (the question-shaped `said`, the refused `answer` value, the `change_answer` on an empty slot) assert `a.rejection and "question" in a.rejection.lower()`. `a.rejection` is now an object, so each becomes `"question" in rejection_text(a.rejection).lower()` plus the structure it now carries — `reason == "bad_value"` with `detail` `"question_shaped"`, `"not_a_choice"` and `"empty_slot"` respectively. Every existing assertion about what was *not* written stays. `test_change_answer_for_a_slot_that_holds_nothing_is_ignored` is extended the same way.

`tests/test_voice_steps.py::test_a_tool_the_step_did_not_offer_is_ignored_and_the_model_answers` — **moves.** Rename to `test_a_tool_the_step_did_not_offer_is_refused_in_words_the_model_can_read` and keep both halves of the old contract that still hold (nothing written, nothing filed, nothing spoken, the turn handed back), replacing the two-strike behaviour:

```python
async def test_a_tool_the_step_did_not_offer_is_refused_in_words_the_model_can_read(fixed_clock):
    """Was `…_is_ignored_and_the_model_answers`. The V1 behaviour — first call silent with
    the turn handed back, second call falls back to the fixed question — was the best a
    *silent* refusal could do. The model is now told why, every time, so the retry counter
    stops being the strategy and becomes only a ceiling (OSS §8.1(e)); the fourth rejection
    in one caller turn speaks the fixed question rather than buying a fourth model call."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import MAX_REJECTIONS_PER_TURN, _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    handler = _make_handler(s)
    for _ in range(MAX_REJECTIONS_PER_TURN):
        p = _Params("give_name", {"first_name": "Ellen"}, llm)
        await handler(p)
        assert s.slots.first_name is None and ledger.items == []
        assert _spoken(llm) == [] and p.results[0][1].run_llm is True
        reason = p.results[0][0]["rejection"]
        assert "give_name" in reason and "answer" in reason and "yes" in reason
    last = _Params("give_name", {"first_name": "Ellen"}, llm)
    await handler(last)
    assert _spoken(llm) == [s.cfg.scripts.ask_returning]
    assert last.results[0][1].run_llm is False
    assert s.signals.counts()["tool_rejected"] == MAX_REJECTIONS_PER_TURN + 1
```

`tests/test_voice_handlers.py` — three of the narrow fix's own cases are extended, none replaced. `test_an_ignored_tool_hands_the_turn_back_to_the_model` is renamed `…_is_refused_in_words_that_name_what_is_missing` and asserts the missing datum and the choices are in the payload, not only that a payload exists. `test_a_question_shaped_answer_hands_the_turn_back_with_a_reason` keeps every assertion and gains `"which treatment" in results[0][0]["rejection"]`. `test_the_ignored_budget_resets_when_the_caller_speaks` survives unchanged: the budget still resets on a final transcription, in `RulesGateProcessor`, and only its ceiling moved from 1 to 3.

- [ ] **Step 2: Run to see them fail**

Run: `... -m pytest -q tests/test_flow_rejections.py tests/test_flow_apply.py tests/test_voice_steps.py tests/test_voice_handlers.py`
Expected: `ImportError: cannot import name 'tool_rejection'`.

- [ ] **Step 3: `Missing` and `readiness()`**

The datum table lives in `flow.py` beside `STEP_TOOL`, which it mirrors. The descriptions are instructions to the model, not sentences the caller hears, which is why they are code and not `scripts.yaml` (non-negotiable 3 is about what is spoken). `choices` is given only where the closed set is genuinely short — a yes/no, the parts of the day, the route — and **never** for the practitioner or the treatment, whose lists are already in the static prompt and would be bought again on every turn:

```python
_MISSING: dict[Step, tuple[str, str, tuple[str, ...]]] = {
    Step.RETURNING: ("returning_client", "whether they have been in to the clinic before", ("yes", "no")),
    Step.OFFERS: ("offers", "whether they would like to hear the new-client offers", ("yes", "no")),
    Step.PRACTITIONER: ("practitioner", "who they would like to see: a name from the team in the facts, or anyone", ()),
    Step.SERVICE: ("service", "which treatment they want, from the SERVICES list above", ()),
    Step.NAME: ("name", "their first name", ()),
    Step.PHONE: ("phone", "the best number to reach them on", ()),
    Step.WINDOW: ("window", "which day or part of the day suits them", ("morning", "afternoon", "evening", "any")),
    Step.TEAM_NOTE: ("team_note", "whether there is anything the team should know before they call", ("yes", "no")),
    Step.ROUTE: ("route", "whether to text them the booking link or have the team call them", ("the link", "a call")),
}
```

Four cases `_MISSING` cannot express, which `readiness()` handles explicitly and which are exactly the four the model got wrong on the founder's calls:

- `Step.PHONE` with a caller id and no miss → `("phone", "whether the number they are calling from is the best one to reach them on", ("yes", "no"))`.
- `Step.NAME` on the `clinical` flow before `offer_accepted` → `("clinical_offer", "whether they would like the clinical team to reach out to them", ("yes", "no"))`.
- `slots.pending is not None` → `("confirmation", "a yes or no to the confirmation the system has just read back", ("yes", "no"))`, tool `answer` — except `pending.kind == "which"`, where the datum is the slot and the tool is its slot tool, because a choice between two is answered by naming one.
- `Step.QA` and `Step.COMPLETE` → `missing is None`.

`Readiness.known` is the existing `known` list from `step_message`, lifted out unchanged and returned as a tuple, so the brief's "Known:" line and the rejection agree by construction. `Readiness.tools` is `tuple(t.name for t in step_tools(...))`.

- [ ] **Step 4: `Rejection` and `rejection_text`**

`_apply` already routes five refusals through `ANSWER_THE_QUESTION`; four more are still bare `Applied(slots=slots, ignored=True)` (an unknown `start_request` kind, a `which` pending answered yes/no, the unreachable tail, and Task 4's `already_yours`). **All nine go through one constructor**, which is what makes the brief and the rejection agree by construction. `ignored` keeps its meaning and its truth value, so `tool_ignored`, `tool_refusal`, `run_tool`, `_finalize` and every existing test are untouched.

```python
def _reject(reason, tool, step, slots, cfg, channel, detail=None) -> Applied:
    report = readiness(slots, cfg, channel)
    return Applied(
        slots=slots,
        ignored=True,
        rejection=Rejection(
            reason=reason, tool=tool, offered=report.tools, missing=report.missing, detail=detail,
        ),
    )
```

`premature` rather than `not_offered` when the tool is `file_request` or `send_link`: both are absent from the step's tools only because the record is not ready, and the model needs the difference.

`rejection_text` renders Parlant's shape in three sentences, with no caller words in any of them. **`ANSWER_THE_QUESTION` is not deleted** — its five sentences become the reason and detail texts below, so the model's reading experience only gains the second and third sentences. Keep its comment ("Never caller-facing, so not tenant config: these sentences are read by a model, not spoken by the assistant") exactly where it is; it is the right note and it now covers `rejection_text` too.

```python
_DETAIL_TEXT = {
    "question_shaped": "what you passed was a question, not an answer",
    "unknown_kind": "that is not one of the kinds of request the system handles",
    "empty_slot": "there is nothing recorded in that slot to change",
    "not_a_choice": "that is not one of the values the system accepts",
    "needs_yes_or_no": "that question takes a yes or a no",
    "name_it_instead": "that question is answered by naming one of the two, not by yes or no",
}


def rejection_text(r: Rejection) -> str:
    """What the model is told, as the tool's result. Never spoken, never sent, never stored."""
    lines = []
    if r.reason == "premature":
        lines.append(f"{r.tool} is not available yet. Nothing was filed and nothing was recorded.")
    elif r.reason == "already_yours":
        lines.append(f"{r.tool} is already open: you have the turn. Answer them in your own words now.")
    elif r.reason == "bad_value":
        lines.append(f"{r.tool} did not take that: {_DETAIL_TEXT[r.detail]}. Nothing was recorded.")
    else:
        lines.append(f"{r.tool} is not available at this point. Nothing was recorded.")
    if r.missing is not None:
        want = f"The system is waiting on {r.missing.description}"
        if r.missing.choices:
            want += " — one of: " + ", ".join(r.missing.choices)
        lines.append(want + f". Put their answer in {r.missing.tool}.")
    lines.append("You may call: " + ", ".join(r.offered) + ".")
    return " ".join(lines)
```

- [ ] **Step 5: The handler**

`handlers.py`: `tool_ignored` gives way to `tool_rejection`, and `IGNORED_TOOL_RETRIES = 1` to `MAX_REJECTIONS_PER_TURN = 3`. `VoiceSession.ignored_tools` keeps its name — it still counts exactly what it says, `RulesGateProcessor` still resets it when the caller speaks, and renaming a field the V1 report told neighbours about buys nothing.

```python
MAX_REJECTIONS_PER_TURN = 3
```

with the comment that carries the reasoning:

```python
# A rejection is a message, not a retry: the model is told what was wrong and gets the turn
# back to act on it, which is what retires the old counter as a *strategy* (OSS §8.1(e)).
# What stays is a ceiling, because every handed-back turn is a model call and a model in a
# tight loop would otherwise spend the call while the caller hears nothing. Past the ceiling
# the runtime speaks the open question itself and stops re-running the model.
```

```python
        rejection = tool_rejection(
            session.slots, params.function_name, args, session.cfg,
            session.ref.channel, session.ref.caller_phone,
        )
        if rejection is not None:
            session.ignored_tools += 1
            session.record_signal("tool_rejected", reason=rejection.reason, tool=rejection.tool)
            logger.info("tool {} refused ({}): the model is told why", rejection.tool, rejection.reason)
            if session.ignored_tools > MAX_REJECTIONS_PER_TURN:
                question = next_question(session, now)
                if question:
                    session.remember_question(question)
                    await params.llm.push_frame(TTSSpeakFrame(text=question, append_to_context=True))
                await params.result_callback(
                    {"spoken": bool(question), "outcome": "none", "ignored": True},
                    properties=FunctionCallResultProperties(run_llm=False),
                )
                return
            await params.result_callback(
                {"rejection": rejection_text(rejection), "spoken": False, "outcome": "none", "ignored": True},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
```

The payload key stays `"rejection"`, exactly as the narrow fix shipped it, and `"ignored": True` stays beside it: nothing but the model reads either, and moving a key buys nothing.

`driver.py`: in `run_tool`, replace the bare `logger.warning("tool {} ignored …")` with the rejection's own words — `logger.info("tool {} refused ({}): {}", name, applied.rejection.reason, rejection_text(applied.rejection))` — and return the five-value tuple unchanged. The text path does not hand the rejection to the model (there is no tool-result round trip in a single completion); that is named in "Not in this plan".

- [ ] **Step 6: Re-home the narrow fix's three refusals**

`resolve.is_question` stays exactly where it is and is not touched. Its two call sites in `_apply` — the `choose_practitioner` and `choose_service` branches — swap `rejection=ANSWER_THE_QUESTION["practitioner"|"service"]` for `_reject("bad_value", name, step, slots, cfg, channel, detail="question_shaped")`, and the refused `answer` value swaps `ANSWER_THE_QUESTION["answer"]` for `detail="not_a_choice"`. The sentences the model reads must still contain the word "question" for the narrow fix's own assertions, which is why `_DETAIL_TEXT["question_shaped"]` says "a question, not an answer" — check that before running, not after.

`tests/test_resolve.py`'s two `is_question` cases are untouched: this task does not change the predicate's behaviour, only what the runtime does with its answer.

- [ ] **Step 7: Run**

Run: `... -m pytest -q tests/test_flow_rejections.py tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_flow_draft.py tests/test_voice_steps.py tests/test_voice_handlers.py tests/test_voice_processors.py tests/test_driver.py tests/test_driver_flow.py tests/test_lead_context_verification.py tests/test_resolve.py tests/test_real_model_findings.py`
Expected: PASS. `tests/test_lead_context_verification.py` unpacks `run_tool`'s five values — it must not have moved.

- [ ] **Step 8: Commit**

```bash
git add spatalk/brain/flow.py spatalk/voice/handlers.py spatalk/brain/driver.py tests/
git commit -m "feat(brain): a refused tool comes back in words, naming what is missing and what is legal"
```

**Done when:** every ignored path carries a `Rejection`; `Rejection` and `rejection_text` hold no caller words (the structural test proves it); `readiness()` is the single source of the missing datum for both the brief and the rejection; the ceiling speaks the fixed question instead of buying a fourth model call; `run_tool`'s five-value return and `Applied.ignored` are unchanged.

**Cost:** +CA$0.00002/min. The rejection text is ~40 tokens of tool result inside a turn the narrow fix already hands back, so it buys no new model call at the margin. The worst case is bounded by the ceiling: three extra calls in one caller turn is CA$0.0059 **once**, not per minute, and the `tool_rejected` count Task 3 records is what tells the founder whether it ever happens.

---

### Task 6: The model words the question — the readiness report, the prompt, the relaxed guard

OSS §8.2 and §8.4(f); LIT R1. The last task of phase A and the one that must not land before Tasks 1 and 2.

**Files:**
- Modify: `spatalk/brain/flow.py` (`OpenQuestion`, `open_question`, `step_message`), `spatalk/brain/prompt.py`, `spatalk/voice/steps.py`, `spatalk/voice/handlers.py`, `spatalk/voice/processors.py`
- Test: `tests/test_voice_processors.py` (three cases move, four survive), `tests/test_voice_steps.py` (one moves), `tests/test_flow_brief.py` (new), `tests/test_tools_prompt.py` (one moves), `tests/test_prompt_booking_flow.py` (one moves), `tests/test_prompt_budget.py` (must still pass)

**Interfaces:**
- Produces: `spatalk.brain.flow.OpenQuestion` (pydantic, frozen: `key: str`, `fills: dict`, `fixed: bool`); `spatalk.brain.flow.open_question(slots, cfg, channel) -> OpenQuestion | None` where `fixed is (slots.pending is not None)`; `spatalk.voice.steps.open_question_text(session, now) -> tuple[OpenQuestion, str] | None`; `spatalk.voice.steps.next_question(session, now) -> str | None` **unchanged in signature** — it stays the fallback; `VoiceSession.reran_this_turn: bool`.
- Consumes: `readiness()` and `Missing` from Task 5.

- [ ] **Step 1: Write the failing tests**

`tests/test_flow_brief.py`:

```python
"""The brief becomes a readiness report (OSS §8.2; LIT R1).

Today it ends "Do not ask a question yourself; one short acknowledgement at most", which is
the prompt half of the answering machine the founder heard. It becomes Parlant's two
sections — what is known, and what is missing with its legal choices — and it *invites* the
question instead of forbidding it. What the runtime keeps is which slot is open and what may
be stored; what it gives up is choosing the words.
"""


def test_the_brief_names_what_is_known_and_what_is_missing_and_asks_for_the_question():
    from spatalk.brain.flow import STEP_MARKER, Slots, Step, step_message

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis")
    brief = step_message(Step.SERVICE, s, cfg, "voice")
    assert brief.startswith(STEP_MARKER)
    assert "Known:" in brief and "returning client" in brief and "Helen" in brief
    assert "which treatment they want" in brief
    assert "in your own words" in brief and "choose_service" in brief
    assert "do not ask a question" not in brief.lower()
    assert "one short acknowledgement at most" not in brief


def test_the_brief_never_licenses_a_claim():
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    for step in Step:
        brief = step_message(step, Slots(flow="new_booking"), cfg, "voice")
        assert "answer_question" in brief or step in (Step.QA, Step.COMPLETE), step
        assert "the system speaks every outcome" in brief or step in (Step.QA, Step.COMPLETE), step


def test_the_name_and_number_steps_forbid_autocorrecting():
    """Vapi's anti-autocorrect rule, verbatim in effect: a recogniser's "payment" for Peyman
    is a transcription problem, and a model that tidies it up hides it (V1 open item 2)."""
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    name = step_message(Step.NAME, Slots(flow="callback", returning_client=True), cfg, "voice")
    assert "never modify" in name and "never autocorrect" in name and "never guess" in name


def test_a_pending_confirmation_is_the_runtimes_words_and_a_plain_step_question_is_not():
    """Phase A's split. A confirmation of a value the resolver is unsure of is wording the
    runtime still owns (candidates-not-verdicts is phase B); a plain step question is not."""
    from spatalk.brain.flow import Pending, Slots, open_question

    cfg = _cfg()
    plain = open_question(Slots(flow="new_booking", returning_client=True), cfg, "voice")
    assert plain.key == "ask_practitioner" and plain.fixed is False
    pending = Slots(
        flow="new_booking", returning_client=True,
        pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"),
    )
    confirm = open_question(pending, cfg, "voice")
    assert confirm.key == "confirm_match" and confirm.fixed is True
    assert confirm.fills == {"value": "Helen"}
```

`tests/test_voice_steps.py::test_a_slot_tool_speaks_the_next_question_and_never_reruns_the_llm` — **moves**:

```python
async def test_a_slot_tool_says_nothing_and_hands_the_turn_back_for_the_question(fixed_clock):
    """Was `…_speaks_the_next_question_and_never_reruns_the_llm`, which was the slot engine's
    invariant 4 in code: the runtime spoke the question and the model never got the turn. The
    memo's decision 1 replaces that invariant — the outcome sentence is still the tenant's,
    the question is the model's — so the handler speaks nothing here and re-runs the model
    with a fresh readiness report. `run_llm` flips from False to True, and that flip is the
    one cost item in phase A (see the plan's Task 6 cost note)."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    s, _ = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    params = _Params("answer", {"value": "yes"}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [], "no script; the model words the practitioner question"
    assert s.slots.returning_client is True and s.tool_called_this_turn
    assert params.results[0][1].run_llm is True
    assert s.signals.counts()["model_rerun"] == 1
    brief = s.context.messages[0]["content"]
    assert "who they would like to see" in brief


async def test_a_confirmation_is_still_the_runtimes_own_words(fixed_clock):
    """The other half of the split, and the reason phase A is safe: a value the resolver is
    unsure of is read back in the tenant's wording, with no second model call."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    s, _ = _session(fixed_clock)
    s.slots = Slots(flow="new_booking", returning_client=True)
    llm = _LLM()
    params = _Params("choose_practitioner", {"said": "Ellen"}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [s.cfg.scripts.confirm_match.format(value="Helen")]
    assert params.results[0][1].run_llm is False
    assert s.signals.counts()["repair"] == 1


async def test_the_outcome_line_is_still_spoken_and_buys_no_second_model_call(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    llm = _LLM()
    params = _Params("file_request", {}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm)[0].startswith("I've sent that to the team as a request")
    assert params.results[0][1].run_llm is False
```

`tests/test_voice_processors.py` — **three move, four survive**:

```python
async def test_the_models_own_question_is_spoken_when_the_runtime_has_none(fixed_clock):
    """Was `test_the_model_does_not_ask_a_question_while_a_flow_is_open`, and it was right
    for the runtime it was written against. Memo §3: "Then the trailing-question suppression
    from `voice-regression-V1` is relaxed, because it was right for a runtime that asked its
    own question on top and is wrong once the model owns the question." The V1 defect it was
    written for — two questions in one breath, the second identical on every turn — is now
    prevented at the source: the runtime asks nothing here."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("That's our fifty-dollar credit. "),
        LLMTextFrame("Would you like to hear about any of those?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["That's our fifty-dollar credit.", "Would you like to hear about any of those?"]
    assert [f for f in down if isinstance(f, TTSSpeakFrame)] == []


async def test_a_fixed_confirmation_still_beats_the_models_own_question(fixed_clock):
    """The one case the hold survives: a `Pending` is open, the wording is law, and the
    model's guess at it is dropped rather than asked alongside."""
    from spatalk.brain.flow import Pending, Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(
        flow="new_booking", returning_client=True,
        pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"),
    )
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Sure. "),
        LLMTextFrame("Did you want Ellen or Helen?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Sure."]
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.confirm_match.format(value="Helen")
    ]


async def test_a_tool_turn_never_lets_the_models_question_out(fixed_clock):
    """A question the model asks in the same breath as a tool call is one step behind the
    record — it was written before the tool moved anything — so it is dropped and the
    re-run's question carries the turn. Exactly one question a turn, still."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking")
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Got it. "),
        LLMTextFrame("Who would you like to see?"),
        FunctionCallInProgressFrame(
            function_name="answer", tool_call_id="1", arguments={"value": "yes"}
        ),
        LLMFullResponseEndFrame(),
    ]
    ...
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Got it."]
```

Read the file's existing `FunctionCallInProgressFrame` construction before copying the signature above; use whatever shape the file already uses.

Surviving unchanged, and each one must be run and seen to pass: `test_a_question_in_the_middle_of_an_answer_is_still_spoken`, `test_a_question_is_the_models_own_outside_a_flow`, `test_a_turn_that_is_only_a_question_is_not_left_silent`, `test_a_fragment_is_not_a_turn_and_its_words_are_kept`, and `test_a_silent_model_turn_gets_the_question_unless_it_was_just_asked` — the narrow fix's renamed and extended form of V1's silent-turn case, and the fallback A4 explicitly keeps. `test_the_step_question_is_not_repeated_word_for_word` and `test_the_step_question_comes_back_once_the_record_moves` survive, narrowed to the fallback path, and gain `assert session.signals.counts()["repeat"] == 1`. `test_no_question_is_repeated_when_a_tool_ran_this_turn` survives and becomes stronger: the handler now speaks no plain question at all, on any turn.

`tests/test_tools_prompt.py::test_prompt_hands_a_request_to_the_system` and `tests/test_prompt_booking_flow.py::test_the_static_prompt_no_longer_carries_the_booking_order` — **move.** Both assert the two sentences this task deletes. Keep every other assertion in them (no booking order, no offer wording, no "first name" in the static prompt, "never say when the team will call") and swap the two:

```python
    assert "the system tells you what it still needs" in p
    assert "you ask for it in your own words" in p
    assert "never ask for a name or a number yourself" not in p
    assert "do not simulate tool usage" in p
```

- [ ] **Step 2: Run to see them fail**

Run: `... -m pytest -q tests/test_flow_brief.py tests/test_voice_steps.py tests/test_voice_processors.py tests/test_tools_prompt.py tests/test_prompt_booking_flow.py`
Expected: `ImportError: cannot import name 'open_question'`; the moved cases fail on the old behaviour.

- [ ] **Step 3: `open_question`**

```python
class OpenQuestion(BaseModel, frozen=True):
    """The question the record is waiting on, and who owns its wording.

    `fixed` is True exactly when a `Pending` is open: a value the resolver could not settle
    is read back in the tenant's own words, because a wrong read-back is a wrong record
    (candidates-not-verdicts is phase B). Everything else is a plain step question, and the
    model words it from the readiness report (memo §7 decision 1).
    """

    key: str
    fills: dict
    fixed: bool


def open_question(slots: Slots, cfg: TenantConfig, channel: str) -> OpenQuestion | None:
    if slots.flow is None or slots.ended_flow:
        return None
    q = step_question(next_step(slots, cfg, channel), slots, cfg, channel)
    if q is None:
        return None
    return OpenQuestion(key=q[0], fills=q[1], fixed=slots.pending is not None)
```

`step_question` itself does not change: it is still the tenant-script table, and it is still what `next_question` renders. In `steps.py`, `open_question_text` renders the pair and `next_question` becomes a two-line wrapper over it, so its signature and its two existing call sites are untouched.

- [ ] **Step 4: `step_message` becomes a renderer over `readiness()`**

Keep every special brief that encodes a disambiguation the model actually got wrong — the QA brief, `COMPLETE`, the offers yes/no, the "is the number you're calling from the best one" brief, the team-note brief, the service-kind brief, and Task 4's digression brief. Change the **general** case, and delete its last sentence:

```python
    report = readiness(slots, cfg, channel)
    m = report.missing
    choices = (" — one of: " + ", ".join(m.choices)) if m.choices else ""
    extra = ""
    if step == Step.NAME:
        extra = (
            " Take the name exactly as they say it: never modify it, never autocorrect it, "
            "never guess a spelling."
        )
    elif step == Step.PHONE:
        extra = " Pass the digits exactly as they say them: never modify, autocorrect or guess."
    return (
        f"{STEP_MARKER} {known_text}Still needed: {m.description}{choices}. Ask for it in one "
        f"short question, in your own words, and put their answer in {m.tool}. If they ask you "
        "something else instead, call answer_question and answer them. If they change an "
        "earlier answer, call change_answer with that slot. The system decides what is stored "
        "and what is asked next, and the system speaks every outcome itself: never say a "
        f"request has been sent, filed, passed on or booked.{extra}"
    )
```

The pending brief tells the model the runtime has the words:

```python
    if slots.pending is not None and slots.pending.kind != "offers":
        return (
            f"{STEP_MARKER} {known_text}The system has just read something back to the caller "
            "in its own words and is waiting for a yes or a no. Call answer with yes or no and "
            "say nothing else."
        )
```

(`pending.kind == "which"` keeps its existing path, where naming one of the two through the slot tool is the answer.)

- [ ] **Step 5: The prompt**

Delete, from the WHAT YOU CAN DO block, the sentence "Never ask for a name or a number yourself, and never ask a question the system is about to ask." and change the clause before it, so the whole bullet reads:

```
- A request for the team (a booking, a callback, a change to an appointment, a question the facts do not answer) is handled by the system: call start_request, and from then on the system tells you what it still needs, one thing at a time, and you ask for it in your own words. The system decides what is asked and what is stored.
```

Add two bullets to HARD RULES, each borrowed verbatim from a project that ships it (OSS §8.2):

```
- Always explicitly invoke a tool when applicable. Do not simulate tool usage, no real action is taken unless the tool is explicitly called.
- A holding phrase must NOT indicate whether you can or cannot fulfill an action; it should be neutral and not imply any outcome. Never say "let me book that", "I'm putting that in" or "one moment while I get that done".
```

The second bullet's first sentence is OpenAI's chat-supervisor clause; the second names the exact family Task 1's guard now blocks, so the prompt and the guard say the same thing. `test_the_voice_is_calm` and the HOW YOU SOUND block are untouched — LIT R10's entrainment and persona changes are not in phase A.

- [ ] **Step 6: The handler**

Replace the `next_question()` append with the split. One re-run per caller turn, reset where `ignored_tools` is reset:

```python
        lines = list(spoken)
        q = open_question(session.slots, session.cfg, session.ref.channel) if not ended else None
        rerun = False
        if q is not None and q.fixed:
            # A confirmation: the wording is law, so the runtime says it and does not pay for
            # a model turn to rephrase it.
            text = render_script(q.key, session.cfg, now, urgent=False, **q.fills)
            lines.append(text)
            session.remember_question(text)
        elif q is not None and not session.reran_this_turn:
            # A plain step question. The runtime says nothing: `sync_context` has just put a
            # fresh readiness report in the brief and the model words the question from it
            # (OSS §8.4(f) — "the one thing to stop doing").
            rerun = True
            session.reran_this_turn = True
            session.record_signal("model_rerun", step=next_step(session.slots, session.cfg, "voice").value)
        for kind, detail in signals_for(before, session.slots):
            session.record_signal(kind, **detail)
        sync_context(session, now)
        for text in lines:
            await params.llm.push_frame(TTSSpeakFrame(text=text, append_to_context=True))
        await params.result_callback(
            {"spoken": bool(lines), "outcome": outcome.kind if outcome else "none", "ignored": False},
            properties=FunctionCallResultProperties(run_llm=rerun),
        )
```

`before` is `session.slots` captured before `run_tool`, so `signals_for` sees the move.

- [ ] **Step 7: The guard**

In `OutputGuardProcessor`, narrow the hold to the two cases where it is still right, and keep the fallback:

- `_emit`: hold a trailing question only when `self._s.tool_called_this_turn` is already True **or** a `Pending` is open (`open_question(...).fixed`). Otherwise release it immediately — the model owns the question.
- On `LLMFullResponseEndFrame`, in order: pop a digression if the model spoke (Task 4); drop the held question when a tool ran or a fixed confirmation was spoken; speak `next_question()` **only** when no tool ran, the model spoke nothing, and the call has not ended. The `asked_already` suppression stays on that fallback path exactly as the narrow fix left it — **conditional on the record alone, with no `_spoke_this_turn` conjunct** (`2f2a247`: a cancelled completion is a turn in which the model said nothing and must not be given the script "however recently it was last asked") — and records the `repeat` signal.
- Leave the `InterruptionFrame` branch clearing `_held` exactly as it is, and add the `bargein` signal there (Task 3).

Because the pipeline is asynchronous, the guard cannot tell the handler whether the model spoke before the handler runs, and the handler cannot wait to find out: Pipecat drains each processor's queue on its own task, while `run_function_calls` runs after the whole completion is consumed (verified in the installed `pipecat/services/google/llm.py` — text parts are pushed during the stream, `run_function_calls(function_calls)` after it). So the decision is split on purpose: the handler decides whether to re-run, the guard decides what reaches the wire, and the model's one-step-behind question from a tool turn is dropped rather than raced.

- [ ] **Step 8: Run**

Run: `... -m pytest -q tests/test_flow_brief.py tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_flow_draft.py tests/test_flow_rejections.py tests/test_voice_steps.py tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_voice_turns.py tests/test_prompt_budget.py tests/test_prompt_booking_flow.py tests/test_tools_prompt.py tests/test_driver.py tests/test_driver_flow.py tests/test_text_scenarios.py tests/test_structural_honesty.py tests/test_guard.py tests/test_renderer.py`
Expected: PASS. `test_the_static_half_of_the_request_is_byte_identical_at_every_step` must still pass — the readiness report rides after `STEP_MARKER` and nothing moves in front of it. `test_the_static_half_of_the_request_stays_inside_its_budget` must still pass with the two new bullets: if `tokens` crosses 6,500, shorten the bullets, do not raise the band.

- [ ] **Step 9: Commit**

```bash
git add spatalk/brain/flow.py spatalk/brain/prompt.py spatalk/voice/steps.py \
        spatalk/voice/handlers.py spatalk/voice/processors.py tests/
git commit -m "feat(voice): the runtime names the act and the model finds the words"
```

**Done when:** no tool result appends a plain step question; a `Pending` confirmation is still the tenant's words with no second model call; the model's own question reaches the caller on a non-tool turn; a silent model turn still gets `next_question()`; the brief invites the question and nowhere forbids it; the two verbatim prompt bullets are present and the "never ask for a name or a number yourself" line is gone; `test_prompt_budget.py` still passes inside its band.

**Cost — the one real cost item in phase A, stated plainly because the memo's §5 row for it is optimistic.** `run_llm=True` after a slot tool is a **second model call on that turn**, not "the same one model call per turn". At the measured shape of a call (6,437 input tokens a turn, 2,474 of them cached, ~45 output tokens for a question, `gemini-3.5-flash-lite` at $0.30 / $0.03 / $2.50 per million, 1.3896 CAD/USD) one extra call is **CA$0.00197**. If every turn bought one, that is +CA$0.0059/min — the memo's own "one extra Flash-Lite call every turn at full prompt, +0.0056, avoid" row. It does not: the re-run fires only on a turn that calls a slot tool and leaves no fixed confirmation, which on the 2026-09-10 call shape was 6 of 13 model turns, and it is capped at one per caller turn. So:

| | CA$/call-min | margin at the CA$0.0994 price |
|---|---|---|
| today | 0.0355 | 64.3% |
| + 1.4 re-runs a minute (the 2026-09-10 shape) | **0.0383** | **61.5%** |
| − the appended step question's TTS on a repeating call | 0.0369 | 62.9% |
| + Gemini explicit context cache (**not in this plan**) | 0.0343–0.0363 | 63.5–65.5% |
| + pre-rendered fixed scripts (**phase D**) | 0.0305–0.0339 | 65.9–69.3% |

The two offsets are each larger than this task's cost and are both already costed; neither is in phase A. **Latency is the sharper price:** on a re-run turn the caller waits one extra model round trip (~0.84 s median TTFB on this stack) before the first word, so the perceived gap on those turns goes from about 1.3 s to about 2.2 s — outside LIT R4's p50 ≤ 600 ms SLO and, unlike the money, audible. The founder call test below listens for exactly that, and `model_rerun` in the signal log counts how often it happens.

---

### Task 7: The signals reach the record and `/internal`

Memo §6 rung 0's second half: the counts have to survive the call, or phase C's trouble score has no history to set a threshold against.

**Files:**
- Modify: `spatalk/models.py`, `spatalk/conversations.py`, `spatalk/voice/pipeline.py`, `spatalk/http/internal.py`, `spatalk/ops/retention.py` (comment only)
- Create: `alembic/versions/0015_call_signals.py`
- Modify: `docs/contracts/runtime-internal.openapi.json`, `portal/src/runtime/client.ts`, `docs/reference/data-model.md`
- Test: `tests/test_conversations.py`, `tests/test_internal_api.py`, `tests/test_contract_snapshot.py`, `tests/test_ops_retention.py`

**Interfaces:**
- Produces: `Conversation.signals: Mapped[dict | None]` (JSONB, nullable); `end_conversation(sf, conversation_id, band, latency_ms, health_context=False, stage_ms=None, signals=None, call_notes=False)`; `ConversationFull.signals: dict | None`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_the_calls_signals_are_stored_with_it(session_factory, ...):
    """One row a call, counts and a capped tail. It is the only rung-0 artefact that outlives
    the process, and phase C's trouble score reads nothing else."""
    from spatalk.conversations import end_conversation
    from spatalk.ops.signals import SignalLog

    log = SignalLog()
    log.next_turn()
    log.record("repeat", script="ask_service")
    log.record("tool_rejected", reason="not_offered", tool="give_name")
    await end_conversation(sf, cid, band=2, latency_ms=[900], signals=log.as_json())
    conv = await _get(sf, cid)
    assert conv.signals["counts"] == {"repeat": 1, "tool_rejected": 1, "bargein_repeat": 0}
    assert conv.signals["turns"] == 1
    assert all(set(s["detail"]) <= {"script", "reason", "tool"} for s in conv.signals["signals"])


async def test_the_conversation_endpoint_carries_the_signals(...):
    body = (await client.get(f"/internal/conversations/{cid}", headers=KEY)).json()
    assert body["conversation"]["signals"]["counts"]["repeat"] == 1


async def test_retention_keeps_the_signals_when_it_takes_the_transcript(...):
    """The signals hold no caller words — Task 3's fence makes that structural — and a
    trouble threshold cannot be set from thirty days of data. They live as long as the
    conversation stub and die with it."""
    ...
    assert conv.signals is not None and conv.latency_ms is None and conv.flow is None
```

- [ ] **Step 2: Run to see them fail**

Expected: `TypeError: end_conversation() got an unexpected keyword argument 'signals'`.

- [ ] **Step 3: Column, migration, writer, endpoint**

`Conversation.signals`, with the comment saying what it is and is not:

```python
    # --- rung 0 (model words / runtime record memo, §6) ---
    # Counts and a capped tail of the call's own trouble signals: repeats, re-prompts,
    # repairs, refused tools, barge-in-and-repeat, guard blocks, and what the turn analyser
    # thought. Closed labels and numbers only — `spatalk.ops.signals` refuses anything that
    # could hold a word somebody said — so unlike `latency_ms` and `flow` this is not nulled
    # when the transcript goes: it is the phase-C trouble score's only history, and it dies
    # with the conversation stub at 400 days.
    signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

`alembic/versions/0015_call_signals.py`, down-revision `0014_slack_integration`: one `add_column` up, one `drop_column` down, schema `runtime`. Exercise the cycle on a second scratch database — `alembic upgrade head`, `information_schema` shows `signals jsonb null`, `alembic downgrade -1` removes it, `alembic upgrade head` re-applies, `alembic check` reports no new operations — and paste the output into the Task 9 report, as `lead-context-V1` did. **Never against `spatalk`.**

`end_conversation` gains `signals: dict | None = None` and puts it in the `values(...)`. `pipeline.py` passes `signals=session.signals.as_json()`. `ConversationFull` gains `signals: dict | None` and `read_conversation` passes `signals=conv.signals`; the list view (`ConversationRow`) does **not** get it, for the same reason the notes stayed off it — a page of conversations is a list of rows.

`spatalk/ops/retention.py` is not changed, only commented: the `.values(caller=None, latency_ms=None, stage_ms=None, flow=None)` line gains a note saying `signals` is deliberately absent and why.

- [ ] **Step 4: Regenerate the two snapshots**

```bash
cd <worktree>/runtime
PYTHONPATH=. C:/.../runtime/.venv/Scripts/python.exe -c "import sys; from spatalk.cli import app; sys.argv=['spatalk','openapi','--internal']; app()" \
  > ../docs/contracts/runtime-internal.openapi.json
cd ../portal && npm run gen:client
```

If `npx` cannot reach the network, hand-write the one added property in `portal/src/runtime/client.ts` in the shape the generator uses for the other nullable JSONB fields (`/** Signals */ signals: { [key: string]: unknown } | null;`) and record it as a deviation so the founder's session can re-run `npm run gen:client` and confirm no diff. Do not run `wasp`.

- [ ] **Step 5: Run**

Run: `... -m pytest -q tests/test_conversations.py tests/test_internal_api.py tests/test_contract_snapshot.py tests/test_ops_retention.py tests/test_voice_turns.py tests/test_call_notes.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add spatalk/models.py spatalk/conversations.py spatalk/voice/pipeline.py \
        spatalk/http/internal.py spatalk/ops/retention.py alembic/versions/0015_call_signals.py \
        tests/ ../docs/contracts/runtime-internal.openapi.json ../portal/src/runtime/client.ts
git commit -m "feat(ops): a call's trouble signals outlive the call"
```

**Done when:** the column exists with a reversible migration exercised both ways on a scratch database; the endpoint carries the signals; the contract snapshot and the portal client match the generator; retention keeps `signals` and still nulls `latency_ms`, `stage_ms` and `flow`.

**Cost:** CA$0.00/min. One JSONB write at the end of a call.

---

### Task 8: Full suite, lint, reference docs

**Files:**
- Modify: `docs/reference/flows.md` (§10 steps 3, 4 and a new step), `docs/reference/data-model.md` (the `conversations` table and the retention table), `docs/roadmap.md`
- Test: the whole runtime suite

- [ ] **Step 1: Run everything, once, on a fresh scratch database**

```bash
docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_mw_final"
cd <worktree>/runtime
SPATALK_NO_ENV_FILE=1 PYTHONPATH=. \
TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_mw_final \
C:/.../runtime/.venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider
C:/.../runtime/.venv/Scripts/python.exe -m ruff check spatalk tests scenarios
```

Expected: every test passing except the one pre-existing failure named in Verification. The suite takes about 30 minutes; run it once and do not interleave a second pytest process.

- [ ] **Step 2: Reference docs**

`docs/reference/flows.md` §10 — step 3 becomes:

> 3. The model is offered exactly the open step's tool (`answer`, `choose_practitioner`, `choose_service`, `give_name`, `give_phone`, `choose_window`) plus `change_answer`, `answer_question`, `escalate`, `end_conversation`. The step brief is a readiness report — what is known, what is still needed and its legal choices — and the model asks for it **in its own words**; the runtime decides which slot is open and what may be stored (model-words memo, 2026-09-11, §7 decision 1). A tool the step did not offer, one called too early, or one called with a value the runtime cannot use is **refused in words the model can read**, naming what is missing and what may be called instead: nothing is written, nothing is said to the caller, and the turn goes back to the model. Past three refusals in one caller turn the runtime speaks the open question itself.

Step 4 gains its second half: "A confirmation of a value the resolver could not settle is still spoken in the tenant's own words (`confirm_match`, `confirm_which`, `confirm_phone`, `confirm_name_staff`), because a wrong read-back is a wrong record." And a new step 7: "A side question at any step is `answer_question` — no arguments, nothing written: the runtime records the step it interrupted, the model answers from the facts and asks the open question again in its own words, and the frame is gone by the next turn."

`docs/reference/data-model.md`: the `signals` row in the `conversations` table, and a row in the Retention table — "`conversations.signals` | kept with the conversation stub (counts and closed labels only, no caller data) | fixed".

`docs/roadmap.md`: one line under built — "Model words, runtime record — phase A: guard hardening, `answer_question`, readable rejections, model-worded questions, rung-0 signals (2026-09-11)".

- [ ] **Step 3: Commit**

```bash
git add docs/reference/flows.md docs/reference/data-model.md docs/roadmap.md
git commit -m "docs(reference): the runtime names the act, the model finds the words"
```

**Done when:** the suite matches the Verification baseline exactly; `ruff check` clean; the three reference documents describe what the code does.

**Cost:** CA$0.00/min.

---

### Task 9: Task report and the founder's call test

- [ ] **Step 1: Write `docs/reports/tasks/model-words-phase-a.md`** in the `docs/agents/ENGINEER.md` format: status, commits, the test commands with counts, the interfaces produced, and **every deviation** with the evidence line that justified it. The ones this plan already knows about, which must appear whether or not anything else does:
  1. The memo's §3.3 says an utterance asserting an outcome "must name an item id the ledger issued this conversation". Read as *backed by*, not *literally spoken*: the caller never hears an item id. The mechanism is the receipt register.
  2. A stall is blocked even with a receipt and even with `has_completed`, because "let me book that" is never true on this system.
  3. The retry counter is retired as a *strategy* and kept as a *ceiling* (`MAX_REJECTIONS_PER_TURN = 3`), against the scope's "replacing … the retry counter as a loop guard", because every handed-back turn is a model call and an unbounded loop spends the call while the caller hears nothing.
  4. A4 is voice-only; `Brain.turn` keeps appending the step question and keeps `drop_trailing_question`.
  5. A3's `Rejection` is produced for both channels but delivered only on voice, because a text turn has no tool-result round trip.
  6. The text driver's receipt count is this turn's, not the conversation's, so a restatement of an earlier filing is retracted and files a second item. Not seen; phase B's job.
  7. `conversations.signals` survives the transcript purge, unlike `latency_ms`, `stage_ms` and `flow`.
  8. Every test moved, old name → new name, with the memo sentence that authorises the move, and the note that each was strengthened rather than weakened.
  9. The Task 6 cost table, and the statement that the memo's §5 "≈ 0" row is right for A2 and wrong for A4.
  10. That `resolve.is_question` was not touched, and which of the narrow fix's five `ANSWER_THE_QUESTION` sentences now reach the model through `rejection_text` with the missing datum appended.
  11. The real full-suite baseline at the branch point, with the commit hash, since 1367 predates the narrow fix.

- [ ] **Step 2: Commit**

```bash
git add docs/reports/tasks/model-words-phase-a.md
git commit -m "docs(report): model words, runtime record — phase A"
```

- [ ] **Step 3: The founder's session does the rest** (not the executor)

1. `git merge model-words` into `main`; push.
2. `uv run alembic upgrade head` on the dev database (`0014` → `0015`).
3. No bundle import: **phase A adds no `scripts.yaml` key and changes no wording**, so the tenant config version does not move.
4. `restart-runtime.sh` (it refuses while a call is live).
5. The call-test checklist below.
6. After the calls: `GET /internal/conversations/<id>` and read `signals.counts`. Then the promptfoo run, one paid pass, at the QA gate.

---

## Verification

**Baseline.** The last measured full-suite figure before this plan is **1367 passed, 2 skipped, 1 pre-existing failure**, taken *before* the narrow fix's four commits, which add roughly thirty cases across `test_resolve.py`, `test_flow_apply.py`, `test_voice_handlers.py` and `test_voice_processors.py`. **So 1367 is a floor, not the number to match.** Record the real one yourself, once, at the branch point, before writing a line of Task 1 — `git rev-parse HEAD`, one full run, both in the Task 9 report. Every later run is compared against that, and the only acceptable difference is the new cases this plan adds.

**The one failure is not ours.** `tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick` is a timing test that starts `run_scheduler_forever` and polls `alerts.last_scheduler_tick()` for three seconds. It fails identically with every change in this plan stashed, nothing here goes near the scheduler, the job queue or the alert module, and `voice-regression-V1` and `cost-gap-C1` both reported it. **Do not fix it and do not touch it.** Prove it is still not ours at the end of the run:

```bash
git stash push -- runtime/spatalk runtime/tests
... -m pytest -q "tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick"
git stash pop
```

**Expected after phase A:** the recorded baseline plus the new tests, minus nothing. Roughly 45–55 new cases across `tests/test_guard.py`, `tests/test_ops_signals.py`, `tests/test_flow_rejections.py`, `tests/test_flow_brief.py`, `tests/test_flow_apply.py`, `tests/test_voice_processors.py`, `tests/test_voice_steps.py`, `tests/test_voice_handlers.py`, `tests/test_structural_honesty.py`, `tests/test_driver.py`, `tests/test_conversations.py`, `tests/test_internal_api.py`. **No test is deleted, skipped, xfailed or loosened.** Fifteen are renamed, extended or rewritten, each one strengthened, each one with the memo sentence that authorises it in its docstring:

| file | old name | becomes |
|---|---|---|
| `test_voice_processors.py` | `test_the_model_does_not_ask_a_question_while_a_flow_is_open` | `test_the_models_own_question_is_spoken_when_the_runtime_has_none` + `test_a_fixed_confirmation_still_beats_the_models_own_question` + `test_a_tool_turn_never_lets_the_models_question_out` |
| `test_voice_processors.py` | `test_the_open_question_follows_a_side_answer` | rewritten: the runtime's question follows only a *silent* model turn |
| `test_voice_processors.py` | `test_the_step_question_is_not_repeated_word_for_word` | survives, narrowed to the fallback path, `+ repeat` signal |
| `test_voice_processors.py` | `test_the_step_question_comes_back_once_the_record_moves` | survives, narrowed, `+ repeat` signal |
| `test_voice_processors.py` | `test_a_silent_model_turn_gets_the_question_unless_it_was_just_asked` | survives unchanged — the fallback, and the narrow fix already strengthened it |
| `test_voice_steps.py` | `test_a_slot_tool_speaks_the_next_question_and_never_reruns_the_llm` | `test_a_slot_tool_says_nothing_and_hands_the_turn_back_for_the_question` + `test_a_confirmation_is_still_the_runtimes_own_words` + `test_the_outcome_line_is_still_spoken_and_buys_no_second_model_call` |
| `test_voice_steps.py` | `test_a_tool_the_step_did_not_offer_is_ignored_and_the_model_answers` | `test_a_tool_the_step_did_not_offer_is_refused_in_words_the_model_can_read` |
| `test_voice_handlers.py` | `test_an_ignored_tool_hands_the_turn_back_to_the_model` | `…_is_refused_in_words_that_name_what_is_missing` |
| `test_voice_handlers.py` | `test_a_question_shaped_answer_hands_the_turn_back_with_a_reason` | extended with the missing datum; nothing removed |
| `test_voice_handlers.py` | `test_a_tool_result_does_not_repeat_the_question_just_asked` | survives; the tool result now carries no plain question at all |
| `test_voice_handlers.py` | `test_a_tool_the_step_does_offer_still_speaks_the_next_question` | rewritten: it speaks the outcome and the confirmation, never a plain question |
| `test_tools_prompt.py` | `test_the_qa_tool_set_is_start_request_and_the_always_tools` | extended with `answer_question` |
| `test_tools_prompt.py` | `test_prompt_hands_a_request_to_the_system` | the two deleted sentences swapped for the two new ones |
| `test_prompt_booking_flow.py` | `test_the_static_prompt_no_longer_carries_the_booking_order` | same swap; every other assertion kept |
| `test_flow_apply.py` | `test_change_answer_for_a_slot_that_holds_nothing_is_ignored` | extended with the rejection, nothing removed |

**Untouched and must pass unchanged:** every case in `tests/test_renderer.py`; `tests/test_structural_honesty.py`'s nine existing cases; `tests/test_guard.py`'s six existing cases (in particular `"Let's get you booked in with the team."` and `"I'd love to help you get that booked."` still pass the guard, which is what keeps the stall pattern narrow); `tests/test_driver.py`'s existing cases; `tests/test_resolve.py`'s `is_question` cases, which this plan does not touch; the narrow fix's `test_a_fragment_is_not_a_turn_and_its_words_are_kept` and `test_a_silent_model_turn_gets_the_question_unless_it_was_just_asked`; `tests/test_prompt_budget.py`'s five cases, including the byte-identical-prefix property and the `5_000 < tokens < 6_500` band; `tests/test_qa_gate_a.py`'s key-for-key script comparison, which needs no edit because phase A adds no script key.

**Lint:** `ruff check spatalk tests scenarios` → All checks passed.

**Migration:** `0014` → `0015` → `0014` → `0015` on a scratch database, with `alembic check` clean at the end, and the `information_schema` line pasted into the report.

**Not run:** the promptfoo suite (paid, one run per QA gate, the orchestrator's). Read it before finishing and say in the report whether anything in it is now stale — the case worth a fresh look is any whose expectation is the runtime's step question after a tool call, because the runtime no longer speaks one.

## Founder call test — phase A

Four calls, from the founder's own phone, after the go-live steps. The first three provoke a specific behaviour; the fourth is a listening test the ledger settles. Read `signals.counts` on each conversation afterwards (`GET /internal/conversations/<id>`) — this is the first release where the call reports on itself.

**1. A side question mid-step.** Start a booking, answer "no" to having been in before, and then, at the treatment question, ask *"what was the facial one again?"* — the 01:40 call's exact shape.
- Expect: an answer from the facts, in the model's words, naming at most three treatments with prices, and then the treatment question again **in the model's own wording** — not "What did you have in mind?" twice.
- Expect **not**: the words being filed as a treatment choice, and no "Did you mean Free virtual consultation?".
- Then ask a second side question straight after ("does it hurt?") and check the same thing happens, and that the assistant still comes back to the treatment.
- In the record: `digression` ≥ 2, `repeat` = 0, `tool_rejected` = 0. A non-zero `repeat` means the fallback fired and the model went silent — say which turn.

**2. A mis-heard name.** At the name question, say your own name, "Peyman", plainly.
- Expect: the call **stays on the booking**. It must not become a payment refusal and must not hang up (V1's symptom 5, already fixed; this confirms it survived).
- Expect, honestly: **the stored name may still be wrong**. STT confidence is phase B and `voice-regression-V1`'s open item 2 is still open. Check the filed item's `contact_name` in the portal and report what it holds. If it is wrong, that is the measurement phase B needs, not a regression in phase A.
- In the record: `caller_repeat` tells you whether you had to repeat yourself.

**3. A premature file attempt.** Say, early and firmly, *"just book me in, that's all you need"* — before giving a name or a number.
- Expect: no item filed, nothing claimed, and the assistant asking for what is actually missing, in its own words. The words "sent", "filed", "passed on" and "booked" must not appear until the outcome script does.
- Then check the portal: **zero items** from that stretch of the call.
- In the record: `tool_rejected` ≥ 1 with `reason` `premature` or `not_offered`. If it is 0, the model never tried and the test proved nothing — try harder.

**4. A paraphrased outcome claim.** This one the model has to volunteer, so it is a listening test. Through all four calls, listen for any sentence of the shape *"I've passed that to the team"*, *"I've sent that over"*, *"let me book that in"* or *"one moment while I get that done"* **before** the runtime's own outcome line.
- Expect: never. If one is attempted, the caller hears `cannot_complete` ("I can't complete that from here, but I've passed it to the team…") and **an item exists** for it — check the portal.
- In the record: `guard_block` is the count, with `family` naming which lexicon fired. `guard_block` > 0 with a matching item in the ledger is the system working, not failing.
- If it never happens on a call, the evidence is `tests/test_voice_processors.py::test_a_paraphrased_outcome_claim_is_retracted_when_nothing_was_filed` and `::test_a_stall_that_implies_an_outcome_never_reaches_the_wire`. Say so in the report rather than claiming the calls proved it.

**What to listen for across all four, and report as numbers, not adjectives.**

- **Exactly one question a turn.** Two questions in one breath is the V1 regression returning; name the turn.
- **The gap before the first word.** Task 6 buys a second model round trip on the turns where the model words a question, which should add roughly 0.8–1.0 s on those turns and nothing on the others. `latency_ms` on the conversation record is the measurement, `model_rerun` in `signals.counts` is how often it was bought, and the honest comparison is against V1's median of 1.31 s. If it is audible, that is a phase-D decision (pre-rendered scripts, Smart Turn re-scoring, the explicit context cache), not a phase-A revert.
- **`turn_prediction` and `turn_no_prediction`.** The ratio is the first real data on how often the 1.5 s silence fallback fires. Nobody touches `TURN_END_FALLBACK_SECS` until it exists — that was V1's ruling and it still stands.
- **One listener is a smoke test.** LIT §6.4 is blunt about it: more than 30 listeners are needed for a stable naturalness verdict, and 10 to 30 paired calls can only detect a near-total preference. Four calls can tell you phase A is not catastrophically worse and that the 01:40 failure is gone. They cannot tell you it sounds more human, and the report must not say they did.
