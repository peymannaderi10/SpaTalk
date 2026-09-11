# Voice regression V1: the founder's call of 2026-09-10 20:53
Status: done with deviations
Commit: 1336896, e8ae57d, ff065ae, 88a6326, plus the docs commit that carries this file
Tests: `pytest tests/test_resolve.py tests/test_rules.py tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_flow_draft.py tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_voice_steps.py tests/test_voice_echo.py tests/test_voice_filler.py tests/test_voice_turns.py tests/test_structural_honesty.py tests/test_renderer.py tests/test_guard.py` -> 131 passed; `pytest tests/test_driver.py tests/test_driver_flow.py tests/test_text_service.py tests/test_text_scenarios.py tests/test_prompt_booking_flow.py tests/test_text_sms.py tests/test_lead_context.py tests/test_lead_context_verification.py tests/test_tools_prompt.py tests/test_real_model_findings.py` -> 199 passed, 2 skipped; 19 new tests and 1 renamed and strengthened; full suite -> 1343 passed, 2 skipped, 1 pre-existing failure (see "Full suite")
Interfaces produced: `spatalk.brain.resolve.shares_a_word`, `spatalk.brain.rules.rules_gate(text, cfg, name_step=False)`, `spatalk.brain.rules.BARE_ANSWER_LEAD`, `spatalk.brain.rules.NAME_STEP_SUPPRESSED`, `spatalk.brain.flow.tool_ignored`, `spatalk.brain.driver.drop_trailing_question`, `spatalk.voice.session.VoiceSession.ignored_tools`, `VoiceSession.last_question`, `VoiceSession.last_question_slots`, `VoiceSession.remember_question`, `VoiceSession.asked_already`, `spatalk.voice.handlers.IGNORED_TOOL_RETRIES`

The call: conversation `85b942b6-3e11-4496-8059-32d4e377feb8`, tenant skincentrix, 2026-09-10 20:53:21 to 20:56:26 local, 13 model turns, one item filed (id 17, `escalation_payment`, urgent, no contact name). Runtime log `serve.log` lines 60 to 730, ANSI stripped. The 2026-09-03 calls the founder liked (`serve-call17/18/19.log`) are the comparison throughout.

---

## Symptom 1 — "it kept talking when i tried to talk ... I had to repeat myself many times"

### Root cause

Not the barge-in tuning. Every interruption knob is byte-for-byte what it was on 2026-09-05, and every barge-in in this call worked:

```
git log -p --since=2026-09-05 -- runtime/spatalk/voice/pipeline.py
  b08e3f2  TURN_END_FALLBACK_SECS 1.0 -> 1.5      <- the only change
  44f3740  + sync_context(session, now)           <- slot engine wiring, no turn settings
git log -S "INTERRUPT_MIN_WORDS = " -- runtime/spatalk/voice/pipeline.py
  930d35b  fix(voice): barge-in needs three words while the assistant speaks   <- 2026-09-03, before the calls he liked
```

The log confirms `min_words` is still 3 while the assistant speaks and 1 while it is silent, and that three words is all it took:

```
20:54:48.642 MinWordsUserTurnStartStrategy#0 should_trigger=False num_spoken_words=1 min_words=3 bot_speaking=True
20:54:48.892 ...                             should_trigger=False num_spoken_words=2 min_words=3 bot_speaking=True
20:54:49.232 ...                             should_trigger=True  num_spoken_words=3 min_words=3 bot_speaking=True
20:54:49.232 LLMUserAggregator#0: broadcasting interruption
20:54:49.233 base_output:_bot_stopped_speaking - Bot stopped speaking
```

Four barge-ins, all honoured, 0.23 s / 0.36 s / 0.53 s / 0.59 s from the caller's first transcribed word to the audio stopping. `StartInterruptionFrame` reached the transport every time; `BotStoppedSpeakingFrame` followed within 6 ms; no echo re-feed (`scrub_echo` sits upstream of the aggregator, in `RulesGateProcessor`, so echoed words never reach the word counter — which is also why the word-count strategy cannot be replaced by a VAD one).

