# sms-staff-delivery Task V1: adversarial verification of S1 and S2

Status: done — pass with majors (two major findings, five minor; no product code changed)
Reviewer: Opus 5, 2026-09-02. Reviewed commits `c672865` (S1) and `a81ec9c` (S2) against
`docs/superpowers/plans/2026-09-02-sms-staff-delivery-plan.md`, `docs/agents/REVIEWER.md` and
the CLAUDE.md non-negotiables.
Tests added: `runtime/tests/test_sms_staff_verification.py` — 22 passed, 3 xfailed(strict).
Suite: `TEST_DATABASE_URL=…/spatalk_test_sms2 python -m pytest -q` -> 914 passed, 2 skipped,
3 xfailed, 1 failed; the one failure is
`test_internal_api.py::test_the_packaged_rates_match_the_researched_table`, proved pre-existing
below. (The tree also carries the operations workflow's uncommitted E6 changes; the same
failure and the same count appear with and without this review's file.)

## Findings (most severe first)

- **[major] `runtime/spatalk/text/sms.py` `_staff_reply` / `_send` (approx. lines 175-215):
  an opted-out staff number is still answered.** The plan's Global Constraints say "Opt-outs
  are respected even for staff: if the owner's number is in `sms_optouts` for that tenant, log
  a warning and send nothing". `deliver.sms` and `_digest_sms` obey; the inbound reply path
  does not — `_send` checks only `cfg.sms_from_number`, so `ACK`, `DONE`, `LIST`, "No open
  item" and the help text all go out to a number that texted STOP. The customer path is
  filtered inside `TextConversationService`, so staff are the only senders who get an
  unfiltered reply. Repro: `test_an_opted_out_staff_number_is_answered_with_nothing`
  (xfail strict). Fix: route staff replies through the same opt-out check the delivery job
  uses, exempting only the carrier-required STOP/HELP confirmations in `_keyword_reply`.

- **[major] `runtime/spatalk/ledger/delivery.py` `build_sms_text` (approx. lines 800-841):
  the three-segment rule is enforced in characters, so a non-GSM-7 character costs seven
  segments.** The limit is `SMS_STAFF_LIMIT = 459`, counted with `len()`, while `sms_segments`
  in the same module knows that one character outside GSM 03.38 makes the whole body UCS-2 at
  67 code units per segment. A name with a curly apostrophe (what a phone keyboard produces),
  an accent outside the GSM table, or an emoji therefore yields a message that is under the
  character limit and over the segment promise — measured: 426 characters, `sms_segments` = 7 —
  and `record_usage` then meters the seven the carrier bills. Repro:
  `test_a_staff_text_is_three_segments_even_when_a_name_is_not_gsm7` (xfail strict; the name is
  200 characters, which the `contact_name` column allows). Fix: drop lines while
  `sms_segments(text) > 3` rather than while `len(text) > 459`.

- **[minor] `runtime/spatalk/ledger/delivery.py` `build_list_sms` (approx. lines 813-825): a
  caller-dictated name forges an item line in the `LIST` reply.** `_sms_who` deliberately
  collapses whitespace (`" ".join(who.split())`); `build_list_sms` interpolates
  `item.contact_name` straight into a newline-joined list. `contact_name` is whatever the model
  transcribed from the caller and is stored verbatim by `PgLedger.create_item`, so a caller who
  gives their name as `Dana\n#9999 Callback requested, Mallory, due now` puts a second,
  fictitious item on the owner's phone. Nothing can be resolved through it (an unknown id
  answers "No open item"), but the owner is reading a forged ledger line. Repro:
  `test_a_caller_name_cannot_forge_an_item_line_in_the_list_reply` (xfail strict). Fix: reuse
  the same whitespace collapse in the list line.

- **[minor] `runtime/spatalk/ledger/delivery.py` `_sms_who` (approx. line 795): the who line is
  caller-supplied text, and it now sits on a phone next to a tappable link.** A caller whose
  name is recorded as `Dana see http://evil.example/t` gets that string into the staff SMS
  immediately before `Transcript: <real link>`. This is pre-existing and channel-wide
  (`build_email`, `build_slack_blocks` and `build_whatsapp_text` interpolate the same column),
  and it is inside the agreed data model — `ItemDraft.contact` is one of the six fields — so it
  is not a plan-S regression. It is worth a decision now that the destination is SMS: either
  strip URL-shaped tokens from the who line, or accept it explicitly.

