# Fix: the packaged rates table had drifted from the researched table

Status: done
Commit: the single commit `fix: sync the packaged rates table with the researched table`
(this report is committed in it, so it cannot quote its own hash; resolve it with
`git log -1 --format=%H -- runtime/spatalk/rates.json`)
Tests: `cd runtime && uv run pytest -q tests/test_internal_api.py -k "rates or estimate"` -> 5/5;
full suite `cd runtime && uv run pytest -q` -> 943 passed, 2 skipped, 0 failed;
`uv run ruff check spatalk tests scenarios` -> clean.
Interfaces produced: none (data file only; `spatalk.rates.{RATES_PATH, load_rates, recommended_stack, estimate_cad}` are unchanged)

## The finding

QA gate C, blocking finding 1 (`docs/reports/qa-gate-C.md`). `runtime/spatalk/rates.json` — the
copy `GET /internal/rates` serves the portal and `estimate_cad` prices from — had not been
re-synced since `7267613`, while `docs/research/rates.json` moved on three times:

| commit | added to the researched table |
| --- | --- |
| `12fc7b8` | `/tts/soniox_tts` and the `B4 Soniox only (STT + TTS), single vendor` voice stack |
| `a0939cc` | `/reference_bundles_usd_per_min/telnyx_voice_ai_agents_all_in` |
| `4fbee36` | that bundle's `add_ons_usd_per_min` and the calculator figures |

`tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table` is the drift
guard and it was failing on a clean checkout, so `.github/workflows/ci.yml`'s runtime job
(`uv run pytest -q`, unfiltered) was red on every push. Reports E4, E5, E6, E7 and E9 each
recorded it as another task's and routed it onward; nobody owned it.

## The change

One file: `runtime/spatalk/rates.json`, replaced with a byte-for-byte copy of
`docs/research/rates.json` — exactly what `make sync-rates` (in `runtime/Makefile`, from
portal Task C3) does. No code, no test, no schema touched.

Before copying I checked the three new entries are wanted rather than in-progress notes:

- `python docs/research/costmodel.py docs/research/rates.json` exits 0 on the researched table
  (also asserted by `tests/test_qa_gate_c.py::test_the_cost_model_runs_and_exits_zero_on_the_researched_rates`).
- The additions are purely additive: `diff` of the two files sorted and normalised shows only
  `>` lines, no removals and no changed prices.
- `recommended: true` still sits on exactly one voice stack (`B  RECOMMENDED (Telnyx + Soniox +
  Inworld Flash + Gemini 2.5 Flash)`) and one text stack. The new `B4` stack and the Telnyx
  reference bundle carry no `recommended` flag, so `recommended_stack()` picks the same stack it
  picked before and `estimate_cad` returns the same numbers —
  `test_estimate_cad_prices_the_recommended_stack` and
  `test_estimate_cad_accepts_call_minutes_instead_of_seconds` pass unchanged.
- Nothing else in the repository embeds a copy of the table: `grep -rl "voice_stacks\|usd_to_cad"
  portal edge docs/contracts` (excluding `node_modules`) returns nothing, so the portal and the
  OpenAPI contract are unaffected.

Verification that the two files are now identical: `cmp docs/research/rates.json
runtime/spatalk/rates.json` -> silent.

## Why not a structural fix

A generator or a symlink would remove the possibility of drift, but the guard test already
exists and the smallest correct change for a blocking gate finding is to run the sync the
Makefile documents. The recurrence risk is that a `docs(research):` commit lands without
`make sync-rates`; the test catches it on the next push, which is the design.

Deviations:
- The report's `Commit:` line names the commit by subject instead of by hash: the
  report ships inside that commit, so any hash written into it is invalidated by the amend
  that writes it.
- Report filename is `fix-rates-table-drift.md` rather than the `ops-E<N>.md` in the standing
  environment note: this is a QA-gate fix, not an ops plan task, and the task instruction asked
  for `docs/reports/tasks/fix-<slug>.md`.
- `make` is not on PATH on this Windows machine, so the Makefile recipe was run directly
  (`cp ../docs/research/rates.json spatalk/rates.json`). The Makefile itself is unchanged.

Notes for neighbours:
- After editing `docs/research/rates.json`, run `make sync-rates` from `runtime/` in the same
  commit. `/internal/rates` serves the packaged copy, so an unsynced edit means the portal quotes
  numbers the research does not agree with.
- Gate C's blocking finding is cleared; the remaining gate items (image size, etc.) are untouched.
