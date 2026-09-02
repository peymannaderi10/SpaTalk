# sms-staff-delivery Task S2: Staff replies: ACK, DONE, LIST
Status: done with deviations
Commit: a81ec9c
Tests: `TEST_DATABASE_URL=…/spatalk_test_sms uv run pytest -q tests/test_sms_staff_replies.py` -> 51/51; full suite `uv run pytest -q` -> 857/859 counted as 857 passed, 1 skipped, 1 failed. The single failure, `test_internal_api.py::test_the_packaged_rates_match_the_researched_table`, is pre-existing (recorded in the S1 report) and compares `spatalk/rates.json` with `docs/research/rates.json`; this task touches neither.
Interfaces produced: `spatalk.text.staff.staff_numbers(cfg) -> set[str]`, `spatalk.text.staff.parse_staff_command(text) -> tuple[str | None, int | None, str]`, `spatalk.text.staff.ACK_WORDS`, `RESOLVE_WORDS`, `LIST_WORD`, `spatalk.text.sms.STAFF_ACK_REPLY`, `STAFF_RESOLVE_REPLY`, `STAFF_UNKNOWN_ITEM`, `_staff_reply`, `_staff_ledger_action`

## What was built

- `spatalk/text/staff.py` (new). `staff_numbers(cfg)` is `set(cfg.delivery.staff_phone_numbers) | sms_destination_numbers(cfg)`, so one list authorises both the `#<id>` relay from B5 and the new keywords, and a destination whose environment variable is unset simply is not in the set. `parse_staff_command` recognises a fixed vocabulary and nothing else: `("ack", id, "")` for `ack|acknowledge|acknowledged|ok|okay <id>`, `("resolve", id, "")` for `done|resolve|resolved|close|closed <id>`, `("relay", id, remainder)` for `#<id> …`, `("list", None, "")` for `list`, and `(None, None, text)` for everything else.
- `POST /telnyx/sms` now sends every authorised sender through `_staff_reply` before the customer path. `ack` and `resolve` call the ledger as actor `sms:<E.164>`, write one `audit_log` row through the same shape `http/actions.py` uses for an email link, and answer `#4821 acknowledged.` / `#4821 resolved.`. `LIST` and the `#<id>` relay keep the behaviour S1 and B5 shipped. Anything unrecognised gets `scripts.help_text`. A staff number never reaches the brain: `ctx.llm.calls == []` is asserted on every staff path.
- Refusals are honest. An unknown id, an id belonging to another tenant, and an id somebody already resolved all answer `No open item #4821.` and change nothing — no audit row, no state transition, no claim.
- Docs: `docs/runbooks/local-demo.md` no longer mentions Slack or WhatsApp anywhere except the "not needed for the demo" line; it gains the Telnyx messaging-profile setup, the `SKINCENTRIX_STAFF_SMS` line in `.env`, the demo-day webhook URL step (`https://<tunnel>/telnyx/sms`) beside the TeXML voice URL, the `EDGE_SHARED_KEY`-must-stay-empty trap, and a new section showing the exact text the owner receives and the table of what to reply. `docs/reference/api-surface.md` gains a staff-reply contract table and updates the `/telnyx/sms` and `<TENANT>_STAFF_SMS` rows; `docs/reference/tenant-config.md` updates `delivery.staff_phone_numbers`. `runtime/.env.example` keeps the variable S1 added and documents that it is also an authorisation, plus the webhook and 401 consequences.

Deviations:
- **The plan's `("resolve", id, "")` examples list bare `done`, `resolve`, `resolved`, `closed`; the parser requires an id with them.** A bare `done` from the owner's phone does not say which item, and guessing (the most recent? the oldest?) would put a wrong state on the ledger, which is the one thing this product cannot do. A bare keyword falls through to the help text, which repeats the `ACK <id>` form. Evidence: `test_anything_else_is_not_a_command[done]` and `…[resolve]`.
- **Aliases beyond the plan's list**: `okay`, `acknowledged`, `close`. They cost nothing and are what a thumb actually types.
- **An already-resolved item answers `No open item #<id>.` rather than acknowledging a second time.** The ledger's `_transition` is a no-op for an item that is already resolved, so replying "acknowledged" would be a claim about a state change that did not happen (CLAUDE.md non-negotiable 1). Evidence: `test_an_already_resolved_item_is_not_acknowledged_a_second_time`.
- **The three staff-facing sentences are module constants in `spatalk/text/sms.py`, not tenant scripts.** No customer can ever see them, and they name an item id rather than an outcome, so the "fixed wording is config" rule (which is about what a customer hears) does not reach them. This follows S1's `SMS_DIGEST_TEXT` and `takeover.HANDBACK_NOTE`.
- **The S1 block in `spatalk/text/sms.py` was replaced rather than appended to**, as S1's own "Notes for neighbours" instructed. The import of `sms_destination_numbers` there is gone (it now reaches the route through `staff_numbers`); `build_list_sms` is still imported directly for the `LIST` reply.
- `runtime/spatalk/models.py` and `settings.py` were not needed. `AuditLog` is imported from `spatalk.models` but the model is untouched.

Notes for neighbours:
- Authorisation for any future staff channel should go through `spatalk.text.staff.staff_numbers(cfg)`; do not re-derive it from `cfg.delivery` at a call site.
- The route's response bodies are now part of the contract that `docs/reference/api-surface.md` documents: `staff_ack`, `staff_resolve`, `staff_unknown_item`, `staff_list`, `staff_relay`, `staff_help`.
- `parse_staff_command` is deliberately total and side-effect free, so a future WhatsApp or Instagram staff path can reuse it without importing the SMS route.
- The demo runbook now tells the founder to edit `sms_from_number` in `runtime/tenants/skincentrix/tenant.yaml` to the number actually bought. The committed value `+12899170079` is still a placeholder until that number exists.

Blocked on: nothing.
