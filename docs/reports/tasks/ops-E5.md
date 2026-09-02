# operations plan Task E5: Latency budgets per stage and the SLO check

Status: done with deviations
Commit: 63d86a6
Tests: `uv run pytest -q tests/test_ops_latency.py` -> 34/34;
full suite `uv run pytest -q` -> **857 passed, 1 failed, 1 skipped** (859 total). The one
failure is `tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table`,
which is not this task's and is red at `HEAD` independently of anything here — proof below.
The skip is `test_driver.py::test_gemini_client_calls_a_tool`, `skipif` on `GOOGLE_API_KEY`.
`uv run ruff check spatalk tests scenarios` -> All checks passed (also clean with `scripts`
added, which the pinned command does not cover).

Interfaces produced: `spatalk.ops.latency.BUDGETS_MS`, `…STAGES`, `…SUGGESTED_FIX`,
`…RUN_KIND = "ops.latency_report"`, `…percentile(values, q)`, `…p50(values)`, `…p95(values)`,
`…session_stage_ms(session) -> dict[str, int]`, `…over_budget(turn_p95, stage_p95) -> list[str]`,
`…daily_latency(ctx, day) -> list[dict]`, `…Alert` (dataclass with `.key`),
`…slo_alerts(ctx, day) -> list[Alert]`, `…check_slo(ctx, day) -> list[Alert]`,
`…latency_table(rows) -> str`, `…run_latency_report(ctx, day=None) -> dict`;
`spatalk.voice.observers.stage_for_processor(name) -> str | None`,
`spatalk.voice.observers.STAGE_BY_SERVICE`; `spatalk.voice.session.VoiceSession.stage_ttfb_ms`;
`spatalk.conversations.end_conversation(..., stage_ms=None)`;
`spatalk.ledger.scheduler.ensure_daily_latency_scheduled(ctx) -> bool`,
`spatalk.ledger.scheduler.NIGHTLY_LATENCY_UTC_HOUR = 5`;
`runtime/scripts/latency_report.py` (`main(argv=None) -> int`, `collect(days, end)`);
`runtime/scenarios/voice/{price_question,clinical_escalation}.yaml`,
`runtime/scenarios/voice/eval_bot.py` (`bot(runner_args)`, `build_session`, `transport_params`),
`runtime/scenarios/voice/README.md`; `.github/workflows/nightly-voice-evals.yml`.

## What is in place

**The measurement, taken by the call itself.** `UsageObserver` now also reads
`TTFBMetricsData` out of every `MetricsFrame` and files it under the stage that produced it
(`session.stage_ttfb_ms`, ms). `voice/pipeline._finalize` writes that call's per-stage p95
into `conversations.stage_ms` through `end_conversation(..., stage_ms=…)`. Nothing
recomputes it later, which matters because retention (Task E3) deletes the transcript at 30
days while the conversation stub lives 400.

**The stage mapping is by service, never by position.** `STAGE_BY_SERVICE` names the six
services `make_stt`, `make_llm` and `make_tts` can return (Soniox, Deepgram Flux, Google,
OpenAI, Inworld, Deepgram Aura-2), and an unknown vendor still lands correctly through a
marker fallback that checks `STT` **before** `TTS` — `"STTService"` contains the substring
`"TTS"`, and a TTS-first scan silently swaps the two budgets. That is pinned by
`test_an_stt_service_is_never_read_as_a_tts_one`.

**The budgets.** `BUDGETS_MS = {"stt": 300, "llm": 450, "tts": 200, "turn": 800}`, the
brief's S7 number and the split under it. They overlap on purpose (300 + 450 + 200 > 800):
the LLM starts on a partial transcript and the TTS on the first tokens.