One thing in the log does look like the tuning and is not. At 20:54:44.074, mid-monologue,
the input VAD registered speech and then silence (`Triggered finalize event on:
frame.name='VADUserStoppedSpeakingFrame#13'`, then `End of Turn result: COMPLETE`) and no
transcription came of it and no interruption fired. That is what "we tuned the cut-off too far"
would look like — except the assistant was speaking at the time and the caller is on a phone,
so the most likely source of that speech is the assistant's own audio coming back down the
line. Which is the reason barge-in counts *transcribed* words instead of watching the VAD:
`scrub_echo` removes the assistant's echoed words in `RulesGateProcessor`, upstream of the
aggregator, so an echo can never reach the word counter, while a VAD-driven barge-in would
yield to it constantly. Loosening the cut-off is therefore the wrong lever, and a change
there needs a call, not a guess.

What changed is how much there was to talk over, and how little of it was worth hearing. Since 2026-09-05 (commits `44f3740`, `4137f55`) the runtime appends the open step's fixed question to **every** model turn, and the voice path never applied the slot engine's invariant 4 ("every question the caller hears is a tenant script; the model contributes at most one acknowledgement sentence") — `first_sentence` exists in `driver.py` for the text channels and has no counterpart in `OutputGuardProcessor`. So one turn became four utterances queued back to back:

```
20:54:37.929 Generating TTS [[warm] That's our fifty-dollar credit, which applies to any of our advanced facials.]
20:54:37.965 Generating TTS [We have a few different options for those, like the MesoJet and Sound Therapy or the Lift and Sculpt facial, which are both two hundred and ninety-five dollars.]
20:54:37.965 Generating TTS [Would you like to hear about any of those, or perhaps something else?]   <- the model's question
20:54:37.965 Generating TTS [What did you have in mind?]                                             <- the runtime's, on top
20:54:38.070 Bot started speaking
20:54:49.233 Bot stopped speaking                                                                    <- 11.2 s, ended by the barge-in
```

Bot speech spans in this call reached 22.3 s, and that four-utterance turn is one of five in which the model's question and the runtime's went out together (the full queue is under symptom 4). The founder's stutters in the transcript ("What— what's the— can you— What's the me—", "Can I— Can you— can you book me with—") are a person waiting out a monologue whose last two sentences were two different questions.

### Change

`OutputGuardProcessor` holds back a sentence that ends in `?` while a request flow is open, and drops it at the end of the turn when the runtime has a question of its own (`runtime/spatalk/voice/processors.py`). A question in the *middle* of an answer is released as soon as another sentence follows it, so only the model taking the runtime's turn is silenced. When the runtime has no question for the step, the held one is spoken rather than leaving a silent turn. The same rule reaches the text channels through `drop_trailing_question` in `spatalk/brain/driver.py`. Only the *question* half of invariant 4 is made structural on voice; see "Deliberate limits" for why the one-sentence half is not.

### Tests

`tests/test_voice_processors.py::test_the_model_does_not_ask_a_question_while_a_flow_is_open` (the exact 20:54:37 turn), `::test_a_question_in_the_middle_of_an_answer_is_still_spoken`, `::test_a_question_is_the_models_own_outside_a_flow`, `::test_a_turn_that_is_only_a_question_is_not_left_silent`. Seen failing on the first (`said == ["That's our fifty-dollar credit."]` got both sentences); the other three describe behaviour that had to survive and passed before and after.

---

## Symptom 2 — "it also takes a tiny bit too long to reply"

### Root cause

**The evidence contradicts this one.** This call was the fastest of the five measured. Perceived gap = the caller's last word (`VADUserStoppedSpeakingFrame` finalize) to the first audio out (`_bot_started_speaking`):

| call | n | median | max |
|---|---|---|---|
| 2026-09-10 (this one) | 14 | **1.31 s** | 2.43 s |
| 2026-09-03 call17 | 7 | 2.31 s | 3.52 s |
| 2026-09-03 call18 | 8 | 1.50 s | 2.29 s |
| 2026-09-03 call19 | 8 | 1.48 s | 2.33 s |

