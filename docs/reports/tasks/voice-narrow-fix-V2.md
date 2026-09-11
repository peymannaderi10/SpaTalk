# Voice narrow fix V2: the four approved items from the 2026-09-11 01:40 call
Status: done with deviations
Commit: `b277622`, `117cb18`, `8563882`, `2f2a247`, `43ea707`, `958b928`, `1cd9279`, `4976d0d`, plus the docs commit that carries this file
Tests: `pytest tests/test_resolve.py tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_flow_draft.py tests/test_rules.py tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_voice_steps.py tests/test_voice_echo.py tests/test_voice_turns.py tests/test_voice_filler.py tests/test_structural_honesty.py tests/test_driver.py tests/test_driver_flow.py` -> 145 passed, 2 skipped; 12 new tests and 1 renamed and extended; full suite -> 1379 passed, 2 skipped, 1 pre-existing failure
Interfaces produced: `spatalk.brain.resolve.is_question`, `spatalk.brain.resolve.QUESTION_WORDS`, `spatalk.brain.resolve.QUESTION_PHRASES`, `spatalk.brain.resolve.KIND_TAIL`, `spatalk.brain.resolve.category_placeholders`, `spatalk.brain.rules.is_fragment(text, yes_no_step=False)`, `spatalk.brain.rules.NO_CONTENT_WORDS`, `spatalk.brain.rules.YES_NO_FILLERS`, `spatalk.brain.flow.Applied.rejection`, `spatalk.brain.flow.ANSWER_THE_QUESTION`, `spatalk.brain.flow.tool_refusal`

The call: conversation `1d90476b-af7e-4a40-af65-8899c5621376`, tenant skincentrix, 2026-09-11
01:40:21 to 01:41:50 local, 6 model turns, nothing filed. Log `serve.log`, lines timestamped
2026-09-11 01:40:00 to 01:41:58, ANSI stripped. This is the narrow four-item fix on the
current slot engine, approved for the demo; it is not phase A of
`docs/superpowers/specs/2026-09-11-model-words-runtime-record-design.md` and none of that
redesign was started.

---

## Item 1 — a question is not an answer

### Evidence

The service step offers `choose_service` and nothing else, and the step brief ends "Do not ask
a question yourself". So a caller asking the runtime to repeat itself has nowhere to go but
into the slot tool:

```
01:41:17.796 Calling function [choose_service:call_58677]    with arguments {'said': 'the station one'}
01:41:17.807 Generating TTS [Sorry, which treatment did you have in mind?]
01:41:26.081 Calling function [choose_service:call_2729800]  with arguments {'said': 'the facial one'}
01:41:26.085 Generating TTS [Is there someone in particular you'd like to see, or whoever's available?]
```

