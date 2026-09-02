# runtime QA gate A fix: guard-path-ledger-failure

Status: done

Commit: 48664fd

Finding fixed: QA gate A, minor — `runtime/spatalk/brain/driver.py:246` and
`runtime/spatalk/voice/processors.py:93` called `caps.capture(...)` on the guard-block path
without the `try/except` that `dispatch_tool` has. With the ledger down, a blocked completion
claim raised out of `Brain.turn` (and out of `OutputGuardProcessor._emit` as an `ErrorFrame`)
instead of degrading, so the caller got silence where they should get the clinic's number.

## What changed

- `spatalk/brain/driver.py`, `Brain.turn` guard block: the `capture` call and the
  `cannot_complete` rendering are inside a `try`. On any exception the outcome becomes
  `Refused(reason="unavailable")` and the spoken part is `render(out, cfg, now, channel=ref.channel)`,
  which renders `refuse_unavailable` ("I'm having trouble saving that right now, so please don't
  count on me for it. Please call the clinic directly at {phone}.") — it claims nothing. The
  failure is logged with `logger.exception`. On success the wording is unchanged
  (`cannot_complete`), as is `guard_blocked`, the band bump and the outcome list.
- `spatalk/voice/processors.py`, `OutputGuardProcessor._emit`: same shape. The dropping flag,
  the `guard_blocks` counter, the band bump and the "everything after a blocked sentence is
  dropped" behaviour are untouched; only the text of the single replacement frame changes when
  the ledger raises.

Both use `except Exception ... # noqa: BLE001`, matching the existing precedent in
`dispatch_tool` and in `RulesGateProcessor` (which already degraded this way).

## Tests

- `tests/test_driver.py::test_guard_block_with_a_dead_ledger_refuses_and_claims_nothing` —
  `FakeLLM` returns "Done, I've booked you for Thursday at 2.", the ledger is a `MemoryLedger`
  subclass whose `create_item` raises. Asserts `guard_blocked`, one `refused`/`unavailable`
  outcome, `905-703-7546` in the reply, and none of "sent", "passed it", "confirm with you",
  "booked".
- `tests/test_voice_processors.py::test_guard_block_with_a_dead_ledger_speaks_the_refusal` —
  the same ledger through `OutputGuardProcessor` under pipecat's `run_test`; one `LLMTextFrame`
  carrying the clinic phone, none of the same four claims, `guard_blocks == 1`.

Seen failing before the fix (product code untouched at that point):

```
FAILED tests/test_driver.py::test_guard_block_with_a_dead_ledger_refuses_and_claims_nothing
        RuntimeError: database is down
FAILED tests/test_voice_processors.py::test_guard_block_with_a_dead_ledger_speaks_the_refusal
        received DOWN frames = [LLMFullResponseStartFrame, LLMFullResponseEndFrame, ]
        expected DOWN frames = [LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, ]
        output_guard exception: Error processing frame: database is down
```

After: `uv run pytest -q tests/test_driver.py tests/test_voice_processors.py` -> 13 passed, 1 skipped.
Full suite: `uv run pytest -q` -> 187 passed, 1 skipped. `uv run ruff check spatalk tests scenarios` -> All checks passed.

## Deviations

- `_world` in `tests/test_driver.py` and `_session` in `tests/test_voice_processors.py` grew an
  optional `ledger=None` parameter so the failing ledger can be injected. Defaults and every
  existing call site are unchanged; no assertion was touched.
- `tests/test_voice_processors.py::test_every_run_test_call_overrides_the_cold_start_timeout`
  (added in the parallel flake fix, uncommitted in the tree when this task started) pins the
  number of `run_test` calls in the file. Its expected count went 4 -> 5 because this task adds a
  fifth call; that call passes `start_timeout=10.0`, so the guard's actual invariant ("no bare
  `run_test`") still holds and was not weakened.
- No `Alembic` migration: no model changed.

## Notes for neighbours

- `tests/test_voice_processors.py` is shared with the `run_test` start_timeout flake fix. This
  commit's pathspec includes that file, so the flake fix's edits to it (start_timeout on the four
  existing calls plus the meta test) rode along in this commit. Nothing else of that task was
  committed here — `runtime/spatalk/brain/rules.py`, `runtime/docker-compose.yml`,
  `runtime/scenarios/promptfooconfig.yaml`, `runtime/tests/test_qa_gate_a.py` and
  `runtime/tests/test_deploy_assets.py` were left modified and uncommitted for their owners.
- Anyone adding a `run_test` call to `tests/test_voice_processors.py` must bump the expected
  count in that meta test and pass `start_timeout>=10.0`.
- The guard-block path can now produce a `Refused(reason="unavailable")` outcome in
  `TurnResult.outcomes` with `guard_blocked=True`. Callers that assumed a guard block always
  yields a `Captured` should read the outcome kind.