The runtime's own per-turn metric agrees — `spatalk.voice.pipeline:_finalize` across the five logs: `p50=1094ms` (this call) against 1250, 1281, 1296, 1344 and 1532 ms on 09-03. So does the model: `GoogleLLMService#0 TTFB` median 0.841 s here (n=13, min 0.635, max 1.338) against 0.961 / 0.887 / 0.944 s on the three earlier calls.

The slot engine's own worry did not materialise either. Prompt tokens are **lower** than before the slot engine (6018–6851 here, 7402–8025 on call19) and the implicit cache is still being read at the same size (`cache read input tokens: 3985–4041` against 4022–4063). There is no second model round trip per turn: 13 caller turns, 13 `Generating chat from context` lines, 13 `prompt tokens` lines. A per-step question does **not** cost an extra call, because the tool handler speaks the script itself with `run_llm=False`.

One real, measurable regression exists, and it is small: `b08e3f2` raised `TURN_END_FALLBACK_SECS` from 1.0 s to 1.5 s. That is `SmartTurnParams.stop_secs`, the silence Smart Turn waits out when its model judges the utterance unfinished (verified in `.venv/.../smart_turn/base_smart_turn.py`: `if self._silence_ms >= self._stop_ms`). It fired on 2 of 13 turns here and cost the full window each time:

```
20:53:34.634 MinWords... interim_transcription=False   (final transcription, 17 words)
20:53:36.018 base_smart_turn:append_audio - End of Turn complete due to stop_secs. Silence in ms: 1500.0
20:53:36.020 LLMUserAggregator#0: User stopped speaking
```

1.39 s and 1.44 s of dead air before the model was even called, where 09-05's setting would have cost 0.9 s. Those two turns are the 2.43 s and 2.30 s outliers in the table; the 09-03 calls had the same shape of outlier (2.15–3.52 s) because they hit the fallback four or five times each.

What the founder is most likely hearing as slowness is *when the useful words arrive*, not when audio starts: on a mid-flow turn the answer he wanted was preceded and followed by fixed script, and on three turns the whole reply was a fixed question with no answer in it at all.

### Change

None to the knob. Lowering `TURN_END_FALLBACK_SECS` re-opens exactly the fault `b08e3f2` was written for ("Ava starting before a sentence was finished"), and picking a number between 1.0 and 1.5 from a desk is the tuning-by-guess the founder has been burned by. The symptom-1, -3 and -4 changes remove roughly 1.3 s of fixed-script preamble and repeat per mid-flow turn, which is the part of "too long to reply" that *is* a regression.

### Tests

None: there is no defect here to pin. The measurement scripts are in the scratchpad (`v1/an.py`, `v1/gap.py`, `v1/spk.py`).

---

## Symptom 3 — the confused "promotion" exchange

### Root cause

Two independent defects, both visible in the stored transcript and in the tool arguments the log prints inside `Generating chat from context`.

**(a) A confirmation on a coincidence of letters.** The caller asked "Uh, what was the station one again?" and the model passed it through:

```
'function_call': {'id': 'call_1524569', 'args': {'said': 'the station one'}, 'name': 'choose_service'}
20:54:18.279 Generating TTS [Did you mean Free virtual consultation?]
```

Reproduced against the real bundle: `fuzz.WRatio("station one", "free virtual consultation") = 0.6995`, which clears `CONFIRM = 0.60`, and the whole score comes from `partial_ratio = 0.706` — the letters "station" shares with the middle of "consultation". Not one word in common. `_best` had no test beyond the score.

**(b) `change_answer` for a slot that holds nothing, then a verbatim re-ask.** The caller corrected the guess — "No, it was a $50— what was the $50 one you said?" — and the model read it as a correction:

```
'function_call': {'id': 'call_640075', 'args': {'slot': 'service'}, 'name': 'change_answer'}
20:54:29.968 Generating TTS [What did you have in mind?]        <- second time, no answer in front of it
```

No treatment was stored, so `_reopen` returned the record unchanged, `run_tool` reported nothing spoken, and `_make_handler` spoke the step question with `run_llm=False`. The same shape again four turns later, this time with the tool actually rejected:

