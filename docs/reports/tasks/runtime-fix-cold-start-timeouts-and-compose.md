# runtime QA gate A fix: cold-start-timeouts-and-compose

Status: done with deviations
Commit: PENDING
Tests: `uv run pytest -q tests/test_voice_processors.py tests/test_deploy_assets.py` -> 12/12;
full suite `uv run pytest -q` -> PENDING
Interfaces produced: none (no product code changed)

## What this fixes

Two minor findings from `docs/reports/qa-gate-A.md`:

1. `runtime/tests/test_voice_processors.py` (4 tests) — pipecat's `run_test` defaults to
   `start_timeout=1.0`, which a cold first run on this machine exceeds. Verified against the
   installed package:

   ```
   uv run python -c "import inspect; from pipecat.tests.utils import run_test; print(inspect.signature(run_test))"
   -> (..., start_timeout: float = 1.0) -> ...
   ```

   All four calls now pass `start_timeout=10.0`, matching the QA gate A test's own call
   (`tests/test_qa_gate_a.py:133`).

2. `runtime/docker-compose.yml` — `app` and `caddy` declared `env_file: .env`, so on a clean
   checkout `docker compose config` and `docker compose ps` failed before anyone had copied
   `.env.example`. Both now use the optional long form:

   ```yaml
   env_file:
     - path: .env
       required: false
   ```

## Tests: failing before, passing after

- **New** `tests/test_voice_processors.py::test_every_run_test_call_overrides_the_cold_start_timeout`
  — asserts pipecat's default is still `1.0`, then parses this file's own AST and requires every
  `run_test(...)` call to pass `start_timeout >= 10.0`. A source-level guard is the only
  deterministic form this check can take: the flake it prevents is a wall-clock race on a cold
  interpreter, not a reproducible assertion.
  Seen failing before the fix:
  `AssertionError: run_test call on line 53 does not pass start_timeout`.

- **Tightened** `tests/test_deploy_assets.py::test_compose_has_db_app_and_caddy_wired_together`
  — `app["env_file"]` and `caddy["env_file"]` must now equal
  `[{"path": ".env", "required": False}]` instead of the bare string `".env"`. Strictly
  stronger than the assertion it replaces; nothing was removed.
  Seen failing before the fix:
  `AssertionError: assert '.env' == [{'path': '.env', 'required': False}]`.

## Verification run

| Check | Result |
|---|---|
| `ls .env` | not present (clean checkout state) |
| `docker compose config >/dev/null` before the fix | exit 1, `env file ...\runtime\.env not found` |
| `docker compose config >/dev/null` after the fix | exit 0 |
| `docker compose up -d db` after the fix, still no `.env` | exit 0, `runtime-db-1 Running` |
| `uv run pytest -q -p no:cacheprovider tests/test_voice_processors.py` x3 | 6 passed, 6 passed, 6 passed |
| same after `rm -rf` of every `__pycache__` under `runtime/` and `runtime/.venv` | 6 passed in 1.84 s |
| `uv run ruff check spatalk tests scenarios` | All checks passed |

## Deviations

- **Touched `runtime/tests/test_deploy_assets.py`, which the task's Files block does not list.**
  That file already pinned `app["env_file"] == ".env"` and `caddy["env_file"] == ".env"`
  (lines 50 and 59), so the compose change could not land without it. The assertions were
  tightened to the optional long form, not relaxed.
  Evidence: `uv run pytest -q tests/test_deploy_assets.py` before the compose edit ->
  `1 failed, 5 passed`, `assert '.env' == [{'path': '.env', 'required': False}]`.

- **`runtime/tests/test_voice_processors.py` was committed by a concurrent agent, not by me.**
  While this task was in flight, the `fix: guard-path-ledger-failure` agent was editing the
  same file (adding `test_guard_block_with_a_dead_ledger_speaks_the_refusal` and a `ledger=`
  parameter on `_session`). Its commit `48664fd` swept up my four `start_timeout=10.0`
  additions and the new guard test. The content is correct and present in HEAD
  (`git show HEAD:runtime/tests/test_voice_processors.py | grep -c start_timeout` -> 11), but
  this task's own commit therefore carries only `docker-compose.yml`,
  `tests/test_deploy_assets.py` and this report.

- **The AST guard asserts `len(calls) >= 4`, not `== 4`.** It was written as `== 4` and
  relaxed the moment the concurrent agent added a fifth `run_test` call, so that the guard
  constrains what it is about (every call overrides the timeout) rather than how many tests
  the neighbour is allowed to add.

## Notes for neighbours

- `runtime/tests/test_voice_processors.py` and `runtime/tests/test_deploy_assets.py` were both
  edited by more than one agent in the same window. Re-read either file before editing; do not
  assume the version you last saw.
- Any new `run_test(...)` call added to `tests/test_voice_processors.py` must pass
  `start_timeout=10.0` or `test_every_run_test_call_overrides_the_cold_start_timeout` fails.
  This is deliberate: the default 1 s is the documented cold-start flake.
- `docker compose` now tolerates a missing `.env`. Deployment still requires a real one —
  `docs/runbooks/deploy.md` is unchanged and `.env.example` is still the source of the
  variable list. `required: false` needs Compose spec support (Docker Compose v2.24+);
  verified working on the Docker Desktop in this environment.
