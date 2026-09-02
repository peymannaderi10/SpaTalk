# QA gate B fix: hermetic-settings-in-tests

Status: done with deviations
Commit: c4cd291

## The defect

`Settings` carries `SettingsConfigDict(env_file=".env")` (`runtime/spatalk/settings.py`), so
on a machine that has a populated `runtime/.env` the suite silently inherited it: every field
a test helper did not name came from the developer's environment rather than from the model
defaults. QA gate B, finding 1, measured **13 failed, 525 passed, 1 skipped** with this
machine's `.env` present against **538 passed, 1 skipped** with it moved aside, from three
separate inheritances (`TURNSTILE_SECRET_KEY`, `EDGE_SHARED_KEY`, `GOOGLE_API_KEY`).

The `TURNSTILE_SECRET_KEY` inheritance was the worst of the three: `chat_ws` only replaces the
verifier through `app.state.turnstile_verifier`, so with a non-empty secret in `.env` the
widget tests ran the real `verify_turnstile`, which `POST`s the tenant's live Turnstile secret
to `https://challenges.cloudflare.com/turnstile/v0/siteverify` during `pytest`.

Reproduced before the fix (this machine, `runtime/.env` present):

```
$ uv run pytest -q tests/test_widget.py tests/test_takeover.py tests/test_text_sms.py
13 failed, 43 passed in 47.49s
```

11 in `test_widget.py`, 1 in `test_takeover.py`, 1 in `test_text_sms.py` — exactly the set the
gate report names.

## The fix

Root cause first, then belt and braces.

1. **`runtime/spatalk/settings.py`** — a new module-level switch and a `Settings.__init__`
   that honours it:

   ```python
   NO_ENV_FILE_VAR = "SPATALK_NO_ENV_FILE"

   def env_file_disabled() -> bool: ...

   class Settings(BaseSettings):
       def __init__(self, **values: Any) -> None:
           if env_file_disabled():
               values.setdefault("_env_file", None)
           super().__init__(**values)
   ```

   With `SPATALK_NO_ENV_FILE=1` (or `true`/`yes`/`on`) in the environment, no `Settings()`
   reads the dotenv file at all: it sees only its defaults, explicit keyword arguments and
   real environment variables. The switch is read at **construction** time, not at import
   time, so it cannot be defeated by an unlucky import order — an `env_file=` computed in the
   class body would have been. An explicit `_env_file=` keyword always wins over the switch.
   Nothing changes for the running service, which sets no such variable.

2. **`runtime/tests/conftest.py`** — sets `os.environ["SPATALK_NO_ENV_FILE"] = "1"` at module
   import, before `spatalk` is imported anywhere and before any fixture runs, so the switch
   covers the whole session including collection-time settings objects.

3. **Every `Settings(...)` in `runtime/tests` now passes `_env_file=None`** — 29 call sites
   across 22 files (`grep -rn "Settings(" runtime/tests runtime/scenarios`; `scenarios/` has
   no `Settings(` call site, only `SocialSettings`, which is a plain pydantic model and reads
   no environment). This is redundant with the switch on purpose: a helper copied into a new
   file, or a settings object built by a tool that never loads `conftest.py`, is hermetic on
   its own.

4. **`runtime/spatalk/text/chat.py`** — `verify_turnstile` now short-circuits on an empty
   secret and returns `False` without constructing an HTTP client. An empty secret cannot
   verify anything, so refusing is the honest answer; the two callers that mean "do not
   challenge at all" (`chat_ws`, `chat_fallback`) already test the secret themselves before
   calling. The real call's 5 s timeout was already present (`httpx.AsyncClient(timeout=5.0)`);
   a new test now pins it so it cannot be dropped.

No test was weakened, skipped or deleted. The only test-body change anywhere is the added
`_env_file=None` argument; every assertion in the suite is untouched.

## Proof

`runtime/tests/test_settings_hermetic.py` (new, 7 tests) writes a **fully populated `.env`**
into a `tmp_path`, makes it the working directory, and clears the real process environment of
every key in it, so the file is the only possible source of a value:

- `test_the_dotenv_on_disk_is_the_only_possible_source_of_these_values` — the control. With
  the switch deleted, `Settings()` *does* pick the file up (`turnstile_secret_key ==
  "leaked-turnstile-secret-key"`). Without this the hermetic assertions would pass against an
  empty file and prove nothing.
- `test_the_switch_makes_settings_ignore_a_populated_dotenv` — under the switch, all 25 keys
  in that file land nowhere: each field equals its declared default and no value contains
  "leaked".
- `test_the_switch_leaves_every_field_a_helper_did_not_name_at_its_default` — the shape every
  test helper uses: `Settings(secret_key="s3cret")` gets `turnstile_secret_key == ""`,
  `edge_shared_key == ""`, `google_api_key == ""`.
- `test_env_file_none_ignores_the_dotenv_even_without_the_switch` — the belt-and-braces
  argument works on its own.
