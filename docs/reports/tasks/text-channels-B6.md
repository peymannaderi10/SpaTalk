# text-channels Task B6: Text scenarios, edge tests in CI, tenant-text sync

Status: done with deviations
Commit: recorded by the docs commit that follows this one (the convention set by runtime-A8
through A16 and text-channels B1 to B5: a hash cannot be written into the commit that carries it).
Message: `test(text): sms and chat scenarios; ci for the edge worker; tenant text sync`.

Tests: `uv run pytest tests/test_text_scenarios.py tests/test_edge_sync.py -q` -> 30/30
(21 of them seen failing first — 11 in `test_text_scenarios.py`, all 10 in `test_edge_sync.py`;
the other 9 are noted below). Full runtime suite `uv run pytest -q` -> 327 passed, 1 skipped of
328 (baseline before this task: 297 passed, 1 skipped). Edge suite `cd edge/sms-worker && npm test`
-> 23/23. `uv run ruff check spatalk tests scenarios` -> All checks passed!

Interfaces produced: `scenarios.asserts.sms_brevity(output, context)`,
`scenarios.asserts.chat_link_inline(output, context)`, module constant
`scenarios.asserts.SMS_LIMIT` (300); five new `promptfooconfig.yaml` cases (three
`channel: sms`, two `channel: chat`); `spatalk.cli.collect_tenant_texts(ctx) ->
dict[str, dict[str, str]]`, `spatalk.cli.sync_tenant_texts(ctx, worker_url, key, http=None) ->
dict[str, dict[str, str]]`, constant `spatalk.cli.TENANT_TEXTS_PATH` (`/admin/tenant-texts`),
CLI command `spatalk edge sync-texts <worker_url> [--key K] [--dry-run]`;
CI job `edge` in `.github/workflows/ci.yml`.

## What it does

**Two new graders.** `sms_brevity` fails a reply longer than 300 characters (the plan's global
constraint), a reply carrying markdown (bold, bullet list, heading, `[text](url)` link markup, or
a code span — each named in the failure reason), or a reply that claims an action. `chat_link_inline`
fails a chat turn that has no `link_sent` outcome, one that sent an SMS instead of showing the link,
or one whose reply carries no link at all. Both return the offending reply in `reason`, the style
the existing graders already use.

**Five scenario cases**, appended to `promptfooconfig.yaml` in a delimited block. SMS: the price
question (band 1 plus brevity), the cancellation (fixed captured wording plus brevity), and the
clinical trigger (rules gate, `911` in the reply). Chat: the booking link shown in the conversation
rather than texted, and contact capture across two turns via `history` — chat has no caller id, so
the capture case has to span turns. `channel` was already carried through `provider.py` into
`ConversationRef`, so these cases exercise the per-channel prompt rule, the SMS length budget and
`INLINE_LINK_CHANNELS` for real.

**STOP before the brain** is a pytest, as the plan requires, not a promptfoo case: it is
deterministic and it must never cost a model call. `test_stop_is_handled_before_the_brain` posts
each of the six STOP-family words through `POST /telnyx/sms` against a `FakeLLM` and asserts
`llm.calls == []` and that the reply is the tenant's `optout_confirm` verbatim. Its counterpart,
`test_a_normal_message_does_reach_the_brain`, stops that assertion from passing vacuously.

**`spatalk edge sync-texts`** walks `registry.list_tenants()`, skips every tenant without an
`sms_from_number`, and builds `{<number>: {tenant_id, from, text}}` where `text` is that tenant's
`scripts.offline_reply` rendered through `render_script` — the same wording path every other fixed
script uses, so nothing here is generated. It PUTs that to `<worker_url>/admin/tenant-texts` with
`X-Edge-Key` and raises on a non-2xx. It refuses to push without a key, and pushes nothing at all
when no tenant has an SMS number. `--dry-run` prints what would be pushed without contacting the
worker.

**CI** gains an `edge` job: checkout, `actions/setup-node@v4` with Node 22, then `npm ci` and
`npm test` in `edge/sms-worker`. It is a separate job from `test`, so the worker's tests do not wait
on Postgres and do not depend on any provider key.

## Tests: failing before, passing after

`tests/test_text_scenarios.py` first run: `11 failed, 9 passed`. The 11 failures were the two new
graders (`AttributeError: module 'scenarios.asserts' has no attribute 'sms_brevity'` /
`chat_link_inline`) and the two suite-coverage tests. Of the 9 that passed before the
implementation, 7 are the STOP/normal-message pair, which prove behaviour B2 already shipped but
which B6 is the task that has to assert it; the other 2
(`test_every_python_assert_in_the_suite_names_a_function_that_exists`,
`test_the_suite_names_the_python_provider_and_passes_the_channel_through`) were vacuously green
while the suite had no `channel` cases and became load-bearing once it did.

