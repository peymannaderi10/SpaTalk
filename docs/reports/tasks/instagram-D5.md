# instagram Task D5: Scenarios, runbook and CI

Status: done with deviations
Commit: `b2d72ac` `test(social): instagram scenarios and meta setup runbook` (hash filled in by the
follow-up docs commit; a hash cannot be written into the commit that carries it)
Tests: `uv run pytest tests/test_social_scenarios.py -q` -> 25/25; with the neighbours it
touches, `uv run pytest tests/test_social_scenarios.py tests/test_text_scenarios.py
tests/test_scenarios_provider.py tests/test_edge_sync.py -q` -> 57/57; full runtime suite
`uv run pytest -q` -> 497 passed, 13 failed (all pre-existing, see Deviations), 1 skipped;
`uv run ruff check spatalk tests scenarios` -> "All checks passed!"
Interfaces produced: `scenarios.asserts.{social_brevity, link_inline, SOCIAL_LIMIT}`
(`chat_link_inline` kept, now delegating to `link_inline`); four `channel: instagram` cases in
`runtime/scenarios/promptfooconfig.yaml`; `docs/runbooks/meta-setup.md`;
`runtime/tests/test_social_scenarios.py`

## What it does

**The graders.** `scenarios/asserts.py` gains `social_brevity`, the promptfoo half of this
plan's global constraint ("Reply in under 500 characters, plain text, no emoji unless the
customer used one"). It fails a reply over 500 characters, a reply carrying markdown, a reply
that claims an action, and — the part that is specific to this channel — an emoji the customer
never used. "The customer used one" is read from `vars.user` and from the user turns in
`vars.history`, so mirroring a smiley passes and introducing one into a plain conversation does
not.

**The scenarios.** Four cases with `channel: instagram`, all with `caller: ""` because Instagram
gives us no phone number: a price question by DM (graded `band1_answer` + `social_brevity` +
contains "99"), a clinical DM (graded `band3_gate` + contains "911", the rules gate before the
model), a booking-link request (graded `link_inline` + `social_brevity` — the link is shown in
the thread, never texted), and one where the customer opens with an emoji.

**The comment path, deterministic.** The plan says explicitly that the comment case is a pytest
and not a promptfoo case, because a comment arrives as a webhook and never as a turn.
`tests/test_social_scenarios.py` replays the recorded comment payload re-worded to the promo-post
question ("how much?") through the real router with a real HMAC signature, runs the job it
queues, and then grades **what actually left for Meta**: one private reply addressed
`{"recipient": {"comment_id": …}}` carrying the `dm_greeting` disclosure and the model's answer,
no public reply while the tenant has it off, nothing texted, no item filed for a band-1 answer,
and the reply passing `social_brevity`. It also asserts the comment turn reached the brain with
the Instagram channel rule in the system prompt, so the promptfoo DM cases and the comment path
are graded against the same register.

**The provider.** Three tests prove the promptfoo cases will exercise what they claim before
anyone spends a key on them: the Instagram channel rule reaches the system prompt, the booking
link is inline with no SMS, and the clinical DM is gated before the model and files an urgent
item even with no phone number.

**The runbook.** `docs/runbooks/meta-setup.md`: what the connection is and where each secret
lives, creating the app (Business Login, not Facebook Login), the two webhook doors and their
fields, the runtime environment table with the Fernet key command, Standard vs Advanced Access
and what each means for onboarding, the Instagram Tester invite flow, what the clinic does
(Settings → Integrations → Connect, the multi-Page choice, Disconnect), token refresh and
`needs_reconnect`, the App Review checklist (Business Verification, screencast, per-permission
use-case text, privacy and data-deletion URLs, test credentials), a troubleshooting table, and
what CI covers.

**CI.** The runtime job already ran the whole suite, so the social tests were already covered;
this task makes that a checked property rather than an accident.
`test_ci_runs_the_social_tests_in_the_runtime_job_without_extra_secrets` parses `ci.yml` and
fails if the pytest step ever grows a `-k`, `--ignore` or `--deselect`, or if the runtime job
starts asking for an `INSTAGRAM_*`, `FACEBOOK_*` or `META_*` value; a companion test fails if the
`test_social_*.py` files stop existing, so the first test cannot pass vacuously. A comment on the
step in `ci.yml` says the same thing to a human.

## Deviations

- **`chat_link_inline` was generalised rather than duplicated.** The plan's Instagram case ("link
  shown inline, no SMS") is exactly what B6's chat grader checks, and Tier C treats `chat`,
  `instagram` and `messenger` as one class (`INLINE_LINK_CHANNELS`). The body moved to
  `link_inline` and `chat_link_inline` now returns `link_inline(output, context)`. B6's name and
  behaviour are unchanged and its tests are untouched and green; `test_the_inline_link_grader_is_
  shared_with_the_chat_case_unchanged` pins both names to the same result. **Anything new should
  use `link_inline`.**