**The daily report.** `daily_latency(ctx, day)` returns one row per tenant that had a
measured call in its own local day (`day_window` from Task E4, so a clinic's Monday is the
clinic's Monday, CLAUDE.md non-negotiable 8): `{day, tenant_id, conversations, turns, p50,
p95, stage_p95: {stt, llm, tts}, over_budget: [stage]}`. A tenant with no calls produces no
row — a p95 of nothing is not zero, and a zero would read as a perfect day.

**The SLO check.** `slo_alerts` derives one `Alert` per breached budget; `check_slo` raises
each through `alerts.notify` (Task E7) under the key `slo:<stage>:<tenant>:<day>`, so the
six-hour dedup applies and it returns only what actually went out. Every alert names the
stage, the measured p95, the budget and one concrete swap (`SUGGESTED_FIX`): Flux for STT,
Flash-Lite or the `openai:` alternative for the LLM, the other vendor for TTS. A turn
breach with every stage inside budget says so explicitly rather than ending in "investigate".

**The scheduled run.** `run_latency_report(ctx, day=None)` reports yesterday, alerts, and
writes an `ops_runs` row whether or not it found anything (Global Constraints); it is
registered as the `ops.latency_report` job handler, and
`scheduler.ensure_daily_latency_scheduled` queues it once per UTC day from 05:00, marked by
the queued job's own `run_at` exactly as retention and the nightly audit are.

**The founder's view.** `scripts/latency_report.py --days 7` prints the table
(`latency_table`) for the last N local days, the budgets, and one line per day over budget;
it exits 1 when anything was over budget, so it can be used as a check as well as a look.

**The nightly voice evals.** `scenarios/voice/*.yaml` are Pipecat eval scenarios in audio
mode: synthesized caller audio (local Kokoro), the bot's real speech transcribed locally
(Moonshine), and `within_ms: 800` — `BUDGETS_MS["turn"]`, which a test pins to the constant
— on the reply. No judge model is used at all: content is asserted as a fixed substring of
the model's own text or of the tenant's fixed script, both decidable without a model, so a
run costs no judged token. `nightly-voice-evals.yml` runs them at 07:23 UTC and on demand,
guarded on all three provider keys being present; without them it prints a `::notice`
saying no scenario ran and every other step is skipped. A green tick over nothing is the
failure being avoided.

## Deviations

1. **`scenarios/voice/eval_bot.py` is new and is not in the task's Files list.** The plan
   says the workflow runs `pipecat eval run scenarios/voice/*.yaml`; the harness drives a
   bot over its own RTVI transport (`pipecat/evals/harness.py`, `runner/run.py::_run_eval`),
   and the production entry point is a Telnyx media stream inside FastAPI, which the harness
   cannot speak to. Without a bot on the eval transport the workflow would reference nothing.
   The bot builds the *same* pipeline — a test extracts the `Pipeline([...])` element list
   from both modules by AST and asserts they are identical apart from the RTVI processor —
   on memory ports, so a scenario needs no database and files nothing into a real ledger.
   Evidence: `.venv/Lib/site-packages/pipecat/runner/run.py:1516 _run_eval`, and
   `pipecat/runner/utils.py:716` requires `transport_params["eval"]` to be an
   `EvalTransportParams`.
2. **`spatalk/conversations.py` is not in the task's Files list.** `end_conversation` gained
   an optional `stage_ms=None` keyword; the alternative was to duplicate the update
   statement inside the pipeline. It is the only caller (`grep -rn "end_conversation("
   spatalk/` -> `spatalk/voice/pipeline.py:243`), so no other task's call site changes.
3. **`spatalk/ledger/scheduler.py` is not in E5's Files list either.** `docs/reference/`
   wins over the plan on conflict, and `docs/reference/flows.md` §9 lists "Daily latency
   report; SLO breach alerts name the stage" among the nightly jobs of E3/E4/E5/E9. Added as
   a delimited block (`NIGHTLY_LATENCY_UTC_HOUR = 5`, `ensure_daily_latency_scheduled`) in
   the same shape as the two above it, plus one call in the loop. It shares the hour with
   the monthly cost report, which only fires on the first of a month.
4. **`Alert` is a new dataclass in `spatalk/ops/latency.py`, not `alerts.AlertCondition`.**
   The plan's interface says `check_slo(ctx, day) -> list[Alert]` and an SLO alert carries
   more than a condition does (tenant, stage, measured p95, budget). It mirrors E7's split:
   `slo_alerts` computes, `check_slo` sends. `Alert.key` is the dedup identity.
5. **The plan's report keys are all present; `day` and `conversations` are added.** The row
   is `{day, tenant_id, conversations, turns, p50, p95, stage_p95, over_budget}` — the extra
   two are what the printed table needs to be readable across a week.
6. **`pipecat eval` needs the `cli` extra, which is not a runtime dependency.** The workflow
   installs `pipecat-ai[cli,kokoro,whisper]` in its own step rather than adding an
   always-installed extra to `pyproject.toml`. Evidence: `uv run pipecat --help` ->
   "The Pipecat CLI needs its optional dependencies (the `cli` extra), which aren't installed."
7. **No migration.** `conversations.stage_ms` already exists: Task E3 added the column in
   `alembic/versions/0006_ops_retention.py` because retention nulls it. Nothing else in this
   task touches the schema.

## Pre-existing failure, not this task's

`tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table` compares
`runtime/spatalk/rates.json` with `docs/research/rates.json`. Both files are committed and
neither is touched here (`git status --porcelain runtime/spatalk/rates.json
docs/research/rates.json` -> empty), and the two disagree at `HEAD` itself:

```
git show HEAD:docs/research/rates.json vs git show HEAD:runtime/spatalk/rates.json
equal at HEAD: False   differs: tts, voice_stacks, reference_bundles_usd_per_min
```

The E4 report records the same failure. It belongs to the cost-model work (E9), not here.

## Notes for neighbours

- **E6 (second LLM vendor):** `STAGE_BY_SERVICE` already maps `OpenAILLMService` to `llm`,
  so `make_llm`'s `openai:` branch reports into the same budget with no change here. The
  `llm` suggested fix names the swap drill runbook E6 writes (`docs/runbooks/model-swap.md`).
- **E10 (live transfer):** a transfer adds no stage; if it grows a processor that reports
  TTFB, give it a name that matches none of the three markers or it will be budgeted.
- **Portal:** nothing is exposed over `/internal` for latency yet. The data is
  `conversations.stage_ms` plus `ops_runs` rows of kind `ops.latency_report`, whose
  `summary` is exactly the report dict, if a health page wants it.
- **Anyone touching `voice/pipeline._finalize`:** `stage_ms` is written there and nowhere
  else. A call that recorded no stage readings stores `NULL`, not `{}`.
- The eval bot reads `EVAL_TENANT_BUNDLE` (a path, default `tenants/skincentrix`). It is a
  scenario-only override, not a runtime setting, so it is not in
  `docs/reference/api-surface.md`'s environment table.