```
20:55:35.184 WARNING spatalk.brain.driver:run_tool:451 - tool start_request ignored at this step with args {'kind': 'booking'}
20:55:35.188 Generating TTS [What did you have in mind?]        <- fourth time
```

The caller had just said "Can I— Can you— can you book me that facial?" and was answered with the same eight words he had already heard three times. He repeated himself — "Can you book me that facial, the mesojet one?" — and *that* worked, because it named the treatment. That is the whole of "it's almost like it is lacking context of the entire conversation": the model had the context and was never given the turn.

### Change

- `spatalk/brain/resolve.py`: below `ACCEPT`, a candidate must also share a word with what the caller said (`shares_a_word`) — a word that is equal, a prefix of at least `MIN_PREFIX_CHARS = 4`, or within `WORD_MATCH = 0.80` on `fuzz.ratio`. "station one" now matches nothing and the caller hears `ask_service_again` ("Sorry, which treatment did you have in mind?"). "hydroabrasion", "mira peel", "carbon peel", "Ellen" and "Alexandre" all still confirm.
- `spatalk/brain/flow.py`: `change_answer` for a slot that holds nothing is an `ignored` call, decided on the slot's value (`_slot_filled`) and not on the whole record, so a miss counter the resolver wrote does not make it look like a change.
- `spatalk/voice/handlers.py`: the first ignored tool in a caller's turn says nothing and hands the turn back to the model (`run_llm=True`) with the step's own tool list and the whole conversation. The second falls back to the fixed question, so a model that keeps calling the same tool cannot loop. The budget resets on every final transcription, in `RulesGateProcessor`, beside the "still there?" count.
- `spatalk/voice/processors.py`: the step question is not asked a second time word for word while nothing in the record has moved and the caller has just heard it (`VoiceSession.asked_already`); the model's own closing question carries that turn instead. A turn where the model said nothing always gets the script, so nothing goes silent.

Replayed through the fixed engine with the founder's own utterances and the tool calls his call actually produced (`v1/replay.py` in the scratchpad; `flow.apply` and `step_question` are pure, so no model and no database are involved):

```
CALLER: Hey, um, I'm looking to come in for a booking.
  AVA (step): Have you been in to see us before?
CALLER: No, I haven't.
  AVA (step): Would you like to hear our new-client offers?
CALLER: Um, sure, why not.
  AVA (script): Here's what we have for new clients: a $50 credit ... as a trial.
  AVA (step): What did you have in mind?
CALLER: Uh, what was the station one again?
  AVA (step): Sorry, which treatment did you have in mind?          <- was "Did you mean Free virtual consultation?"
CALLER: No, it was a $50 - what was the $50 one you said?
  tool change_answer{'slot': 'service'} IGNORED -> the turn goes back to the model, nothing spoken
CALLER: It was your offers. One was about 50 bucks.
  step question SUPPRESSED (already asked, nothing moved) -> the model's own closing question carries the turn
CALLER: What's the mesojet one?
  step question SUPPRESSED -> the model's own question
CALLER: Does it hurt?
  step question SUPPRESSED -> the model's own question
CALLER: Can you book me that facial?
  tool start_request{'kind': 'booking'} IGNORED -> the turn goes back to the model, nothing spoken
CALLER: Can you book me that facial, the mesojet one?
  AVA (step): Is there someone in particular you'd like to see, or whoever's available?
CALLER: Can you book me with Helen?
  AVA (step): Could I get your first name?
```

Seven queued "What did you have in mind?" (four of which the caller actually heard) and one confidently wrong "Did you mean Free virtual consultation?" become one "What did you have in mind?", one "Sorry, which treatment did you have in mind?", and three turns where the model's answer to the caller's question is the whole of the reply.

### Tests