- **A fourth Instagram scenario was added beyond the three the plan lists** (customer opens with
  an emoji). The plan's constraint has two halves and the three listed cases only exercise the
  "no emoji" half in the negative; without a case where an emoji is allowed, a grader that simply
  banned every emoji would pass the suite.
- **No new fixture was recorded.** The plan's D5 file list has no fixtures, and the promo-post
  comment is D2's `comment.json` with the comment text replaced in the test body (the same
  mutation D2's own tests use for message ids). A near-duplicate fixture would have been one more
  file to keep in step with Meta's payload shape.
- **`ci.yml` was changed by four comment lines only.** The behaviour the plan asks for ("CI runs
  the social tests as part of the runtime job, no extra secrets") was already true of
  `uv run pytest -q`; adding a second, social-only pytest step would have run those tests twice
  for no signal. The failable check is the test that reads the workflow. Note that D4 already
  added four dummy `INSTAGRAM_*`/`FACEBOOK_*` values to the **portal** job (its Integrations tab
  needs a connect URL); the assertion above is scoped to the runtime `test` job, which is where
  the social tests actually run and where no Meta value exists.
- **`docs/superpowers/specs/…-architecture-design.md` was edited** — one row appended to the §7
  subprocessor register for Meta. The plan's self-review assigns that edit to this task; the file
  is otherwise untouched, and `test_meta_is_in_the_subprocessor_register` keeps it there.
- **The runbook assertion is case-insensitive.** `screencast` appears as "**Screencast**" at the
  head of a checklist item; lower-casing both sides checks the content the plan lists without
  dictating sentence case.
- **promptfoo itself was not run.** It needs `GOOGLE_API_KEY` and a paid Gemini call, which this
  environment does not have and this task is not allowed to spend (`CLAUDE.md`: one run per QA
  gate, and no key exists here). Everything about the new cases that can be checked without a
  model is checked deterministically: the YAML parses, every `python` assert resolves to a real
  function, every Instagram case carries an empty `caller`, every case whose reply comes from the
  model is graded for length and emoji, and the graders themselves are unit-tested against the
  replies they are supposed to reject. **The QA gate must still run
  `npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache` with a key before this plan is
  called done.**
- **The 13 failures in the full runtime suite are pre-existing and unrelated**, the same 13 D3 and
  D4 recorded: `tests/test_widget.py` (11), `test_takeover.py::test_a_staff_message_left_waiting_
  is_delivered_when_the_widget_reconnects` and `test_text_sms.py::test_a_telnyx_signature_is_
  accepted_when_no_edge_key_is_configured`. Nothing this task touches is imported by any of them:
  the changes are a new test file, two `scenarios/` files, two docs and four comment lines in
  `ci.yml`. The widget ones reach `challenges.cloudflare.com` for Turnstile from a sandbox with no
  network; the Telnyx one signs against the `FixedClock` (2026-09-01) and verifies against the
  wall clock, now 2026-09-02, outside the 300 s freshness window. No test was skipped, weakened or
  touched here.

## Notes for neighbours

- **A real honesty wrinkle this task surfaced but did not fix.** On a channel with no phone
  number, the band-3 gate still renders `scripts.clinical`, which says "someone will call you back
  at this number". On Instagram there is no number: the item it files carries no contact at all
  (`escalate` → `_with_caller`, and `ref.caller_phone` is empty), so the assistant promises a
  call back on a channel where the team can only answer in the Instagram inbox. The scenario suite
  now grades that path (`band3_gate` + "911"), which is what the plan asks for, and it passes —
  the wording is the problem, not the code. The fix belongs to whoever owns tenant scripts: either
  a channel-aware clinical script, or the same username capture D2 already does for the
  expired-window callback item. Flagging rather than changing, because `scripts.yaml` and
  `renderer.py` are not D5 files and the wording is enforced by `docs/reference/tenant-config.md`.
- **`link_inline` is the name to use** for "the booking link was shown, not texted", on any screen
  channel. `chat_link_inline` still works and means the same thing.
- **The operations plan's CI work should keep the runtime pytest step unfiltered**;
  `test_ci_runs_the_social_tests_in_the_runtime_job_without_extra_secrets` will fail on a `-k`,
  `--ignore` or `--deselect` there, and on a Meta value appearing in that job's env.
- **The widget and Telnyx failures are still open** and are now three tasks old. B2/B4's owner
  should inject the Turnstile verifier in every widget test and sign the Telnyx fixture against
  the clock under test; nothing in the social plan can reach them.

Blocked on: nothing.