- **[minor] `runtime/spatalk/ledger/delivery.py` `_deliver_sms` (approx. lines 890-915): the
  job trusts its own payload and a live item.** It never asserts
  `item.tenant_id == payload["tenant_id"]`, so a mis-enqueued payload would text tenant A's item
  to tenant B's staff phone; and `ctx.ledger.get` returning `None` (an item purged by retention
  between enqueue and run) raises `AttributeError` inside the opt-out warning or the builder
  rather than skipping, so the job burns its attempts and dead-letters. Both are shared with
  `_deliver_slack`, `_deliver_email` and `_deliver_whatsapp`, so this is a convention to fix
  once across delivery, not a plan-S defect.

- **[minor] `runtime/spatalk/text/staff.py` `staff_numbers` (approx. line 38): authorisation is
  a bare string compare against raw environment values.** `destination_address` returns
  `os.environ[...]` unnormalised, so `SKINCENTRIX_STAFF_SMS="+1 519 555 0123"`, a trailing
  newline, or a national-format number silently de-authorises the owner: their `ACK 4821` is
  not recognised, goes to the brain as a customer message, and the assistant answers the owner
  as if they were a caller. `docs/runbooks/local-demo.md` asks the founder to hand-edit this
  variable on demo morning, which is exactly when it will happen. Fix: `.strip()` the resolved
  value and compare in a single normalised form.

- **[minor, informational] `runtime/spatalk/text/sms.py` `inbound_sms` (approx. line 245): the
  only credential for working the ledger by text is the sender's caller id.** SMS sender ids are
  forgeable through some A2P gateways, and a forged one acknowledges or resolves an item with an
  audit row that names the owner (`sms:+1…`). The plan chose number-based authorisation
  deliberately ("staff authorisation by configured numbers only"), so this is recorded, not
  charged: if it ever matters, the reply keyword would need a per-item code, which the message
  already has room for.

## Verified invariants

Each of these was attacked, not merely read; the tests named are in
`runtime/tests/test_sms_staff_verification.py`.

- **No staff message contains model output.** What `MemorySms` received is character-for-character
  what `build_sms_text` produces from the item's columns (only the time-signed action token
  differs between two calls), and an assistant turn stored on the same conversation appears
  nowhere in it. The digest is a count from a module constant, `LIST` is item columns, the
  unrecognised-message reply is `scripts.help_text` through `render_script`, and the three
  staff sentences are constants. `test_the_staff_text_is_the_pure_builder_output_and_carries_no_conversation_words`.
- **A non-staff number cannot acknowledge or resolve.** `ACK <real id>` from the caller's number
  leaves the item `open` with `acknowledged_by` null, writes no audit row, sends no
  confirmation, and is handled as an ordinary customer message.
  `test_a_customer_number_cannot_acknowledge_a_real_open_item`.
- **A staff number cannot act on another tenant's item.** With the other tenant's item verified
  open first, `ack <their id>` answers "No open item #…", changes no state and writes no audit
  row; `LIST` names only this tenant's items and never the other tenant's name or ids.
  `test_a_staff_number_cannot_acknowledge_another_tenants_item`,
  `test_the_list_reply_never_names_another_tenants_open_item`.
- **Authorisation is resolved per request.** Unsetting `SKINCENTRIX_STAFF_SMS` demotes the number
  to a caller immediately; an unset variable authorises nobody rather than widening the set.
  `test_a_number_whose_variable_is_gone_is_no_longer_staff`.