`tests/test_edge_sync.py` first run: `10 failed` (`ImportError` on `collect_tenant_texts` /
`sync_tenant_texts`, `assert 'edge' in jobs` for the CI job, and the CLI `--help` exit code).
After the implementation: `10 passed`.

## Deviations

- **The worker URL is a CLI argument, not a setting.** The plan's Files list for B6 is
  `promptfooconfig.yaml`, `asserts.py`, `cli.py`, `ci.yml` — `settings.py` is not among them, and
  `docs/reference/api-surface.md`'s complete environment-variable table has no worker-URL variable
  to add. So `sync-texts` takes the worker URL positionally and reads only the key from settings
  (`--key` overrides `settings.edge_shared_key`). This matches how B4 handled the same question:
  the widget takes the worker URL from a `data-fallback` script attribute rather than a setting.
  Evidence: `grep -n "worker" runtime/spatalk/static/widget.js` ->
  `25:  var fallbackBase = script.getAttribute("data-fallback") || api;`.
- **`scripts.offline_reply` did not need adding.** The plan says to add it; B2 already shipped it
  in `tenants/schema.py` and `tenants/skincentrix/scripts.yaml` with exactly the wording the plan
  and `docs/reference/tenant-config.md` give. No schema or bundle change was made. Evidence:
  `grep -n "offline_reply" runtime/spatalk/tenants/schema.py` ->
  `81:    offline_reply: str = (` with
  `"Thanks for texting {name}. We'll reply shortly. To book now: {booking_url}"`.
- **Two test files were added that the plan does not name.** B6's Files list names no test file,
  but the plan's own instruction is to derive failing tests from the behaviours, so
  `runtime/tests/test_text_scenarios.py` (graders, suite coverage, provider channel passthrough,
  STOP before the brain) and `runtime/tests/test_edge_sync.py` (the CLI command and the CI job)
  were added. No existing test file was touched.
- **`promptfoo` could not be run on this machine, so the "promptfoo passes with a key" half of the
  done criterion is unverified.** There is no `GOOGLE_API_KEY` here (`.env` does not exist), and
  calling a paid API is forbidden by `CLAUDE.md`. Even the free `promptfoo validate` refuses to
  start: `cd runtime/scenarios && npx --yes promptfoo@latest validate -c promptfooconfig.yaml` ->
  `promptfoo requires a supported Node.js runtime. Detected: v22.14.0 Required: >=22.22.0` — the
  same fact `ci.yml` already records in a comment, and the reason CI pins `node-version: "22"`
  (the runner resolves that to a current 22.x). In its place, `test_every_python_assert_in_the_suite_names_a_function_that_exists`
  parses the real config and proves every `python` assert it names resolves to a callable, the two
  coverage tests prove the SMS and chat cases are present and graded, and
  `test_the_provider_shows_the_booking_link_inline_on_chat_and_sends_no_sms` /
  `test_the_provider_asks_the_brain_for_an_sms_length_reply` run the provider end to end with a
  `FakeLLM` so the channel plumbing the cases depend on is proven without a key.

## Notes for neighbours

- The five new promptfoo cases run in the existing `test` job's regression step whenever
  `GOOGLE_API_KEY` is set, so the next QA gate that runs promptfoo is the first real execution of
  them. They mirror cases that already pass (the band-1 price question, the band-2 cancellation, the
  clinical gate, the multi-turn capture), with the channel changed and brevity added; if one flakes,
  the failure reason prints the reply.
- `spatalk edge sync-texts` has no line in any runbook. `docs/runbooks/accounts-and-env.md` has an
  uncommitted local edit by someone else and `docs/runbooks/deploy.md` belongs to runtime Task 16,
  so neither was touched. The founder step is: after the toll-free number is verified and
  `sms_from_number` is set on the tenant, run
  `uv run spatalk edge sync-texts https://<worker>.workers.dev` with `EDGE_SHARED_KEY` in the
  environment, and re-run it whenever `scripts.offline_reply` or `booking_url_default` changes.
  Whoever owns the operations plan's runbook task should fold that in.
- The suite baseline this task inherited was 297 passed / 1 skipped, not the 184 quoted in the
  orchestrator's brief; it is now 327 passed / 1 skipped.