The stored transcript for that second turn is "Sorry, what was the— what was the facial one
again? The facial one?". The slot filled, the step moved to the practitioner, and the question
was never answered. The caller said it a third time ("No, I'm talking about the, the facial.
Treatment. What was that, the, the offer again?") before the model finally answered in words
at 01:41:38.

### Cause

`flow._apply` hands `said` straight to the resolver. There is no test anywhere in the path for
whether the caller asked something rather than answered, and a refused tool call returned only
a bare `ignored` flag, so the model was told "no" without being told what to do instead.

### Change

- `spatalk/brain/resolve.py`: `is_question(said)`. An interrogative or repeat marker as a
  whole word (`QUESTION_WORDS`: what, what's, whats, whatre, which, again, repeat, repeated,
  pardon), one of five repeat phrases (`QUESTION_PHRASES`: "you said", "did you say", "one
  more time", "say that", "come again"), or a question mark anywhere. Whole words, so
  "whichever" and "whoever's" are still answers. "sorry" is deliberately **not** a marker:
  "Sorry, the classic facial" is a correction, not a question.
- `spatalk/brain/flow.py`: `apply` runs it ahead of the resolver for `choose_service` and
  `choose_practitioner`, and refuses an `answer` whose `value` is outside the schema's enum
  rather than reading anything that is not "yes" as a no. A refused call writes nothing and
  says nothing, as before, and now carries `Applied.rejection` — a sentence the model can act
  on. The same was extended to the other refusals, which the memo's decision 6 also asks for:
  a tool the step does not offer, and a `change_answer` on a slot that holds nothing.
- `spatalk/voice/handlers.py`: `tool_refusal` replaces the `tool_ignored` call (one pure
  `apply`, two values). The rejection goes back as the function response with `run_llm=True`
  and no fixed step question appended — the ignored-tool path from `e8ae57d`, unchanged in
  shape. The one-retry budget still stops a model that loops.

The rejection is a function response and nothing else: never rendered, never spoken, never
stored on an item or on the record. Non-negotiable 3 is untouched — every word the caller
hears still comes from `scripts.yaml`.

### Test

`tests/test_resolve.py::test_a_question_is_not_an_answer` (the founder's two utterances plus
seven controls), `tests/test_flow_apply.py::test_a_question_shaped_answer_is_refused_with_a_reason`
(both utterances refused at the service step, "the facial one" still resolves, the practitioner
step and the `answer` enum too), `tests/test_voice_handlers.py::test_a_question_shaped_answer_hands_the_turn_back_with_a_reason`.
Seen failing first, and the handler test failed with the call's own line: `AssertionError: a
refused tool call spoke ... text="Is there someone in particular you'd like to see, or
whoever's available?"`.

### What a live call must confirm

**This item would not have fired on this call, and that is the honest finding.** The model did
not pass the caller's question through; it summarised it. The two arguments it actually sent
were `{'said': 'the station one'}` and `{'said': 'the facial one'}` — no interrogative, no
repeat marker, no question mark — and the same was true on 2026-09-10 (`{'said': 'the station
one'}` at 20:54:17). `is_question` cannot see a question that has been stripped before it
reaches the tool. What fixes *this* call's 01:41:26 turn is item 2. Item 1 fixes the same
failure whenever the model does pass the caller's words through, which is what the tool
description asks of it ("The treatment the caller named, in their words"), and it is the guard
that stops a stripped question from resolving the moment the model stops stripping.

The cost to watch for: a caller who phrases a real choice as a question ("How about the
classic facial?") is now answered rather than advanced, and has to say it again. On the
recorded calls that has not happened; the markers are tight, but "how" and "who" were left out
of the set on purpose to keep it that way.

Two smaller things to listen for. A caller who phrases a real choice as a question ("How about
the classic facial?") is now answered rather than advanced, and has to say it again; the marker
set is tight, and "how" and "who" were left out on purpose to keep it that way. And the
`answer` enum is matched exactly, so a model that sends `"Yes"` rather than `"yes"` is refused
and asked to try again — which costs one round trip but is strictly better than the old
behaviour, where anything that was not exactly `"yes"` was silently read as a no. Case-folding
the value would remove even that, and was left out only to keep this change to the four
approved items.

---

## Item 2 — a generic category entry resolves to a kind, not a treatment

### Evidence

Against the real bundle:

```
match_service("the facial one", cfg)             -> kind='exact' value='facial'
match_service("what was the facial one again")   -> kind='exact' value='facial'
match_service("maybe a facial", cfg)             -> kind='exact' value='facial'
match_service("microchanneling", cfg)            -> kind='exact' value='microchanneling'
match_service("laser hair removal", cfg)         -> kind='which' candidates=('laser_hair_xsmall', 'laser_hair_small')
_score("facial one", "facial")                   -> 0.9        (ACCEPT is 0.90)
```

(run against `118952a`, this task's baseline, archived with `git archive`.)

`tenants/skincentrix/services.yaml` carries, under the comment "what callers ask for by
category (generic entries; the specific ones follow)", `id: facial, name: Facial, category:
facial`. `WRatio` penalises the length difference and returns the partial ratio times 0.9, so
*any* phrase containing "facial" scores exactly 0.90 against "Facial" — exactly `ACCEPT`. The
runtime therefore stored a catalog row that names no treatment and advanced the step, and the
same held for `microchanneling`. The third placeholder went the other way: "laser hair
removal" is the exact name of its own row, but the category-word narrowing drops "laser" and
matches the rest, so the caller was offered a coin-flip between two of the six-session
packages instead.

### Cause

The placeholder rows are indistinguishable from treatments to the resolver, and the spec's
"a facial → kind → `ask_service_kind`" path was reachable only by the bare category word.

### Change

`spatalk/brain/resolve.py`:

- `category_placeholders(cfg) -> {service_id: category}` finds them by shape, so no tenant
  bundle has to be re-authored: an entry whose `id` or whose `name` **is** its category, or
  whose `name` is a strict subset of the names of two or more other entries in the same
  category ("Laser hair removal" inside "Laser hair removal, small area"). On the Skincentrix
  catalog that is exactly `facial`, `laser_hair_removal` and `microchanneling`, and nothing
  else — a real treatment always carries a word the others do not.
- `KIND_TAIL` strips the filler a caller hangs off a category name ("one", "ones",
  "treatment", "treatments", "option", "options") before the category test, but never when it
  is the whole utterance, so `match_service("one")` is still `none`.
- A match on a placeholder, by the category word or by the placeholder's own name, returns
  `kind` with the category's **specific** treatments as its candidates. `flow._service` already
  turns `kind` into `Pending(kind="offers")`, which `step_question` renders as
  `ask_service_kind` with the treatment slot left empty.
- Placeholders are out of the running when the specific entries are matched, so `_best` over
  the whole phrase can no longer land on one. (On this bundle the narrowing already shielded
  most phrases from that — `"classic facial"` and `"acne facial"` read the same before and
  after — so this half is insurance rather than a fix.)

Result against the bundle: `"the facial one"` → kind facial, 12 candidates; `"laser hair
removal"` and `"the laser one"` → kind laser, 7; `"microchanneling"` → kind skin; `"the express
one"` and `"express treatment"` → kind express. `"MesoJet"` → exact `mesojet_facial`;
`"classic facial"` → exact `classic_facial`; `"hydroabrasion facial"` →
`hydrabrasion_facial`; `"skin and scalp facial"` → `scalp_facial`; `"the station one"`,
`"station one"`, `"one"`, `"blorp"` → none.

### Test

`tests/test_resolve.py::test_a_generic_category_entry_resolves_to_a_kind` (the three the item
names, the placeholder excluded from its own candidate list, plus five specific treatments that
must still be exact), `tests/test_flow_apply.py::test_a_generic_category_entry_does_not_fill_the_treatment_slot`
(the slot stays empty and the next script key is `ask_service_kind`). The second was seen
failing with `assert 'facial' is None`.

### A regression the promptfoo suite caught on the page

Taking the placeholder out of the running left "maybe a facial" and "I was thinking a facial"
to the fuzzy match over the specific treatments, which answered `which` on whichever two
happened to score alike:

```
match_service("maybe a facial")           -> which=('scalp_facial', 'purecarbon_facial')
match_service("I was thinking a facial")  -> which=('purecarbon_facial', 'mirapeel_facial')
```

(run against `1cd9279`, the commit before the fix.) "Did you mean the Skin and scalp facial or
the PureCarbon facial?" to a caller who has chosen nothing is worse than the defect it
replaced — before `117cb18` those phrases matched the placeholder exactly, which was the
original defect, so neither reading was right. `scenarios/promptfooconfig.yaml`'s case "step
treatment, a kind of treatment" is that exact sentence, expecting `ask_service_kind`.

`4976d0d`: when a category word is present and the words around it narrow to nothing, that is
a kind. `_named_category` is now the single place the category fallback lives, reached from
both the narrowing miss and the whole-phrase miss. Pinned by
`tests/test_resolve.py::test_a_category_word_the_rest_does_not_narrow_is_a_kind` over six
phrasings, with "the hydrabrasion facial", "MesoJet facial" and "a facial for acne" as the
controls that must still narrow.

A sweep of 58 realistic treatment phrasings and 15 practitioner ones against the bundle found
nothing else moved by this item. Two oddities in it are older than this task and unchanged by
it: "express lift" resolves to `lift_sculpt_facial` rather than `express_lift` (the narrowing
drops the category word "express" and both names carry "lift"), and "the nurse" resolves to
`any` because `STRIP_WORDS` removes the word.

### What a live call must confirm

- "A facial, please" now reaches `ask_service_kind` — "I can run through two or three options,
  or a free virtual consultation can help you pick — which would you prefer?" — and then the
  model naming two or three from the facts. That is one more turn than before; the founder
  should judge whether it reads as helpful or as a stall.
- "Microchanneling" is now kind `skin`, whose candidates are the whole category (the three
  microchanneling serums plus XERF and the acne program). The script names no candidates, so
  what the caller hears depends on the model picking sensibly from the facts.
- `$99 express treatment` is the one generic row the shape rule does not catch (its name
  carries "99" and "treatment", which no sibling's name repeats). It is reached anyway through
  `KIND_TAIL` and the category fallback: "express treatment", "the express one", "express
  treatments" and "the ninety-nine dollar express treatment" are all kind `express`. The
  phrasing that still lands on the row is one that keeps the digits — "the 99 express
  treatment" answers `which`. Worth a `generic: true` flag in the schema if that shows up on a
  call; the rule was kept out of the bundle deliberately so the demo needs no re-import.

### Bundle

**No change to `runtime/tenants/skincentrix/*.yaml`.** The recognition is a resolver rule, so
nothing has to be re-imported. `docs/reference/tenant-config.md` documents it under
`services.yaml`.

---

## Item 3 — a fragment with no content words is not a turn

### Evidence

The stored transcript holds three one-utterance caller turns in five seconds:

```
user  "Um."
user  "Well."
user  "What was the, uh—"
user  "What was the, the station one again?"
```

Each was a **final** transcription from the recogniser, not a promoted interim:

```
01:41:11.233 MinWordsUserTurnStartStrategy#1 should_trigger=True num_spoken_words=1 min_words=1 bot_speaking=False interim_transcription=False
01:41:12.128 ...                             should_trigger=True num_spoken_words=1 min_words=1 bot_speaking=False interim_transcription=False
01:41:13.788 ...                             should_trigger=True num_spoken_words=4 min_words=1 bot_speaking=False interim_transcription=False
01:41:16.786 ...                             should_trigger=True num_spoken_words=7 min_words=1 bot_speaking=False interim_transcription=False
```

`_promote_stale_interim` did not fire once in the whole 01:41 window — the log holds three of
its lines in total, at 01:39:58.101, 01:40:00.161 and 01:40:02.240, all on "Hi there." from
the previous call. So **the evidence disagrees with
the brief's first hypothesis**: the stale-interim promotion is not involved, and neither is the
turn-stop watchdog (`TURN_STOP_WATCHDOG_SECS = 2.0`, never reached).

What did let them through, read out of the installed Pipecat 1.8.1 source: a final arriving
*after* the VAD stop starts a fresh turn through `MinWordsUserTurnStartStrategy`;
`TurnAnalyzerUserTurnStopStrategy.handle_user_turn_started` calls `_reset()`, which clears
`_vad_stopped`; `_handle_transcription` then takes its no-VAD fallback branch, sets
`_turn_complete = True` and arms a timer of `ttfs_p99 - stop_secs`. So the INCOMPLETE the Smart
Turn model had just returned is discarded:

```
01:41:11.220 End of Turn result: EndOfTurnState.INCOMPLETE
01:41:11.377 LLMUserAggregator#1: User turn inference triggered (strategy: TurnAnalyzerUserTurnStopStrategy#1)
01:41:11.382 GoogleLLMService#1: Generating chat from context [...]
```

144 ms, not the 1.5 s fallback. That is Pipecat's own path and not ours to change.

### Cause

Nothing in the runtime asked whether an utterance carried anything worth a turn. The one layer
we own upstream of the aggregator is `RulesGateProcessor` (`pipeline.py`: `transport.input()`,
`stt`, `RulesGateProcessor`, `user_agg`, …), so it is the only place the decision can be made
before the start and stop strategies see the frame.

### Change

- `spatalk/brain/rules.py`: `is_fragment(text)` — every word in `NO_CONTENT_WORDS` and no
  question mark. `NO_CONTENT_WORDS` is disfluency, discourse markers and the function words a
  sentence begins with. The set is deliberately asymmetric, because holding a real answer
  costs the caller a nudge's worth of silence while letting a hesitation through costs one
  model run the item-4 suppression already covers: **anything that could be an answer is a
  turn.** So out go every step answer ("yes", "no", "sure", "any", "whoever"), every repair
  word (so "What?" still asks for the question again), and — corrected in `958b928` after the
  first cut had them in — the affirmative backchannels "mhm", "mm", "mmm", "right" and
  "alright", which are how a caller says yes to "Have you been in to see us before?". "hm"
  and "hmm" stay, as the thinking-aloud nasals. A gate word is always a content word, so a
  transcription the rules gate would have escalated is never a fragment.
- `spatalk/voice/processors.py`: `RulesGateProcessor._turn_text` **holds** a fragment rather
  than dropping it and puts it in front of the next transcription that does carry content, so
  nothing the caller said is lost. It runs after the echo scrub (so an utterance trimmed down
  to a filler is caught too) and before the session bookkeeping, so a fragment no longer
  resets the "still there?" count or the ignored-tool allowance — it is not a caller turn.
  `_yes_no_step` asks `step_tools` whether `answer` is on offer, rather than keeping a list of
  steps of its own, so the gate cannot drift from the flow; a pending confirmation counts too.

If the caller has in fact stopped, the floor is still held: no `UserStartedSpeakingFrame`
reaches `UserIdleController`, so the idle timer armed at the bot's last `BotStoppedSpeakingFrame`
runs out and `on_user_turn_idle` asks "still there?", and the worker's 45 s idle timeout ends
the call. If a fragment's *interim* opened a turn that the held final would have closed,
`user_turn_stop_timeout` forces the turn shut 2 s later and `LLMUserAggregator.push_aggregation`
returns `""` without pushing a context frame (verified in the installed source, line 871), so
no model runs and nothing is spoken.

### Test

`tests/test_rules.py::test_a_fragment_with_no_content_words_is_not_a_turn` (the call's three
utterances and four more fragments, against eight controls including "No.", "Sue", "What?" and
"Seizure."),
`tests/test_voice_processors.py::test_a_fragment_is_not_a_turn_and_its_words_are_kept` (the
three frames reach nothing downstream; the next transcription carries "Um", "Well" and "What
was the" in front of it; "No." is still a turn). Seen failing: `AssertionError: a fragment
reached the aggregator`.

### Two holes found by walking the steps, not the call

Both in `1cd9279`, both before any live call, and the first would have broken a booking:

1. **A phone number carries no letters.** `is_fragment`'s word regex stripped digits with the
   punctuation, so `re.sub` left no words and `all()` over an empty list is True: every number
   was a fragment. The founder would have given his number at `ask_phone` and heard nothing
   until the nudge. Digits are content words now, and
   `test_digits_are_content_so_a_phone_number_is_always_a_turn` pins six spellings of a number
   plus the punctuation-only case that should still be nothing.
2. **"Okay." answers the offers question.** It is on the item's filler list and it is also how
   a caller says yes to "Would you like to hear our new-client offers?". `YES_NO_FILLERS`
   ("okay", "ok") now stands down wherever the open question takes a yes or a no, which the
   gate learns from `step_tools`. Everywhere else "Okay." is still thinking aloud.

The remaining collisions after that walk, all mild and all of the "held, then joined to the
next utterance" kind rather than lost: a bare "I was." or "I am." as a yes to "Have you been
in to see us before?" is held, because "was" has to stay in the set for the item's own "what
was the" example.

### What a live call must confirm

- A whole booking end to end, and in particular the number step: say the number, hear the
  read-back. That is the path the digits hole would have broken.
- Whether a caller who pauses inside a sentence now gets the patient silence he wanted, rather
  than the assistant filling it.

---

## Item 4 — the fixed step question never fires twice on an unchanged record

### Evidence

The suppression fired once and then stopped working:

```
01:41:12.137 step question not repeated: 'What did you have in mind?'
01:41:12.278 Generating chat from context [...]                       <- the turn "Well." started
01:41:12.837 broadcasting interruption                                <- the next fragment cancelled it
01:41:12.839 GoogleLLMService#1 prompt tokens: 0, completion tokens: 0
01:41:12.841 Generating TTS [What did you have in mind?]              <- 2nd time
...
01:41:16.787 broadcasting interruption
01:41:16.795 Generating TTS [What did you have in mind?]              <- 3rd time
```

Both repeats came from `LLMFullResponseEndFrame` on a completion the caller's next words had
cancelled — nothing generated, `prompt tokens: 0, completion tokens: 0`.

### Cause

V1's condition was `if question and self._spoke_this_turn and self._s.asked_already(question)`.
`_spoke_this_turn` is False on a turn in which the model produced no text, so the suppression
was skipped by design — V1's own docstring says the script goes out "however recently it was
last asked" when the model is silent. An interrupted completion is indistinguishable from a
silent one at that point, so every cancelled turn re-spoke the question. The tool-result path
in `handlers.py` had no suppression at all.

### Change

- `spatalk/voice/processors.py`: the condition is now the record alone —
  `if question and self._s.asked_already(question)`.
- `spatalk/voice/handlers.py`: the tool handler consults `asked_already` before appending the
  question, so the same rule holds on the tool-result path. It is reachable on the second
  refused call in a caller turn, whose fallback is the open question.
- `spatalk/voice/session.py`: `asked_already`'s docstring now states the contract — every path
  that could speak a fixed question asks it, and the rendered text is the identity because it
  is what the caller hears.

A silent turn on an unchanged record is now silent by design; the "still there?" nudge and the
45 s idle timeout hold the floor instead of a third identical question.

### Test

`tests/test_voice_processors.py::test_a_silent_model_turn_gets_the_question_unless_it_was_just_asked`
— the renamed and extended form of `test_a_silent_model_turn_still_gets_the_question`. It still
pins that a question the runtime has not just asked fills a silent turn, and now also pins the
two cancelled completions of 01:41:12 to 01:41:17 replayed as frames, and the question coming
back the moment the record moves. That is the one existing expectation this task overturns; it
was strengthened, not weakened.
`tests/test_voice_handlers.py::test_a_tool_result_does_not_repeat_the_question_just_asked` is
the other path. Both seen failing first.

### What a live call must confirm

Whether the silence reads as attentive or as dead air. The mechanism is pinned; only an ear can
say whether a caller who has just heard the question and says nothing new is better served by
silence and the eventual nudge than by hearing it again.

---

## The call, replayed through the fixed engine

`flow.apply`, `flow.step_question` and `rules.is_fragment` are pure, so this is the founder's
own utterances and the tool calls his call actually produced, with no model and no database
(`v2/v2_replay.py` in the scratchpad):

```
CALLER: Hi, I would like to book an appointment.
  AVA (step): Have you been in to see us before?
CALLER: Uh, no, I haven't.
  AVA (step): Would you like to hear our new-client offers?
CALLER: Uh, sure.
  AVA (script): Here's what we have for new clients: a $50 credit ...
  AVA (step): What did you have in mind?
CALLER: Um.
      (fragment held, not a turn -> nothing is spoken)
CALLER: Well.
      (fragment held, not a turn -> nothing is spoken)
CALLER: What was the, uh-
      (fragment held, not a turn -> nothing is spoken)
CALLER: Um. Well. What was the, uh- What was the, the station one again?
  AVA (step): Sorry, which treatment did you have in mind?
CALLER: Sorry, what was the- what was the facial one again? The facial one?
  AVA (step): I can run through two or three options, or a free virtual consultation
              can help you pick - which would you prefer?
CALLER: No, I'm talking about the, the facial. Treatment. What was that, the, the offer again?
      (step question SUPPRESSED: just asked, record unchanged -> the model's answer is the turn)
```

The three fragments cost three model runs on the real call (01:41:11.382, 01:41:12.278,
01:41:16.764), three broadcast interruptions and two extra "What did you have in mind?"; they
now cost nothing. The treatment slot is no longer filled with a row that names nothing, and the
caller's third repetition is answered instead of re-asked. Record at the end: `flow=new_booking`,
`returning_client=False`, `offers_done=True`, `pending=offers/service_kind/facial`,
`misses={'service': 1}` — nothing stored that the caller did not choose.

---

## Deviations

- **`is_question` cannot see a stripped question, so item 1 does not fire on this call's own
  tool arguments.** The model sent `{'said': 'the facial one'}`, not the caller's sentence;
  evidence: `01:41:26.081 ... with arguments {'said': 'the facial one'}`. Item 2 is what
  repairs that turn. Recorded rather than worked around: reading the caller's last utterance
  inside `flow.apply` would mean giving a pure function the transcript, and the real answer is
  the memo's `answer_question` tool in phase A.
- **No schema field and no bundle edit for item 2.** The item offered a `generic` flag; a shape
  rule was chosen instead because it needs no re-import before the demo and no tenant has to
  re-author a catalog. Evidence that it is exact on this bundle: it flags `facial`,
  `laser_hair_removal` and `microchanneling` and nothing else. The cost is `$99 express
  treatment`, which the shape rule misses (see item 2's live-call notes).
- **Item 2 needed a second commit for a regression it caused.** Removing the placeholder from
  the candidate list sent "maybe a facial" to a `which` between two unrelated facials;
  `4976d0d` routes a bare category word to the kind instead. Found by reading
  `scenarios/promptfooconfig.yaml` rather than by a test, which is why the first commit was
  green and wrong.
- **The stale-interim promotion is not the cause of item 3.** `_promote_stale_interim` logged
  nothing between 01:40:02 and 01:41:58, so the fix went into `RulesGateProcessor`'s handling
  of real finals instead. Evidence: `grep -c "promoting the interim" serve_clean.log` is 3, and
  all three lines are at 01:39:58.101, 01:40:00.161 and 01:40:02.240, before this call's first
  caller turn.
- **`NO_CONTENT_WORDS` is narrower than a plain reading of the item's list, and `is_fragment`
  grew a second argument.** The affirmative backchannels came out in `958b928` ("Mhm." and
  "Right." are answers to `ask_returning`), and `1cd9279` made digits content and stood "okay"
  and "ok" down at a yes/no step rather than dropping them from the list the founder gave.
  Both were review findings on item 3's own word set, recorded as their own commits because
  the item's commit had already landed.
- **`is_fragment` treats a question mark as content**, which the item's word list does not say.
  Without it "What?" — a caller asking for the question again — would be swallowed and the
  caller left in silence, which is the opposite of what item 3 is for.
- **"sorry" is not a question marker**, though the item lists `"sorry?"`. With the question
  mark it is already covered; as a bare word it would refuse "Sorry, the classic facial",
  which is a correction.
- **`tool_ignored` now delegates to the new `tool_refusal`.** The published V1 name and
  signature are unchanged; the voice handler calls `tool_refusal` so one pure `apply` yields
  both the flag and the reason.
- **A silent turn on an unchanged record is now silent.** V1's `test_a_silent_model_turn_still_gets_the_question`
  asserted the opposite; it is renamed and extended rather than deleted. This is the founder's
  item 4 as approved ("the second time the runtime stays silent and the model's turn, if any,
  stands").

## Commits

In git order; one per item, plus two corrections to item 3's word set and item 4's dead flag
found in review after their own commits had landed. Each was checked out on its own (`git archive <rev>
runtime` into a scratch tree, then ruff and pytest there with `PYTHONPATH` pointing at the
archive), so no commit in this run is green only because of a later one.

| hash | item | what | standalone |
|---|---|---|---|
| `b277622` | 1 | `fix(brain): a question is not an answer to the open slot` | 60 passed, ruff clean |
| `117cb18` | 2 | `fix(brain): a generic category entry resolves to a kind, not a treatment` | 48 passed, ruff clean |
| `8563882` | 3 | `fix(voice): a fragment with no content words is not a turn` | 45 passed, ruff clean |
| `2f2a247` | 4 | `fix(voice): the fixed step question never fires twice on an unchanged record` | 46 passed, ruff clean |
| `43ea707` | 4 | `refactor(voice): drop the flag the repeat suppression no longer reads` | 58 passed, ruff clean |
| `958b928` | 3 | `fix(voice): an affirmative backchannel is an answer, not a fragment` | 41 passed, ruff clean |
| `1cd9279` | 3 | `fix(voice): digits are content, and "Okay." answers a yes/no question` | 84 passed, ruff clean |
| `4976d0d` | 2 | `fix(brain): a category word the rest does not narrow is a kind` | 101 passed, ruff clean |
| this one | — | `docs(report): the narrow four-item fix for the 2026-09-11 call` | — |

`43ea707` is item 4's tail: `OutputGuardProcessor._spoke_this_turn` existed for the one
condition item 4 rewrote, so after `2f2a247` nothing read it. Removed rather than left as
write-only state; no behaviour change.

## Full suite

One fresh scratch database for every run in this task: `spatalk_test_fix_1230`, created with
`docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_fix_1230"`.
`spatalk`, `portal` and `spatalk_test` were not touched, and the runtime on port 8000 was
neither restarted nor signalled.

```
cd runtime && TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_fix_1230 \
  .venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider

FAILED tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick
1 failed, 1379 passed, 2 skipped, 1 warning in 1755.58s (0:29:15)
```

`ruff check spatalk tests scenarios` -> All checks passed.

### One failure is not mine

1,379 of 1,380 runnable tests pass, against V1's 1,343: 36 more tests than V1 reported, of
which 13 are this task's (12 new plus 1 renamed, which counts once) and the rest arrived with
the neighbouring work committed on main since.

The one failure is the pre-existing scheduler timing test recorded in
`voice-regression-V1.md`: it starts `run_scheduler_forever` and polls
`alerts.last_scheduler_tick()` for three seconds. Verified pre-existing rather than assumed —
run against `118952a`, this task's baseline, archived with `git archive` and imported with
`PYTHONPATH` so the archive's own `spatalk` is the one under test:

```
cd <archive>/runtime && TEST_DATABASE_URL=...spatalk_test_fix_1230 PYTHONPATH=<archive>/runtime   python -m pytest -q "tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick"
  asyncio.exceptions.CancelledError
1 failed in 5.45s
```

None of this task's six source files mentions the scheduler, the job queue or the alert module
(`grep -l "scheduler\|last_scheduler_tick"` over all six returns nothing). Left alone.

### The promptfoo suite was not run

`scenarios/promptfooconfig.yaml` needs `GOOGLE_API_KEY` and a paid Gemini call per case, and
the standing rule is one run per QA gate, so it is the orchestrator's. It was read line by
line instead, and that is where `4976d0d` came from: the case "step treatment, a kind of
treatment" sends "I was thinking a facial" and expects `ask_service_kind`, which item 2's
first cut would have failed. After `4976d0d` every case that goes near this work reads
correctly on paper:

- "step treatment, a kind of treatment" -> kind `facial` -> `ask_service_kind`, as asserted.
- "step treatment, a named treatment" ("the hydrabrasion facial") -> exact `hydrabrasion_facial`
  -> `ask_name`, unchanged.
- "changing an answer: the treatment is asked again" passes `service_id: classic_facial`, a
  specific treatment, so `change_answer` still reopens the step and still expects `ask_service`.
- Eleven cases pass `service_id: facial` (ten) or `laser_hair_removal` (one) **in the `slots` fixture**.
  Those are stored values, not resolver results, and both ids still exist in the catalog, so
  the renderer still names them. Unaffected.

No case asserts on a fragment, a refused tool result, or a repeated step question, so items 1,
3 and 4 are invisible to it. The suite still has to be run at the gate.

## Reference docs

- `docs/reference/tenant-config.md`, under `services.yaml`: what a generic category entry is,
  how it is recognised without a schema field, and that it resolves to a kind.
- `docs/reference/flows.md` §8: point 3 now says a refused call carries a readable reason and
  names the three refusals; point 4 adds the two things that are never resolved (a question,
  and a category placeholder); a new point 7 states the two call-only rules — the same rendered
  question never twice running on an unchanged record, and a content-free utterance is not a
  turn. `flows.md` wins over a plan when they disagree, so it had to move with the code.

## Notes for neighbours

- `Applied` gained `rejection: str | None = None`. Anything constructing an `Applied`
  positionally would break; everything in the repo uses keywords. `run_tool`'s five-value
  return is unchanged.
- The voice tool-result payload gains a `"rejection"` key **only when there is one**, alongside
  `"spoken"`, `"outcome"` and `"ignored"`. It goes to the model as a function response;
  nothing else reads it.
- `Brain.turn` (the text channels) does not surface the rejection: `run_tool` still returns
  nothing for a refused call and the driver re-asks the open question. The voice path is what
  the founder's items are about; extending it to text is a one-line change in `run_tool`'s
  return, which V1 deliberately froze.
- `match_service` now returns `kind` with candidates populated. `flow._service` ignores the
  candidates (`Pending(kind="offers")` carries only the category), so nothing downstream
  changed; phase B is the consumer they exist for.
- `RulesGateProcessor` holds a `_held_fragment` string for the life of the call. It is
  prepended to the next content-carrying transcription and never otherwise flushed, so a call
  that ends on a fragment loses nothing that was ever a turn.
- `rules.is_fragment` takes `yes_no_step: bool = False`. The default keeps every caller
  working, the way `rules_gate`'s `name_step` does; the one in-repo caller passes it.
- `RulesGateProcessor` now imports `step_tools` from `spatalk.brain.flow`, so the gate depends
  on the flow's tool table rather than a list of steps of its own.
