# QA gate B fix: sms-optout-matching

Status: done with deviations
Commit: <filled below>
Tests: `cd runtime && uv run pytest -q tests/test_text_sms.py -k optout` -> 40/40 (20 deselected);
`uv run pytest -q tests/test_text_sms.py` -> 60/60; full suite `uv run pytest -q` -> 591 passed,
1 skipped; `uv run ruff check spatalk tests scenarios` -> All checks passed.
Interfaces produced: `spatalk.text.sms.normalise_keyword(text) -> list[str]`,
`spatalk.text.sms.is_optout(words) -> bool`, `SHORT_STOP_WORDS`, `SHORT_STOP_MAX_WORDS`

## The finding

QA gate B, major 2: `STOP_WORDS` was matched whole against `text.strip().lower()`, so
`"STOP."`, `"STOP ALL"`, `"stop!"`, `"Please stop"` and `"unsubscribe me"` were handed to the
model instead of unsubscribing the sender. A trailing full stop is what a phone keyboard
produces on its own and `STOP ALL` is a CTIA standard keyword, so the exact match was not the
carrier rule.

## What changed

`runtime/spatalk/text/sms.py`:

- `normalise_keyword(text)` lowercases, replaces every run of non-alphanumeric characters
  with a space and splits: `"  STOP, please! "` -> `["stop", "please"]`.
- `is_optout(words)` is true when the first word is one of
  `stop, stopall, unsubscribe, cancel, end, quit`, or when the message is at most three words
  and contains `stop` or `unsubscribe`. The three-word ceiling is what separates
  `"please stop"` from `"can you stop by the clinic"`; a longer sentence that merely mentions
  stopping keeps reaching the brain, because silencing a customer who asked a question would
  be the worse of the two failures.
- `_keyword_reply` now takes the raw `text` and normalises it once. START and HELP get the
  same normalisation but stay a whole-message match (`len(words) == 1`): they are opt-in and
  informational, and widening `yes` to a first-word match would have unsubscribed nobody but
  would have swallowed `"yes I would like to book Thursday"`.
- The call site drops `word = text.strip().lower()`.

No send path changed: reply (`service.handle_inbound`, `service._deliver`), follow-up
(`service._send_followup`), missed-call text-back (`textback.schedule_missed_call_textback`
and the `sms.textback` handler) and the staff relay (`takeover._relay_sms`) already consult
`is_opted_out` before sending, which the new tests now pin.

## Tests added (`runtime/tests/test_text_sms.py`, 46 new cases)

- `test_an_optout_phrasing_unsubscribes_before_the_brain` — 23 phrasings
  (`STOP`, `stop`, `" STOP "`, `STOP.`, `stop!`, `Stop, please`, `STOP ALL`, `stop all`,
  `stopall`, `STOPALL`, `Please stop`, `please stop!`, `stop texting me`, `UNSUBSCRIBE`,
  `unsubscribe.`, `unsubscribe me`, `Unsubscribe me please`, `CANCEL`, `cancel!`, `END`,
  `end.`, `QUIT`, `quit!`). Each asserts the `sms_optouts` row, the fixed confirmation
  wording, and `llm.calls == []`.
- `test_a_sentence_that_merely_mentions_stopping_is_not_an_optout` — 7 negatives
  (`can you stop by the clinic`, `Do I have to stop using retinol before my peel?`,
  `I need to cancel my appointment on Friday, is that ok?`,
  `When does your promotion end this month?`,
  `The elevator will quit working during the renovation, right?`,
  `Please do not stop sending me appointment reminders.`, `What time do you open today?`).
  Each asserts no opt-out row and exactly one model call, so the positives cannot pass
  vacuously.
- `test_a_start_phrasing_removes_the_optout` — 8 phrasings, `test_a_help_phrasing_answers_from_the_script` — 6.
- `test_the_brain_is_never_called_for_an_opted_out_number` — after `"Please stop."`, two
  ordinary questions produce no model call and no SMS.
- `test_no_followup_or_textback_reaches_an_opted_out_number` — a queued `text.followup` and a
  queued `sms.textback` both run after `"STOP ALL"` and send nothing.

Seen failing before the fix: the same file at the pre-fix `sms.py` gave
**25 failed, 21 passed** (`STOP.`, `stop!`, `Stop, please`, `STOP ALL`, `stop all`,
`Please stop`, `please stop!`, `stop texting me`, `unsubscribe.`, `unsubscribe me`,
`Unsubscribe me please`, `cancel!`, `end.`, `quit!`, every punctuated START and three HELP
phrasings). No test was weakened, skipped or deleted.

## Deviations

- `stopall` stays in the first-word set even though the task listed only
  `stop, unsubscribe, cancel, end, quit`. It was already in the pre-fix `STOP_WORDS` and is a
  CTIA keyword; dropping it would have removed working behaviour. `STOP ALL` (two words) is
  covered by the first-word rule regardless.
- START/UNSTOP/HELP/INFO are normalised but matched as the whole message rather than by first
  word. `yes` is a START word, and a first-word rule there would have turned
  `"yes, Thursday works"` into an opt-in confirmation instead of an answer.
- `runtime/tests/test_text_sms.py` is committed carrying one line that is not mine:
  `Settings(_env_file=None, secret_key="s3cret", ...)` in `_build`, from the engineer fixing
  QA gate B finding 1 (test hermeticity). That agent rewrote the file mid-task from a stale
  snapshot and erased this task's appended block once; the block was restored from a
  scratchpad copy and their one-line change kept. Evidence:
  `git diff -- runtime/tests/test_text_sms.py` showed only that hunk after the block vanished,
  and `wc -l` fell from 372 back to 235. The finding-1 agent's commit will therefore not need
  to touch this file.
- Full-suite numbers (591 passed, 1 skipped) include that agent's in-flight changes to
  `spatalk/settings.py`, `spatalk/text/chat.py`, `tests/conftest.py` and the other test
  modules; this task's own commit touches only `spatalk/text/sms.py`,
  `tests/test_text_sms.py` and this report.

## Notes for neighbours

- `normalise_keyword` and `is_optout` are importable from `spatalk.text.sms` if the edge
  worker or a future channel needs the same rule. The edge worker
  (`edge/sms-worker/`) was not touched and does not implement opt-out itself; the runtime
  remains the only net, as gate B recorded.
- Worth a product decision later: a message that *starts* with `cancel`, `end` or `quit` is
  now an opt-out, per the task's rule, so `"cancel my appointment on Friday"` unsubscribes
  the sender and answers with the opt-out confirmation instead of filing a change request.
  `"I need to cancel my appointment on Friday"` (the far commoner phrasing, and the one in
  the negative set) is unaffected. If the medspa wants the narrower behaviour, the change is
  to move `cancel`/`end`/`quit` out of the first-word set and back to whole-message matches;
  that is a product call, not a compliance one, so it was left as the task specified.
- Per-agent test database `spatalk_test_sms_optout_matching` was created and dropped again.
