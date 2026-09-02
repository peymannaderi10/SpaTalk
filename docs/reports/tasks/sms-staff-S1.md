# sms-staff-delivery Task S1: SMS destination, delivery job, digest
Status: done with deviations
Commit: c672865
Tests: `uv run pytest -q tests/test_sms_staff_delivery.py` -> 17/17; full suite `uv run pytest -q` -> 772/773 (the one failure, `test_internal_api.py::test_the_packaged_rates_match_the_researched_table`, is pre-existing on `c984cae` and unrelated: it compares `spatalk/rates.json` with `docs/research/rates.json`, neither of which this task touches)
Interfaces produced: `Destination(kind="sms", address_env=...)`, `spatalk.ledger.delivery.build_sms_text(item, cfg, links, now=None, escalation=False)`, `build_list_sms(items, cfg, now=None)`, `sms_segments(text)`, `sms_destination_numbers(cfg)`, `SMS_STAFF_LIMIT`, `SMS_HEALTH_LINE`, `SMS_DIGEST_TEXT`, `SMS_LIST_HEADER`, `SMS_LIST_MAX_ITEMS`, job `deliver.sms`, `schedule_item_delivery` sms branch, `_digest_sms`

## What was built

- `Destination.kind` gains `"sms"`; the validator refuses one without `address_env`, so an owner's mobile is always named and never written into a bundle. The dormant `"whatsapp"` kind from plan W is untouched.
- `build_sms_text` renders one item as at most three GSM-7 segments (459 characters): head with the tenant name, item id, type label and channel; who; due; the health line when flagged; `Reply ACK <id> or DONE <id>.`; and the transcript link last. Over the limit, lines are **dropped**, never truncated, in the order health line, who line; the transcript URL survives every cut.
- `sms_segments` counts what the carrier bills: GSM-7 (160 / 153 with the concatenation header, extension characters costing two septets) or UCS-2 (70 / 67 code units).
- Job `deliver.sms`: resolves `to` from `os.environ[to_env]` (warn and return when unset, since a missing variable is a configuration gap no retry fixes); skips with a warning when `(tenant, to)` is opted out; **raises** when `cfg.sms_from_number` is null, so the job retries and then dead-letters where the job-health alert finds it; sends via `ctx.sms.send(cfg.sms_from_number, to, text)`; records `sms_out` usage with the segment count.
- `schedule_item_delivery` enqueues one `deliver.sms` per `sms` destination, honouring `urgent_only`, and reaches every destination for urgent and escalated items.
- The digest job also texts `"{Name} front desk: {n} open item(s). Reply LIST for details."` to every `sms` destination.
- `LIST` from a staff number replies with `build_list_sms`: a count line and up to five item lines with ids, capped at 459 characters.
- `runtime/tenants/skincentrix/tenant.yaml` carries `sms_from_number: "+12899170079"` and an `sms` destination naming `SKINCENTRIX_STAFF_SMS`; email, Slack and the dormant WhatsApp destination are kept.

Deviations:
- `build_sms_text` takes `escalation: bool = False` and puts `"ESCALATED, past due: "` inside the builder, where the plan has the job prepend it. Because if the job prefixed the finished string, an escalated message could exceed the 459-character rule the same function is responsible for. The job passes `escalation` through; behaviour is identical apart from the limit being honoured. Evidence: `tests/test_sms_staff_delivery.py::test_an_escalated_item_says_so_at_the_front_of_the_message` asserts the prefix arrives through the job.
- The message adds `"URGENT: "` for an urgent item, which the plan's template does not show. Every other channel builder (`build_email`, `build_slack_blocks`, `build_whatsapp_text`) marks urgency, and a staff phone is the one place it matters most.
- The `LIST` reply is wired into `spatalk/text/sms.py`, which the plan's File Structure assigns to Task S2, because S1's own Tests list requires it and the digest S1 sends says "Reply LIST for details". It sits in a delimited `# --- sms staff delivery (plan S) ---` block and authorises the sender with `staff_phone_numbers` **or** `sms_destination_numbers(cfg)`. See "Notes for neighbours".
- `_digest_sms` warns and skips on a null `sms_from_number` instead of raising. A raise would fail the whole digest job and resend the emails already delivered on the retry.
- Setting `sms_from_number` in the bundle (which the plan's Global Constraints require: "the bundle must carry the tenant's messaging number") broke five tests in files this task does not own, all of which asserted the *bundle's* null number rather than saying "no number" out loud. Each was changed to null the number explicitly, preserving its intent:
  - `tests/test_edge_sync.py` (2 tests) — new `_take_the_tenants_sms_number_away(registry)` helper.
  - `tests/test_ops_alerts.py` (1 test) — new `_silent_tenant(registry)` helper, mirroring the existing `_texting_tenant`.
  - `tests/test_tier_c.py` (1 test) — `cfg.model_copy(update={"sms_from_number": None})` in the test body.
  - `tests/test_internal_api.py` (2 tests) — the tenant listing now expects the sms number (the registry registers `sms_from_number` as a number of kind `sms`), and the `otherclinic` fixture starts with `sms_from_number: None` so a second tenant does not claim skincentrix's number.
  - `tests/test_delivery.py` (1 test) — four destinations rather than three; the context gains a `MemorySms` and the test now asserts the staff text.
  `tests/test_ops_alerts.py` belongs to the operations plan, which another workflow is executing concurrently. The change is confined to one test body plus one new helper; nothing existing was reordered or reformatted.

Notes for neighbours:
- **Task S2** should replace the S1 block in `spatalk/text/sms.py` with `spatalk.text.staff.staff_numbers(cfg)` and `parse_staff_command`. `sms_destination_numbers(cfg)` in `spatalk/ledger/delivery.py` already resolves the `address_env` of every `sms` destination and is exactly the second half of `staff_numbers`; `staff_numbers` should be `set(cfg.delivery.staff_phone_numbers) | sms_destination_numbers(cfg)`. The `LIST` branch returns `{"ok": True, "handled": "staff_list"}` and calls `build_list_sms(open_items, cfg, now)`; keep both when folding ACK and DONE in beside it.
- The reply instruction in the message body is exactly `Reply ACK <id> or DONE <id>.`, so S2's parser must accept those two forms verbatim in addition to the aliases the plan lists.
- The digest text is `SMS_DIGEST_TEXT` and the list header `SMS_LIST_HEADER`; both are module constants, not tenant scripts, because they are staff-facing and no customer ever sees them (the same reasoning as `takeover.HANDBACK_NOTE`).
- `runtime/.env.example` gains `SKINCENTRIX_STAFF_SMS=`; `docs/runbooks/local-demo.md` is S2's to rewrite.
- The bundle's messaging number `+12899170079` is now registered as a tenant number of kind `sms` whenever the bundle is imported. Any test that creates a second tenant from skincentrix's config must null it first.

Blocked on: nothing.
