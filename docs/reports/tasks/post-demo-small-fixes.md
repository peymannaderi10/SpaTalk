# Post-demo small fixes (2026-09-05)

Three independent tasks, one commit each. Runtime tests from `runtime/` with `uv run pytest -q`; portal tests in WSL with `npx prettier --write` then `npx vitest run`. The runtime and the portal were not restarted, the bundle was not imported, nothing was pushed, no paid API was called.

## Task 1: the utterance that trips the rules gate is written to the transcript
Status: done with deviations
Commit: 9413957
Tests: `uv run pytest -q tests/test_voice_processors.py tests/test_text_service.py` -> 25/25 (the voice test was seen failing: `turns == []`); full suite -> 1200 passed, 2 skipped
Interfaces produced: `VoiceSession.context` (the call's `LLMContext`, set in `spatalk/voice/pipeline.py`); `RulesGateProcessor` adds `{"role": "user", "content": <utterance>}` to it before pushing the fixed `TTSSpeakFrame`
Deviations:
- No code change on the text channel because `TextConversationService.handle_inbound` already stores the user message (`append_message(..., "user", text)`) before `Brain.turn` runs the gate; evidence: `test_a_message_the_rules_gate_answers_is_stored_before_the_fixed_reply` passed on its first run and is kept as a regression pin.
- On voice the gate swallows the `TranscriptionFrame`, so the user aggregator never wrote the turn; `_finalize` reads `context.messages` at the end of the call, which is why the fix writes to the context rather than to the database directly (the order user -> assistant is kept because the assistant aggregator appends the spoken script later).
Notes for neighbours:
- Takes effect on voice only after the runtime is restarted (founder's step).

## Task 2: an emergency lexicon alone carries the 911 line; pain words leave the clinical list
Status: done with deviations
Commit: 9235b94
Tests: `uv run pytest -q tests/test_rules.py tests/test_renderer.py tests/test_voice_processors.py tests/test_driver.py tests/test_qa_gate_a.py tests/test_social_scenarios.py tests/test_tenant_bundle.py tests/test_call_notes.py tests/test_lead_context_verification.py` -> 235/235 (21 seen failing first); full suite -> 1212 passed, 2 skipped; portal `npx vitest run src/client/formatting.test.ts` -> 25/25
Interfaces produced: `DEFAULT_LEXICONS["emergency"]`, `ORDER = ["emergency", "human_request", "clinical", "complaint", "payment"]`, `Lexicons.emergency`, `Scripts.emergency`, `Scripts.emergency_text`, `EscalateReason` gains `"emergency"`, item type `escalation_emergency`, `_ESCALATION_SCRIPTS["emergency"]`, `TYPE_LABELS["escalation_emergency"]`, portal `itemTypeLabel("escalation_emergency") == "Emergency"`
Deviations:
- No Alembic migration: `items.type` is `String(40)` (`spatalk/models.py:130`), not a Postgres enum; the enum list in `docs/reference/data-model.md` was extended instead.
- Script keys are `emergency` and `emergency_text`, not `escalation_emergency`: the `Scripts` model names band-3 scripts by reason (`clinical`, `clinical_text`) and the item type carries the `escalation_` prefix. The text variant exists for the same reason `clinical_text` does (QA gate C: "hang up" and "at this number" make no sense in a chat window); the renderer routes both reasons to `<reason>_text` off voice.
- `emergency` and `emergency_text` have defaults (unlike `clinical`) so the config stored in `tenant_config_versions` before this change still loads at the next restart without a bundle import; evidence: `config_from_json` on the bundle's JSON with the two keys removed and the old clinical wording restored -> loads, `"911" in scripts.emergency` True. For the same reason the validator requires 911 in the emergency scripts but does not forbid it elsewhere (the stored config still carries the old clinical wording and would be refused at load); the "only script that says 911" rule is enforced by `test_only_the_emergency_scripts_say_911` on the bundle and on the defaults.
- "allergic reaction" moved from the clinical list to the emergency list (the task lists it as an emergency phrase; with `emergency` first in `ORDER` the clinical copy was dead).
- The model's `escalate` tool enum and description gain `emergency`, so a life-threatening phrase the lexicon misses can still reach the 911 script; without it the model's only route was `clinical`, which no longer says 911, a regression from the day before.
- The emergency terms were added wherever the clinical lexicon was reused: the call-notes health scrub (`ledger/notes.py`), the nightly lexicon scan (`ops/nightly_audit.py`) and the cosmetic-concern check in `tenants/schema.py`.
- Existing assertions that a rash or a burn reply contains "911" were inverted in `test_driver.py`, `test_qa_gate_a.py`, `test_renderer.py`, `test_voice_processors.py`, `test_social_scenarios.py`, `test_tenant_bundle.py` (that is the behaviour the task reverses); every file gained an emergency counterpart asserting 911, and `test_qa_gate_a.py` gained five emergency paraphrases in the gate table plus the two new scripts in the when-to-expect-contact test.
- promptfoo: the four `icontains "911"` assertions on clinical scenarios became `not-icontains`; one emergency scenario was added. The suite was not run (paid API).
- `docs/runbooks/local-demo.md` step 4 no longer says the clinical script includes the emergency sentence.
- Prettier reformatted two unrelated lines in `portal/src/client/formatting.ts` and `formatting.test.ts` (its own output for the checked-in files).
Notes for neighbours:
- The founder must import the Skincentrix bundle for the new `clinical` wording to be spoken; until then, after a restart, the stored config's clinical script (with 911) is used and the emergency scripts fall back to the defaults, which are word-for-word the bundle's.
- `spatalk/brain/prompt.py` was not changed; the tool description tells the model what `emergency` is for.

## Task 3: the request card says "Follow up by"
Status: done
Commit: a335e34
Tests: `npx vitest run src/client/requests.test.ts` -> 15/15
Interfaces produced: `requestFacts()` label `"Follow up by"`; `REQUEST_SORTS` "due" label `"Follow up soonest"`
Deviations:
- The sort option "Promised soonest" was relabelled too, for the same reason. The plan text in `docs/superpowers/plans/2026-09-03-lead-context-plan.md` names the label and was updated; the e2e tests never named it; the historical reports were left alone. Prettier reformatted the sort test's fixture lines.

## Working tree
`docs/research/rates.json` and `portal/src/admin/QuoteBuilder.test.tsx` were modified by another session while this ran and were not staged.