- **Opt-outs are respected on the way out.** An opted-out staff number receives neither the item
  (S1's own test) nor the digest, while the email destination still gets both.
  `test_a_staff_number_that_texted_stop_gets_no_digest_either`. The inbound reply path is the
  gap, filed as the first finding above.
- **A null `sms_from_number` fails loudly.** `deliver.sms` raises with the tenant id and the item
  id in the message, the job requeues with `last_error` naming `sms_from_number`, and with its
  attempts spent it lands in `dead` having sent nothing (S1's test, re-read and confirmed). On
  the reply path the ledger still moves but nothing is sent and nothing is claimed.
  `test_a_tenant_with_no_messaging_number_claims_nothing_on_the_reply_path`.
- **The 459-character rule never cuts the transcript link.** A 200-character name, a
  187-character email, urgent + escalated + health-flagged, and all of them at once: the body
  stays within the limit, ends with the whole URL and contains it exactly once. The last-resort
  branch (`text[:room] + " " + tail`) provably cuts inside the head, never inside the tail:
  the body is `A + " " + tail`, so `len(text) > 459` implies `len(A) > 458 - len(tail) = room`.
  Confirmed with a 600-character tenant name — 459 characters out, one `Transcript:`, link
  whole. `test_the_transcript_link_survives_every_shape_of_item`,
  `test_an_absurd_tenant_name_cuts_the_head_and_still_ends_in_the_whole_link`.
- **A staff number never reaches the brain.** `ack`, `done`, `LIST`, `#<id> words`, a bare
  `#<id>`, an unknown id, free text and an empty body all leave `ctx.llm.calls == []` and return
  the documented `handled` value. `test_no_staff_branch_ever_reaches_the_brain` (8 cases).
- **Personal numbers appear only as environment variable names.** Every `sms` and `whatsapp`
  destination carries `address_env` and no literal `address`; the schema validator refuses an
  `sms` destination without one; and the only E.164 literal in any file of
  `runtime/tenants/skincentrix/` is `+12899170079`, the tenant's own messaging number.
  `runtime/.env.example` ships `SKINCENTRIX_STAFF_SMS=` empty.
  `test_the_bundle_writes_no_number_but_the_tenants_own`.
- **The suite is green on my own database.** `spatalk_test_sms2`, created and dropped for this
  review. 913 passed, 1 skipped, 1 failed. The failure,
  `test_the_packaged_rates_match_the_researched_table`, is unrelated and predates this work:
  `runtime/spatalk/rates.json` and `docs/research/rates.json` are byte-identical to each other's
  earlier selves at `c984cae` (before S1), `c672865`, `a81ec9c` and `HEAD`, and the diff is in
  `voice_stacks`/`tts` rates, which plan S never touches.

## Notes on the two reports' deviations

Each deviation S1 and S2 recorded was checked against the code, and all of them hold up:
`escalation` inside the builder (otherwise the prefix would break the same function's own
limit), the bare-`done`-is-not-a-command decision (guessing an item is the one thing the ledger
cannot afford), the already-resolved item answering "No open item" rather than acknowledging a
second time, and `_digest_sms` warning rather than raising so a retry does not resend delivered
emails. The staff-facing constants (`SMS_DIGEST_TEXT`, `STAFF_ACK_REPLY` and the other two) are
consistent with `takeover.HANDBACK_NOTE`: non-negotiable 3 governs customer-facing wording, and
no customer can reach these strings.

One thing the reports do not say: S1 changed six test files it does not own, including
`tests/test_ops_alerts.py`, which belongs to the operations plan running concurrently. The
changes are confined to test bodies and two new helpers, and the full suite is green with both
workflows' code in the tree, so nothing was lost — but that is a cross-plan edit and it should
be visible to the orchestrator.

## Deviations from the brief

- The brief asked for tests filling gaps. Three gaps are defects, not omissions, so the tests
  that describe them are `pytest.mark.xfail(strict=True)` with the reason naming the plan line
  they violate. Strict xfail keeps the suite honest in both directions: it fails today (proving
  the gap is real) and it will fail as XPASS the moment someone fixes the product, which is the
  signal to delete the marker. This is a new marker in this repo; no other test uses `xfail`.
- `settings.py` and `models.py` were not read for edits and not touched, as instructed. The
  hermetic-settings fix has landed (`SPATALK_NO_ENV_FILE` in `spatalk/settings.py`, exported by
  `tests/conftest.py`), so `runtime/.env` was left in place and never renamed.
- `uv run` could not be used for most runs: the concurrent operations workflow holds
  `runtime/.venv/Scripts/spatalk.exe`, and `uv`'s sync step fails with `os error 32`. Runs went
  through `runtime/.venv/Scripts/python.exe -m pytest` with the same interpreter and
  environment.

Blocked on: nothing.