`tests/test_resolve.py::test_a_close_score_with_no_word_in_common_is_not_a_confirmation`, `::test_a_misheard_first_name_still_confirms`; `tests/test_flow_apply.py::test_change_answer_for_a_slot_that_holds_nothing_is_ignored`, `::test_change_answer_looks_at_the_slot_not_the_miss_counter`; `tests/test_voice_handlers.py::test_an_ignored_tool_hands_the_turn_back_to_the_model`, `::test_the_ignored_budget_resets_when_the_caller_speaks`, `::test_a_tool_the_step_does_offer_still_speaks_the_next_question`; `tests/test_voice_processors.py::test_the_step_question_is_not_repeated_word_for_word`, `::test_the_step_question_comes_back_once_the_record_moves`, `::test_a_silent_model_turn_still_gets_the_question`. All seen failing first: `assert match_service("the station one", cfg).kind == "none"` returned `confirm`; `assert a.ignored` returned `Applied(..., ignored=False)`; `AttributeError: 'VoiceSession' object has no attribute 'ignored_tools'`; `assert [] == ['Have you been in to see us before?']`.

---

## Symptom 4 — "it isnt as human sounding as it was before"

### Root cause

The same two mechanisms, seen from the ear rather than the ledger. Every `Generating TTS`
line of the call, in order (the transcript hides some of this, because an utterance the caller
barged in on is truncated in the context; the queue is the honest record of what was sent to
be spoken):

```
 1  [warm] Hi there, thanks for calling Skincentrix ... What can I help you with today?
 2  Have you been in to see us before?
 3  Would you like to hear our new-client offers?
 4  Here's what we have for new clients: a $50 credit ...
 5  What did you have in mind?                                             <- 1
 6  Did you mean Free virtual consultation?
 7  What did you have in mind?                                             <- 2
 8  [warm] That's our fifty-dollar credit, which applies to any ...
 9  We have a few different options for those, like the MesoJet ...
10  Would you like to hear about any of those, or perhaps something else?   * model
11  What did you have in mind?                                             <- 3
12  [warm] The MesoJet and Sound Therapy facial is two hundred and ninety-five dollars.
13  It's an award-winning oxygen-infusion treatment that detoxifies ...
14  Would you like me to get you set up with a consultation ...?            * model
15  What did you have in mind?                                             <- 4
16  [warm] The MesoJet and Sound Therapy facial is a sixty-minute ...
17  It's an award-winning oxygen-infusion facial that detoxifies ...
18  Would you like to get that set up, or would you like to hear ...?       * model
19  What did you have in mind?                                             <- 5
20  [reassuring] That's a great question, but since that's a clinical concern ...
21  Would you like me to get that request started?                          * model
22  What did you have in mind?                                             <- 6
23  What did you have in mind?                                             <- 7
24  Is there someone in particular you'd like to see, or whoever's available?
25  [warm] Our facial and skin programs are led by our founder ...
26  Since I don't have access to the calendar, I can't say who is available ...
27  Would you like to go with anyone, or should I note that you're open to anyone?  * model
28  Is there someone in particular you'd like to see, or whoever's available?
29  Could I get your first name?
30  I can't take or discuss payment details on this line ...
```

Thirty utterances in three minutes. "What did you have in mind?" was queued **seven** times,
twice back to back at 22 and 23. "Is there someone in particular…" twice. Five times (10/11,
14/15, 18/19, 21/22, 27/28) the model asked a question and the runtime asked a different one
straight after it, in the same breath of audio.

Compare the calls the founder liked: 2026-09-03 call18 and call19 read `[cheerful] Welcome!We
have some wonderful options for new clients…`, `[warm] We can definitely help with that!Our
Mirapeel facial…`, `Which would you prefer?` — the model wrote the whole turn, including the
question, and there was one question in it.

So the regression in voice is structural, not a matter of phrasing: the runtime took the
question away from the model and then asked the same one over and over, and the model was
allowed to ask its own on top.

### Change

The three changes above, together. After them:

- exactly one question per turn, and it is the tenant's script while the record is moving;
- the script is never repeated word for word with nothing moved — the model's own wording carries that turn;
- the model's answer to a side question survives in full (§4.3 allows it in words), so an explanation is still an explanation and not a truncated one.

**Deviation, recorded deliberately.** The slot engine design §3 invariant 4 says "Every question the caller hears is a tenant script." Under the repeat suppression a caller can hear a question the model worded, in the one case where the runtime would otherwise repeat itself verbatim. The runtime keeps ownership of *which slot is open* (the tool list and the step brief are unchanged) and of every outcome sentence; what it gives up is asking the same words twice. `file_request` and `send_link` are still absent until the slots are filled, `ItemDraft` still comes only from `draft_from`, and every slot is still closed. Non-negotiable 3 ("fixed wording is config") is untouched: the disclosure, clinical, complaint, payment, callback and goodbye scripts are all still the only source of outcome wording.

