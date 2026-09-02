# operations plan Task E6: Second LLM vendor, model-list check and the swap drill

Status: done with deviations

Commit: 22eedd7

Tests: `uv run --no-sync pytest -q tests/test_ops_model_check.py` -> **35/35**;
`uv run --no-sync pytest -q tests/test_driver.py` -> 6 passed, 2 skipped (both live vendor
smoke tests, `skipif` on `GOOGLE_API_KEY` / `OPENAI_API_KEY`);
full suite `TEST_DATABASE_URL=…/spatalk_test_e6 uv run --no-sync pytest -q` ->
**892 passed, 1 failed, 2 skipped** (895). The one failure is
`tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table`, the
`rates.json` drift that E4, E5, E7 and E9 all reported and routed to the rates owner:
neither file is touched here (`git status --porcelain runtime/spatalk/rates.json
docs/research/rates.json` -> empty) and their last commits are different pieces of work
(`7267613` versus `4fbee36`).
`uv run --no-sync ruff check spatalk tests scenarios` -> All checks passed.

Interfaces produced: `spatalk.brain.driver.{OPENAI_PREFIX, GOOGLE, OPENAI, provider_for,
model_name, parse_chat_completion, OpenAIClient}`;
`spatalk.voice.pipeline.{LLM_TEMPERATURE, make_llm}` (openai branch);
`spatalk.ops.model_check.{ModelInfo, CheckResult, KEY_ENV, KEY_SETTING,
DEPRECATION_MARKERS, OK, FINDING, UNCHECKED, normalise, is_deprecated, evaluate,
list_models, check_configured_model, main}`; `spatalk.settings.Settings.openai_api_key`;
`.github/workflows/model-check.yml`; `docs/runbooks/model-swap.md`.

## What is in place

**One environment variable names the vendor as well as the model.** `LLM_MODEL` is a bare
name for Google and `openai:<model>` for OpenAI. `provider_for` and `model_name` are the
only two places that know the rule, and all four call sites read it through them:
`voice.pipeline.make_llm` (the Pipecat service for a call), `text.service.make_text_llm`
(SMS, web chat, Instagram, Messenger), `scenarios/provider.py` (the promptfoo suite) and
`ops.model_check`. That is the point of putting the parsing in one place: a swap that moved
voice but left text on the retired model would be worse than no swap at all.

**`OpenAIClient` is the same protocol as `GeminiClient`**, so nothing above the client knows
which vendor answered — the rules gate, the tool dispatch and the output guard are untouched
and structural honesty is unaffected by the swap. It speaks **Chat Completions**, not the
Responses API (the plan says to record which): that is the API Pipecat's own
`OpenAILLMService` uses for the voice half of the same swap
(`pipecat/services/openai/base_llm.py` calls `chat.completions.create`), so one drill puts
both channels on one API rather than two, and the recorded fixture in the tests is the shape
both halves see.

**A tool call with unparseable arguments still runs, with no arguments.** That is the shape
`GeminiClient` already produces when the model sends none, and `dispatch_tool` answers
honestly about the missing fields (`Refused(out_of_scope)`), so the caller hears something
true. Dropping the call instead would leave a voice caller with silence.

**The weekly check has three answers, not two.** `model_check` asks the provider for its
model list and exits `0` (listed, no retirement notice), `1` (absent, or the provider's own
description carries a deprecation marker) or `2` (**no key, a provider error, or an empty
listing — the question could not be asked**). The third code exists because a weekly job
that goes green when it reached nobody is worse than no job: it also removes the suspicion
that would have made someone look. `model-check.yml` runs Mondays at 06:40 UTC, checks the
conversational model, the nightly audit's judge model and the OpenAI fallback, and every
step that runs the check is guarded on a key with a `::notice` when there is none.

**Deprecation is read from the provider's own words.** Google puts a retirement notice in
the model's `description`; OpenAI's listing has no such field, so for OpenAI the check is
presence and a retirement shows up as an absence. `DEPRECATION_MARKERS` is the list, and
`normalise` makes Google's `models/gemini-2.5-flash` comparable with the configured
`gemini-2.5-flash`.

