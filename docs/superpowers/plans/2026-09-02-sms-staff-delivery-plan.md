# SMS Staff Delivery Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Tests first. Founder decision 2026-09-02: tracked items go to the business owner's phone as ordinary SMS (Slack parked, WhatsApp dropped). Email delivery stays. The WhatsApp destination kind from the earlier plan stays in the code as dormant; nothing here removes it.

**Goal:** Every tracked item, every escalation and the daily digest reach the owner's mobile as SMS from the tenant's own Telnyx number within seconds, and the owner can acknowledge or resolve by replying `ACK 4821` or `DONE 4821`.

**Architecture:** A `sms` destination kind on `Delivery.destinations` with `address_env` (an environment variable name holding the E.164 number, so personal numbers never enter the bundle). A `deliver.sms` job that sends through the existing `SmsPort` (`TelnyxSms` in production, `MemorySms` in tests) from `cfg.sms_from_number`. Staff replies come in through the existing `POST /telnyx/sms` path: a sender whose number is any `sms` destination's number, or in `staff_phone_numbers`, may acknowledge or resolve with a keyword; everything already there (`#<id>` relay, STOP handling) stays.

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §3 (ledger delivery), §5 (no free text; nothing generated). Depends on the runtime plan Tasks 8 to 10 and the text-channels plan B2 and B5.

## Global Constraints

- Everything in the runtime plan's Global Constraints. Staff messages are built from item fields and fixed wording; never from model output.
- No personal number in a bundle: `address_env` only. The number resolved from it is automatically authorised as staff for replies.
- A message is at most three SMS segments (459 GSM-7 characters): item id, type label, who, due wording, a health-context line when flagged, the reply instruction, and one transcript link. Never truncate a link; drop the least important line first (health-context line last, since it carries no detail).
- Opt-outs are respected even for staff: if the owner's number is in `sms_optouts` for that tenant, log a warning and send nothing; an email destination still receives the item.
- Sends use `cfg.sms_from_number`; if it is null the job fails with a clear error (not silently), so the bundle must carry the tenant's messaging number.

## File Structure

```
runtime/spatalk/tenants/schema.py            Destination.kind gains "sms"; validator: sms needs address_env
runtime/spatalk/ledger/delivery.py           build_sms_text(item, cfg, links, now) -> str; job deliver.sms; schedule_item_delivery handles kind sms; digest job sends a short digest by SMS to sms destinations
runtime/spatalk/text/sms.py                  staff keyword handling: ACK/DONE (aliases OK, ACKNOWLEDGE, RESOLVE, RESOLVED, DONE) + item id; authorisation = sms destination numbers or staff_phone_numbers
runtime/spatalk/text/staff.py (new)          staff_numbers(cfg) -> set[str] resolving address_env values; parse_staff_command(text) -> ("ack"|"resolve"|"relay"|None, item_id, remainder)
runtime/tenants/skincentrix/tenant.yaml      sms_from_number: "+12899170079"; destinations: email (kept), {kind: sms, address_env: SKINCENTRIX_STAFF_SMS}, slack (kept, dormant)
runtime/.env.example                         SKINCENTRIX_STAFF_SMS=
docs/reference/tenant-config.md, api-surface.md   the new kind and variable
docs/runbooks/local-demo.md                  SMS notifications replace the Slack section; messaging profile webhook step on demo day
runtime/tests/test_sms_staff_delivery.py, test_sms_staff_replies.py, test_tenant_bundle.py (extended)
```

## Task S1: SMS destination, delivery job, digest

**Interfaces:**
- `Destination(kind="sms", address_env="SKINCENTRIX_STAFF_SMS")`; `urgent_only` honoured; escalation and urgent items go to every sms destination regardless.
- `build_sms_text(item, cfg, links, now) -> str`: `"{Name} front desk #{id}: {type label} via {channel}. Who: {name} {phone|email}. Due {humanized}. Reply ACK {id} or DONE {id}. Transcript: {url}"`, plus `"Caller mentioned a health condition; read the transcript first."` when `health_context`; drop lines in the order health line, who line, until under 459 characters; the transcript URL is never cut.
- `schedule_item_delivery(sf, item, cfg, escalation=False)`: enqueue `deliver.sms` with `{item_id, tenant_id, to_env, escalation}` per sms destination.
- Job `deliver.sms`: resolve `to` from `os.environ[to_env]` (warn and skip if unset), skip with a warning if `(tenant, to)` is opted out, fail loudly if `cfg.sms_from_number` is null, send via `ctx.sms.send(cfg.sms_from_number, to, text)`, record usage `sms_out` with the segment count, prefix `"ESCALATED, past due: "` when `escalation`.
- Digest: the existing digest job also sends `"{Name} front desk: {n} open item(s). Reply LIST for details."` to sms destinations; a staff reply `LIST` returns up to five open items, one line each, with ids.
- `JobContext.sms` is the port (already present); `build_context` wires `TelnyxSms`.

**Tests:** destination validation (sms needs address_env); builder content and the 459-character rule with a long name and a flagged item; scheduling per destination and for urgent items with `urgent_only`; job sends through `MemorySms` with the right from/to and records usage; unset env skips; opted-out staff number skips with a warning and email still goes; null `sms_from_number` raises so the job retries and dead-letters visibly; digest SMS text and the `LIST` reply.

**Done when:** tests pass, suite green, bundle test updated. Commit `feat(delivery): sms destination to staff phones with reply keywords`.

## Task S2: Staff replies: ACK, DONE, LIST

**Interfaces:**
- `staff_numbers(cfg) -> set[str]`: `staff_phone_numbers` plus the resolved `address_env` of every sms destination (missing env ignored).
- `parse_staff_command(text) -> tuple[str | None, int | None, str]`: normalises (lowercase, strip punctuation); returns `("ack", id, "")` for `ack 4821`, `ok 4821`, `acknowledge #4821`; `("resolve", id, "")` for `done`, `resolve`, `resolved`, `closed`; `("relay", id, remainder)` for `#4821 on my way` (existing behaviour); `("list", None, "")` for `list`; `(None, None, text)` otherwise.
- In `POST /telnyx/sms`, before the customer path: if the sender is in `staff_numbers(cfg)`: run the command; `ack`/`resolve` call the ledger (actor `sms:<number>`), write an audit row, reply `"#4821 acknowledged."` or `"#4821 resolved."`; an unknown id replies `"No open item #4821."`; `list` replies the open items; anything else replies `scripts.help_text`. A staff number never reaches the brain.

**Tests (through the real `/telnyx/sms` route with the edge key, `MemorySms`):** each keyword form; unknown id; a non-staff number sending `DONE 4821` is treated as a customer message and changes nothing; an item from another tenant cannot be resolved from this tenant's staff number; audit rows written; `LIST` output.

**Done when:** tests pass; `docs/runbooks/local-demo.md` rewritten for SMS (owner number in `.env`, messaging profile webhook to `https://<tunnel>/telnyx/sms` on demo day, what the owner sees and replies). Commit `feat(text): staff acknowledge and resolve by sms reply`.

## Self-review against the spec

- Delivery on a channel staff already use, acknowledge and resolve without a login: S1, S2.
- No free text and nothing generated: message built from item fields and fixed wording; staff replies are keywords, never fed to the model.
- Security: staff authorisation by configured numbers only; cross-tenant ids refused; audit rows on every action.
- Compliance: opt-outs respected; personal numbers only through environment variable names.