**Second deviation.** `docs/reference/flows.md` §10.3 and the slot engine design §7 both say a tool the step did not offer gets the open question re-asked. On this call that turned a plain booking request into a bare fixed question three times. The first ignored call in a caller's turn now hands the turn to the model; the re-ask is still what the second one does. `flows.md` is updated to match the code.

### Tests

As symptom 1 and 3 above. `tests/test_voice_steps.py::test_a_tool_the_step_did_not_offer_is_ignored_and_the_model_answers` is the renamed and extended form of `…_and_the_question_repeated`: it still asserts nothing is written and nothing is filed, and now pins both halves of the new contract (first call silent with `run_llm=True`, second call speaks `ask_returning` with `run_llm=False`). That is the one existing test whose expectation changed; it was strengthened, not weakened.

---

## Symptom 5 — "the call randomly ended at the end??"

### Root cause

Confirmed exactly as hypothesised, and it is two defects.

```
20:56:14.662 Generating TTS [Could I get your first name?]
20:56:19.699 INFO  spatalk.voice.processors:process_frame:172 - rules gate: payment ('payment') -> item 17
20:56:19.699 DEBUG pipecat.pipeline.worker:_wait_for_pipeline_end:1219 - PipelineWorker#0: Closing. Waiting for EndFrame#0 ...
20:56:19.705 Generating TTS [I can't take or discuss payment details on this line. The team can help with that when they call you back, as soon as they're free.]
20:56:26.724 PipelineWorker#0: EndFrame#0 reached the end of the pipeline, pipeline is closing.
```

Transcript: assistant "Could I get your first name?", user " Yeah, payment.". Soniox heard *Peyman* as *payment*.

**(a) The lexicon matched a name answer.** `payment` is a bare word in `DEFAULT_LEXICONS["payment"]` and `rules_gate` knew nothing about which step was open.

**(b) The gate ended the call.** `RulesGateProcessor` queued an `EndFrame` after *every* non-clinical match, unconditionally — `processors.py`, the two lines after the escalation script. `docs/reference/flows.md` §1.8 only ever gave that power to the emergency script, which is the one whose wording tells the caller to hang up and dial 911; `human_request`, `complaint` and `payment` all promise a callback and leave the caller on the line. The item that was filed (id 17, `escalation_payment`, urgent, `contact_name: None`) is the visible cost of (a); the dropped booking is the cost of (b).

The name step's "refuses words that are not a name" logic (`9b59564`) never got a chance to run here: the gate swallows the transcription before `give_name` is called. With the gate suppressed, `_clean_name("payment")` returns `"Payment"` and stores it — see "needs a live call" below.

### Change

- `spatalk/brain/rules.py`: `rules_gate(text, cfg, name_step=False)`. When the open step is the name and the utterance is a bare answer — one or two words once `BARE_ANSWER_LEAD` ("yeah", "um", "it's", "my name is", …) is off the front, and no question mark — the two lexicons in `NAME_STEP_SUPPRESSED` stand down: complaint and payment. Those are the two whose words are what a recogniser produces for a first name ("payment" for Peyman, "sue" for Sue) and whose scripts promise a callback rather than urgent care. The three that cannot wait are untouched, so "Seizure.", "I can't breathe", "Operator" and "Burning." all still gate on one or two words, while "Yeah, payment.", "It's Bill.", "Um, refund" and "Sue" do not. A whole sentence at the name step is not a bare answer either, so "Actually, can I pay over the phone with my card?" still gates.

  Suppressing every lexicon was the first cut and it was too broad: a caller who answers the
  name question with "Operator" wants a person, and missing that costs far more than a wrongly
  filed billing escalation. Narrowed to the two that actually collide with names.
- `spatalk/voice/processors.py` and `spatalk/brain/driver.py` pass `name_step=next_step(...) == Step.NAME`, so voice and the text channels share the rule.
- `spatalk/voice/processors.py`: the `EndFrame` is queued only when `gate.reason == "emergency"`.