**The runbook is the half a machine cannot do.** `docs/runbooks/model-swap.md` is the drill:
key, suite, promptfoo scenarios, twenty real calls, then a comparison of turn p95 (E5's
`BUDGETS_MS`) and cost (E9's report) with the decision written down; and the rollback, which
is one line in `.env` and a restart because the previous vendor's key is deliberately left
in place. It records that on this machine promptfoo must be invoked as
`npx --yes -p node@24 -p promptfoo@latest promptfoo eval …`, because the installed Node
22.14 is rejected by promptfoo and the short form in `CLAUDE.md` fails here.

## Deviations

1. **`spatalk/text/service.py` is not in E6's Files list.** `make_text_llm` built a
   `GeminiClient` unconditionally, so `LLM_MODEL=openai:…` would have swapped voice and left
   every text channel on Google. The plan's Behaviour says "`LLM_MODEL` accepts
   `gemini-2.5-flash` (Google) or `openai:gpt-4.1-nano` (OpenAI)" without limiting that to
   voice, and a half-swap is exactly the failure spec §10.3 is about. The change is six
   lines and the signature is unchanged. Pinned by
   `test_make_text_llm_follows_the_same_prefix`.
2. **`scenarios/provider.py` is not in E6's Files list either.** Same reason, one step
   worse: step 3 of the swap runbook runs the adversarial scenarios against the candidate,
   and with the old `_make_llm` it would have graded the incumbent and reported the swap
   safe. Pinned by `test_the_promptfoo_provider_follows_the_same_prefix`.
3. **`spatalk/settings.py` gained `openai_api_key`.** Not in the Files list, but
   `docs/reference/api-surface.md` lists `OPENAI_API_KEY` under E6 and reference wins over
   the plan. `runtime/.env.example` gained the key with an empty value and the comment on
   its own line, so it does not repeat QA gate B's inline-comment bug.
4. **`make_llm` raises when `openai:` is selected without `OPENAI_API_KEY`.** The plan does
   not ask for it. The alternative is a service that constructs cleanly and 401s on the
   first turn of a real call, which is the worst possible moment to discover it. The Google
   branch is left as it was: changing it is not this task's behaviour to change, and it is
   the asymmetry a later task may want to close.
5. **The plan's Files list has the tests split as
   `tests/test_ops_model_check.py` plus "`tests/test_driver.py` (+OpenAI client test,
   skipped without key)".** `test_driver.py` gained exactly the live test
   (`test_openai_client_calls_a_tool`, `skipif` on `OPENAI_API_KEY`, the twin of the Gemini
   one). Every offline E6 test — parsing, request shape, `make_llm` selection, the model
   check, the workflow and the runbook — is in `test_ops_model_check.py`.
6. **The pipecat service's model and temperature are asserted through `_settings`.**
   Pipecat 1.8 exposes no public accessor for a configured-but-not-yet-run service:
   `get_full_model_name()` returns `''` before the first request and `GoogleLLMService` does
   not have the method at all. Evidence:
   `uv run python -c "…; print(repr(llm.get_full_model_name()))"` -> `''`, and
   `AttributeError: 'GoogleLLMService' object has no attribute 'get_full_model_name'`.
   `_settings.model` / `_settings.temperature` exist on both services and are what
   `Settings(...)` populates.
7. **`sentry-sdk` was not added to `pyproject.toml`** even though E7's report offered E6 the
   one line. It is out of this task's Behaviour, E7 already degrades to a warning when the
   package is missing, and it resolves in this environment as a transitive dependency
   anyway. `pyproject.toml` gained only what E6 names: `openai` in the `pipecat-ai` extras
   and `openai>=1.99` as a direct dependency (both already resolvable here, so `uv.lock`
   changed by three lines and downloaded nothing).

## Notes for neighbours

- **A swap is one variable and it moves everything at once.** Anything added later that
  builds an LLM client must go through `provider_for`/`model_name` rather than reading
  `LLM_MODEL` itself, or it becomes the channel left behind on the retired model.
- **E5 (latency)** already maps `OpenAILLMService` to the `llm` stage in
  `STAGE_BY_SERVICE`, so the OpenAI branch reports into the same budget with no change
  there, and the `llm` suggested fix now names a runbook that exists.
- **E4 (nightly audit)**: the judge is still Google-only (`make_judge` reads
  `judge_model` and `google_api_key`). It is a separate model on a separate variable on
  purpose; `model-check.yml` checks it as its own step. If the judge should follow the
  `openai:` prefix too, that is a four-line change in `ops/nightly_audit.make_judge`.
- **Whoever runs the suite next**: `spatalk_test_e6` is this task's private database, for
  the reason every earlier ops report gives — `tests/conftest.py` drops and recreates the
  schema per test, so two agents sharing `spatalk_test` corrupt each other's runs.
- **`uv run` needed `--no-sync` on this machine** while another agent held
  `.venv/Scripts/spatalk.exe` open: `error: failed to remove file …spatalk.exe: The process
  cannot access the file because it is being used by another process (os error 32)`. The
  package is installed editable, so `--no-sync` runs the current source.

## Verification run

| Check | Result |
|---|---|
| `uv run --no-sync pytest -q tests/test_ops_model_check.py` (before any product code existed) | **33 failed, 1 passed** — `ImportError: cannot import name 'model_name' from 'spatalk.brain.driver'`, then `ModuleNotFoundError: spatalk.ops.model_check`, then `FileNotFoundError: docs/runbooks/model-swap.md`. The one pass was the existing Google branch of `make_llm`. |
| `uv run --no-sync pytest -q tests/test_ops_model_check.py` (after) | **35 passed** in 2.1 s |
| Mutation check: deprecation test removed from `evaluate`; an empty listing made `ok=True`; `make_llm`'s missing-key guard removed; `parse_chat_completion`'s blank-content-to-`None` removed | **5 failed, 30 passed** — each of the four properties is pinned by a test that fails without it. Files restored byte-for-byte and re-run: 35 passed. |
| `python -m spatalk.ops.model_check --model openai:gpt-4.1-nano` with no key | `[NOT CHECKED] openai: OPENAI_API_KEY is not set, so openai was never asked about gpt-4.1-nano; nothing was checked`, exit **2** — not 0 |
| `uv run --no-sync ruff check spatalk tests scenarios` | All checks passed |
| `.env.example` parsed with python-dotenv | 55 keys, `OPENAI_API_KEY` present and empty, 0 poisoned by an inline comment |
| Live vendor calls | **none**. Both smoke tests are `skipif` on their key and both skipped; no paid API was called in this task. |