- `test_real_environment_variables_still_win_under_the_switch` — the switch turns off the
  *file*, not the environment, so Docker and CI still configure the service the documented way.
- `test_turnstile_verification_with_no_secret_never_touches_the_network` — records every
  attempt to construct an `httpx.AsyncClient` and asserts none was made. (`verify_turnstile`
  swallows every exception and refuses, so a stub that merely raises would have looked like a
  pass; the test records instead of raising.)
- `test_the_real_turnstile_call_is_bounded_by_a_five_second_timeout` — the real path still
  posts to `TURNSTILE_VERIFY_URL` with `timeout=5.0`.

Each was seen failing before it was trusted, by mutating the product code and restoring it in
the same command (`git diff` clean afterwards):

| Mutation | Result |
|---|---|
| `if env_file_disabled():` → `if False:` in `settings.py` | `test_the_switch_makes_settings_ignore_a_populated_dotenv` and `test_the_switch_leaves_every_field_a_helper_did_not_name_at_its_default` fail: `+ leaked-turnstile-secret-key` |
| `if not secret: return False` removed from `verify_turnstile` | `test_turnstile_verification_with_no_secret_never_touches_the_network` fails at the recorded attempt |

## The gate's own acceptance test: same result with and without a `.env`

Three full runs from `runtime/`, on the per-agent database
`spatalk_test_hermetic_settings_in_tests`. The real `runtime/.env` was copied to the scratchpad
first and byte-compared (`cmp`) back into place after each run; it was never committed, and the
dummy file never left the working directory.

| Run | `runtime/.env` | Result |
|---|---|---|
| A | a dummy file with a non-empty value for all 38 keys (`SMTP_PORT=2525` so it still parses) | **591 passed, 1 skipped** in 164.99 s |
| B | absent entirely | **591 passed, 1 skipped** in 162.84 s |
| C | this machine's real `.env`, restored | **591 passed, 1 skipped** in 155.11 s |

Identical. The 13 failures are gone and the suite no longer depends on what the machine holds.
(591 rather than 538 because gate B's own `test_qa_gate_b.py`, the concurrent
`fix: sms-optout-matching` commit and this task's 7 tests have all landed since the gate ran.)

Targeted run of the previously failing files, with the real `.env` present:

```
$ uv run pytest -q tests/test_widget.py tests/test_takeover.py tests/test_text_sms.py
102 passed in 45.32s
```

Lint:

```
$ uv run ruff check spatalk tests scenarios
All checks passed!
```

## Deviations

- **One of my lines was committed by the other engineer.** The concurrent
  `fix: sms-optout-matching` task (`a79c47b`) staged `runtime/tests/test_text_sms.py` while my
  one-line `_env_file=None` edit to its line 54 was in the working tree, so that line shipped
  in their commit rather than mine. Evidence:
  `git show a79c47b -- runtime/tests/test_text_sms.py | grep _env_file` →
  `+    settings = Settings(_env_file=None, secret_key="s3cret", **setting_overrides)`.
  The change is correct and present; only its authorship moved. No other file of mine was
  swept in (`git status --short` before committing listed every remaining file).
- **`spatalk/settings.py` and `spatalk/text/chat.py` are shared files.** Both additions are in
  clearly delimited blocks (`# --- hermetic settings (QA gate B, finding 1) ---`) and nothing
  existing was reordered or reformatted. `Settings.__init__` is appended after the last field
  declaration rather than placed at the top of the class, to keep the field list untouched.
- **The 5 s timeout the task asked for was already there.** `verify_turnstile` already used
  `httpx.AsyncClient(timeout=5.0)`; the change was the empty-secret short-circuit plus a test
  that pins the timeout. Evidence: the pre-change file at
  `runtime/spatalk/text/chat.py:80-92`.
- **`scenarios/` needed no change.** `grep -rn "Settings(" runtime/scenarios` matches only
  `SocialSettings(...)`, a plain `BaseModel` in `spatalk.tenants.schema` that reads no
  environment.

## Notes for neighbours

- **`SPATALK_NO_ENV_FILE=1` is now the way to make anything hermetic**, not just pytest. If a
  future job, CLI command or fixture builds settings outside `tests/conftest.py`, set that
  variable or pass `_env_file=None`. `spatalk.settings.NO_ENV_FILE_VAR` and
  `spatalk.settings.env_file_disabled()` are exported for that.
- **New test helpers must pass `_env_file=None`.** The switch already covers them, but the
  argument is the local, readable guarantee and every existing helper now carries it.
- **`verify_turnstile("", "")` is now `False` rather than a network round trip.** Any caller
  that relied on an empty secret meaning "pass" would break — none does; both callers gate on
  the secret before calling.
- The variable is deliberately absent from `runtime/.env.example` and
  `docs/reference/api-surface.md`: it configures a *test run*, not a deployment, and adding it
  to the example file would invite someone to set it on a server.
- The per-agent database `spatalk_test_hermetic_settings_in_tests` was created for this task
  and dropped afterwards.