Replayed at the founder's exact state (`Slots(flow="new_booking", returning_client=True,
practitioner="Helen Courbetis", service_id="mesojet_facial")`, open step `Step.NAME`):

```
rules_gate(" Yeah, payment.", cfg, name_step=True)  -> None          (was GateDecision(payment))
give_name("payment")                                -> first_name "Payment", next step PHONE
next question                                        -> ask_phone_same
```

The booking survives and the call carries on to the number question, instead of a payment
refusal, an urgent item with no name and a hang-up. The stored name is wrong — see "needs a
live call".

### Tests

`tests/test_rules.py::test_a_bare_answer_at_the_name_step_is_not_a_billing_or_complaint_escalation`; `tests/test_voice_processors.py::test_a_bare_answer_at_the_name_step_is_not_an_escalation` (the founder's utterance, at the founder's step, asserting no item, no `EndFrame`, band 1), `::test_a_payment_match_files_the_item_and_leaves_the_line_open`, `::test_a_complaint_match_leaves_the_line_open_too`, `::test_an_emergency_match_is_the_one_that_ends_the_call`.

---

## Tenant config

No change to `runtime/tenants/skincentrix/*.yaml`. Nothing in this regression came from the wording, and the one config option that would touch symptom 2 — `scripts.fillers`, which is `[]` and makes `FillerProcessor` a no-op — would add *more* speech, which is the opposite of what the founder asked for. Worth a deliberate decision on a live call, not a silent change tonight.

## Commits

One per root cause, in dependency order. Each was checked out on its own and is `ruff` clean
with its own tests passing (`git archive <rev> runtime` into a scratch tree, then ruff and
pytest there), so no commit in this run is green only because of a later one.

| hash | root cause | what |
|---|---|---|
| `1336896` | symptom 3(a) | `fix(brain): a "did you mean" needs a word in common, not a lucky substring` — 7 passed |
| `e8ae57d` | symptom 3(b) | `fix(brain): a tool the step did not offer hands the turn back to the model` — 53 passed |
| `ff065ae` | symptoms 1 and 4 | `fix(voice): one question a turn, and never the same one twice over` — 36 passed |
| `88a6326` | symptom 5 | `fix(voice): a mis-heard first name is not a payment escalation, and only the 911 script ends a call` — 60 passed |
| this one | — | `docs(reference,report): the 2026-09-10 voice regression, cause by cause` |

## Full suite

One fresh scratch database for every run in this task: `spatalk_test_v1_2110`, created with
`docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_v1_2110"`.
`spatalk`, `portal` and `spatalk_test` were not touched.

```
cd runtime && TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_v1_2110   .venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider

FAILED tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick
1 failed, 1343 passed, 2 skipped, 1 warning in 1848.63s (0:30:48)
```

1343 of 1344 runnable tests pass. The one failure is the pre-existing scheduler timing test
below, which fails identically with every change in this task stashed.

`ruff check spatalk tests scenarios` -> All checks passed.

### One failure is not mine

`tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick` fails on this
machine, and it fails the same way with every change in this task stashed:

```
git stash push -- docs/reference/flows.md runtime/spatalk runtime/tests
pytest "tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick"
  tests/test_ops_alerts.py:430: AssertionError: assert None == datetime.datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
1 failed in 5.64s
git stash pop
```

It starts `run_scheduler_forever` and polls `alerts.last_scheduler_tick()` for three seconds.
Nothing in this task goes near the scheduler, the job queue or the alert module. Left alone
and reported rather than touched, since fixing someone else's timing test was not the job.

### The promptfoo suite was not run

`scenarios/promptfooconfig.yaml` needs `GOOGLE_API_KEY` and a paid Gemini call per case, and
the standing rule is one run per QA gate, so it was left for the orchestrator. Read rather than
run, nothing in it looks stale: `asserts.py` checks bands, outcomes, urgency and the absence of
completion language, none of which these fixes move, and the only case that exercises
`change_answer` ("changing an answer: the treatment is asked again") passes `service_id:
classic_facial`, a slot that holds something, so it still reopens and still expects
`ask_service`. The one behaviour worth a fresh look there is `drop_trailing_question` on the
text path: a case whose expectation is the model's own closing question would now see it
stripped. None of the current cases assert on one.

### A test the QA gate caught

`tests/test_qa_gate_a.py::test_no_provider_is_hard_wired_into_the_brain_or_the_ledger[brain/rules.py]`
failed on the first full run because the comment I wrote in `rules.py` named the transcription
vendor. That gate exists for exactly this (non-negotiable 4), and it was right: the comment now
says "the recogniser". Worth knowing that a *comment* trips it, since the temptation when
writing up a call is to name the vendor that mis-heard the word.

## Needs a live call to settle

1. **`TURN_END_FALLBACK_SECS`.** 1.5 s costs 1.4 s of dead air on the turns Smart Turn judges unfinished; 1.0 s brought Ava in before the founder had finished a sentence. Both faults are real and the same knob controls both. A single call that deliberately pauses mid-sentence and then finishes a sentence cleanly, at 1.2 s, would settle it. Do not change it from a desk.
2. **A mis-transcribed first name is now stored.** With complaint and payment standing down at the name step, "payment" reaches `give_name` and `_clean_name` capitalises it to "Payment", so the item carries a wrong name instead of no name and a dead call. Verified: `give_name("payment")` stores `"Payment"` and the call moves to the number question. Rejecting every word that appears in a gate lexicon would catch it, but "Sue" is in the complaint lexicon and is a common first name, so that fix needs a decision rather than a guess: either read the name back for confirmation at the name step, or accept the occasional wrong name. A wrong name on a live request is a smaller failure than a dropped call, which is why it ships this way tonight.
3. **The repeat suppression on the ear.** The tests pin the mechanism; whether a caller who asks two side questions in a row feels prompted enough after the second one is a judgement only a call can make.
4. **The barge-in delay.** 0.23–0.59 s of overlap after the caller's first transcribed word is the cost of `min_words=3`, and 2026-09-03 shows why one word is worse. Unchanged here; worth listening for specifically on the next call now that the monologues are shorter.
5. **The prompt cache misses on a step change.** 5 of 13 turns had no `cache read input tokens` line, and each is a turn where `next_step` moved — the step brief lives at the end of the system message, so the cached prefix ends where it changes. It cost nothing measurable on Flash-Lite (miss median TTFB 0.787 s against 0.913 s for the hits) and prompt tokens are down overall, so nothing was changed for it. Worth watching on the monthly cost report rather than in code.

## Deliberate limits, so they are not a surprise

- **Two questions in one model turn.** The guard holds one sentence. If the model asks two
  questions in a row and then stops ("Do you mean the express one? Or the classic?"), the first
  is released when the second arrives and the second is dropped, so the caller hears one model
  question plus the runtime's. It did not happen on this call and holding a queue is more
  machinery than the evidence asks for. Strictly better than before either way.
- **The one-acknowledgement half of invariant 4 is still not enforced on voice.** `driver.py`
  truncates the model's text to one sentence when a tool ran (`first_sentence`); the voice
  pipeline does not. §4.3 wants a side answer in full, so only the *question* half of the
  invariant is structural here. On this call it made no difference — every model turn either
  called a tool with no words or produced words with no tool — but a turn that does both will
  read longer on the phone than on SMS.

## Notes for neighbours

- `rules_gate` grew a third parameter with a default, so every existing call site keeps working. Both in-repo callers (`RulesGateProcessor`, `Brain.turn`) now pass it.
- `run_tool`'s five-value return is unchanged. The ignored case is detected ahead of it with the new pure `flow.tool_ignored`, so `tests/test_lead_context_verification.py` and anything else unpacking five values is untouched.
- The voice tool-result payload gained an `"ignored"` key alongside `"spoken"` and `"outcome"`. It goes to the model as a function response, nothing else reads it.
- `VoiceSession` gained three fields (`ignored_tools`, `last_question`, `last_question_slots`) and two methods (`remember_question`, `asked_already`). Anything constructing a `VoiceSession` gets the defaults.
