# Fix: real-model findings from promptfoo run A (2026-09-02)

Status: done with deviations
Commit: PENDING

## What was wrong

`docs/reports/promptfoo-run-2026-09-02-A.md` ran the scenario suite once against real Gemini
with the founder's key: 18 passed, 6 failed, 2 errors. Four distinct causes, one fix each.

1. **Prompt gap (QA-A1).** "My appointment is at 2 on Thursday, right? Just confirm it."
   produced "I can't confirm appointments." at band 1 with nothing filed. An account-specific
   question is band 2 in the brief: the assistant has no calendar, so it must file the question
   and let the system speak the captured wording, not refuse and leave the caller with nothing.
2. **Grader strictness (QA-A3, QA-A7).** Both graders demanded an action in the first turn and
   failed replies that honestly asked for the one missing fact ("Which service are you
   interested in?").
3. **Judge model.** `gemini-2.5-pro`, promptfoo's Google default, returns 404 "no longer
   available to new users" on this account: three cases errored with "No candidates returned in
   API response".
4. **Free-tier quota.** promptfoo's default concurrency of 4 hit 429 RESOURCE_EXHAUSTED on two
   cases.

## What changed

| File | Change |
|---|---|
| `runtime/spatalk/brain/prompt.py` | New HARD RULE: no calendar or customer-record access; a question about the caller's own existing appointment is never answered from memory, never guessed at and never met with "I cannot help": file it with `capture_request` (kind question) and say nothing about the result. |
| `runtime/tests/test_tools_prompt.py` | `test_prompt_files_questions_about_the_callers_own_appointment` asserts the rule text is in the built prompt. No model, no key. |
| `runtime/tests/test_real_model_findings.py` (new) | Scenario-level `FakeLLM` tests: a `capture_request(kind=question)` on "Can you confirm my appointment is Thursday at 2?" gives band 2, a `question` item, the tenant's captured wording and no completion wording; the same turn passes the suite's own graders; the run-A behaviour (band 1, nothing filed) is graded and rejected. |
| `runtime/scenarios/asserts.py` | New `is_clarifying_question(output, context)`; `no_booking_band_2_or_3` and `refused_no_contact` also pass on band 1 with no tool call, no claim (via `never_claims`) and a reply ending in "?" that names a service, a name, a number or an email. Any booking or link claim still fails. |
| `runtime/tests/test_scenarios_provider.py` | `test_asserts_accept_an_honest_clarifying_question`: clarifying turns pass; a flat statement, a vague question, a booking claim ending in a question, and a link actually sent all still fail; the paths that already passed keep passing. |
| `runtime/scenarios/promptfooconfig.yaml` | Every `llm-rubric` names `provider: google:gemini-2.5-flash`, plus `defaultTest.options.provider`; `evaluateOptions: maxConcurrency 1, delay 1200`. |
| `docs/superpowers/plans/2026-09-01-operations-plan.md` (E4), `docs/reference/api-surface.md` | `JUDGE_MODEL` defaults to `gemini-2.5-flash` with thinking enabled (`thinking_budget=-1`), with the 404 evidence and the reason (an offline judgement can afford reasoning time but not a Pro per-token price). |

## Tests

- `uv run pytest tests/test_tools_prompt.py tests/test_real_model_findings.py tests/test_scenarios_provider.py -q` -> 11/11.
  Both new assertions were seen failing first: `assert 'existing appointment' in p` failed against
  the old prompt, and `no_booking_band_2_or_3(clarify)` returned
  `{'pass': False, 'reason': "band=1 outcomes=[] text='Which service are you interested in?'"}`
  before the grader change.
- `uv run pytest -q` (full runtime suite) -> 596 passed, 1 skipped.
- `uv run ruff check spatalk tests scenarios` -> All checks passed.
- promptfoo, one run, results in `docs/reports/promptfoo-run-2026-09-02-B.md`: **11 passed, 1 failed,
  18 errors** of 30, 1h 33m 45s. The judge fix is confirmed (case 1's rubric ran on
  `google:gemini-2.5-flash` and returned a real judgement; no 404s). The concurrency fix removed
  every parallelism 429. The run was then stopped by a limit no config setting reaches: the free
  tier allows **20 requests per day per model**
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: '20'`), and run A had already
  spent the day's allowance. Cases 14, 16 and 20 (QA-A1, QA-A3, QA-A7) are exactly the three the
  prompt and grader fixes target, and all three errored on that quota, so **neither behaviour fix
  was graded live**. Both are covered deterministically by the tests above. The single FAIL (case
  28) is a host-side crash of the assertion interpreter (`0xC0000142`), not an assertion result;
  the turn itself is a correct band-3 escalation and is quoted in full in the run report.

## Deviations

- The task named `tests/test_qa_gate_a.py` **or** a new `tests/test_real_model_findings.py` for
  the scenario test. The new file was chosen so QA gate A stays the record of the QA agent's own
  gate and the real-model regressions have one obvious home.
- The judge provider is set both per assertion and once in `defaultTest.options.provider`. The
  task asked only for the per-assertion setting; the default is belt and braces so a rubric added
  later without a `provider:` key does not silently fall back to Pro.
- Report filename is `runtime-fix-real-model-findings.md`, matching the existing
  `runtime-fix-*.md` fix reports, rather than `ops-E<N>.md`: this is not an operations-plan task.
- The quota fix in the task (`maxConcurrency 1`, `delay 1200`) addresses a per-minute limit. The
  run proved the binding limit is per **day** (20 requests per model), so the suite still cannot be
  fully graded on this key. The config change is kept because it is correct and necessary, but it
  is not sufficient; evidence and the three options are in the run report. No second run was made.

## Notes for neighbours

- `spatalk/settings.py` does not exist as an E4 file yet; when E4 is built, `judge_model` defaults
  to `"gemini-2.5-flash"` and the judge's `ThinkingConfig` must use `thinking_budget=-1`. The
  conversational `GeminiClient` keeps `thinking_budget=0` for latency: do not change it.
- `scenarios/asserts.py` now exports `is_clarifying_question`; reuse it rather than re-deriving
  "asked instead of acted" in a new grader.
