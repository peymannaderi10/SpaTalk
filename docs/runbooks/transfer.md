# Live transfer to a staffed back-line

The brief promises that during opening hours a caller who asks for a person gets one. Spec
§10 weakness 7 says the clinic may not have a line that can receive that transfer: TELUS
forwards the main number to us, so transferring the caller back to the main number rings us
again. Everything below is about establishing whether a transfer is possible at all, and
about the code that already degrades honestly while the answer is unknown.

**Nothing here has been run.** Placing a live call, changing a Telnyx application and
dialling a clinic line are the founder's steps (`CLAUDE.md`, "Things agents must not do
overnight"). The runtime is coded for **Option A** and tested against a fake carrier; the
spike in section 2 is what decides whether Option A stays.

---

## 1. What ships today

`transfer_number` in `tenants/<id>/tenant.yaml` is `null` for Skincentrix and unverified.
While it is null, **the `transfer_to_human` tool does not exist**: it is not in the tool list
the model is given, and no handler is registered for it. The model cannot offer a transfer
it cannot make, and a caller who asks for a person gets the existing band-3 path — an urgent
item in the ledger and the `human_request` script.

When a `transfer_number` is set, the tool appears **only on calls that start while the clinic
is open** (`spatalk.voice.transfer.transfer_available`: a number *and* `BusinessCalendar.
is_open`). The tool list is built per call, in `run_call`, from the calendar state at the
moment the media socket opens. Outside hours the tool is absent, not refused, because a tool
the model can see is a tool the model will eventually try.

What happens when the model calls it:

1. The caller hears `scripts.transferring` — "One moment, I'll connect you to the team." It
   promises an attempt, not a connection, which is all that is true at that point.
2. The runtime asks the carrier to transfer the leg, and waits at most **20 seconds**
   (`TRANSFER_TIMEOUT_SECONDS`).
3. **Accepted** → outcome `Transferred`, the call belongs to the staff member, and the
   serializer's `auto_hang_up` is switched off so that our pipeline shutting down does not
   hang up the call the caller is now on. No missed-call text-back is sent.
4. **Refused, errored, or silent past the budget** → the Tier C `transfer` capability files
   an **urgent** `escalation_human_request` item first, and only then does the caller hear
   the `human_request` script. The sentence is backed by a row someone has to work. Nothing
   claims a connection happened.

`Transferred` is constructible by the voice adapter only. `spatalk/brain/tier_c.py` does not
contain the word, and `tests/test_voice_transfer.py` asserts that it never will.

---

## 2. The spike: does Telnyx accept a call-control transfer on a TeXML call?

This is the one fact that cannot be established from documentation or from a test. Run it
once, on the live number, and write the result into section 4.

### Before you start

- The app is deployed and answering calls (`docs/runbooks/deploy.md`).
- `TELNYX_API_KEY` is set in the app's environment.
- You have a **second phone** to act as the back-line. Use your own mobile for the spike;
  do **not** use the clinic's main number — it forwards to us and the loop guard will refuse
  it (`docs/runbooks/failover.md`).
- You have a **third phone** to call in from. Calling in from the back-line number itself
  will also be refused by the loop guard.

### Step 1 — set a back-line for the spike

```bash
# runtime/tenants/skincentrix/tenant.yaml
transfer_number: "+1<your mobile in E.164>"
```

```bash
docker compose exec app spatalk tenant import tenants/skincentrix
docker compose exec app spatalk tenant export skincentrix /tmp/spatalk-check
docker compose exec app grep transfer_number /tmp/spatalk-check/tenant.yaml
```

Do this **during opening hours**, or the tool will not be offered and the spike will look
like a model failure instead of a carrier one.

### Step 2 — place the call

Call the clinic's Telnyx number from the third phone. After the disclosure, say:

> "Can I speak to a person, please?"

Expect one of two things:

- your mobile rings, you answer, and the two of you can hear each other — **Option A works**;
- you hear "One moment, I'll connect you to the team", a pause of up to 20 seconds, then
  "Of course. I'm sending a request to the team now, and someone will call you back at this
  number within 15 minutes" — **the transfer was refused or timed out**.

### Step 3 — read what the carrier said

```bash
docker compose logs app --since 10m | grep -i transfer
```

A refusal logs `transfer to *******1234 failed: ...` with the carrier's status and body. The
line to record is the HTTP status and the Telnyx error code. A 422 with a code about the
call not being a call-control call is the answer that sends you to Option B; a 404 usually
means the leg had already ended; a 401 or 403 means the API key, not the call type.

### Step 4 — check the ledger either way

```bash
docker compose exec app spatalk items list skincentrix
```

- Transfer accepted: **no** new item. Correct — the caller reached a person, so there is
  nothing to call back about.
- Transfer refused: exactly **one** urgent `escalation_human_request` item, due within 15
  minutes, with the caller's number. Correct — the promise the caller heard is in the ledger.

If a refused transfer left no item, stop and treat it as a defect: the caller was told
someone would call back and nobody will.

### Step 5 — put the bundle back

Set `transfer_number` back to `null` and re-import, unless the clinic's real back-line is
ready. A `transfer_number` pointing at a personal mobile is a live promise to every caller
during opening hours.

---

## 3. Option B, if the spike fails

If Telnyx refuses a call-control action on a TeXML-originated leg, the number moves from the
TeXML application to a **Call Control application**. The media protocol and the whole
pipeline are unchanged — the same `TelnyxFrameSerializer`, the same WebSocket, the same
tokens — because Telnyx streams media the same way in both. What changes is only how a call
is answered.

This is a described change set, not code that exists. Nothing in the repository is written
for Option B, and none of it should be until the spike says it is needed.

### The change set

1. **Telnyx portal (founder).** Create a Call Control application. Point its webhook at
   `https://<api host>/telnyx/call-control`. Move the voice number from the TeXML
   application to it. Keep the failover URL on the TeXML bin (`docs/runbooks/failover.md`) —
   a bin can be a Call Control application's failover too.

2. **`runtime/spatalk/voice/texml.py` becomes a webhook handler.** Same file, same tenant
   resolution, same loop guard, same `start_conversation`, same signed 5-minute stream token
   — only the response changes. Instead of returning a TeXML document, the handler answers
   `200` immediately and makes two API calls on the `call_control_id` from the
   `call.initiated` event:

   ```
   POST /v2/calls/{call_control_id}/actions/answer
   POST /v2/calls/{call_control_id}/actions/streaming_start
        {"stream_url": "wss://<media host>/ws/<token>",
         "stream_track": "both_tracks",
         "stream_bidirectional_mode": "rtp"}
   ```

   The signed token still travels in the URL path, so `/ws/{token}` and `verify_stream_token`
   do not change.

3. **Webhook authenticity.** A Call Control webhook is signed with the Telnyx public key
   (`telnyx_public_key` already exists in `settings.py` for the SMS front door). Verify it
   the same way, and reject unsigned events; a TeXML application's Voice URL was reached only
   by Telnyx, but a webhook endpoint that answers and streams on request is worth signing.

4. **Ignore the events you do not need.** `call.answered`, `call.hangup`,
   `streaming.started` and `streaming.stopped` all arrive at the same endpoint. Return `200`
   and do nothing for each; `_finalize` in `pipeline.py` still owns the end of the call.

5. **`spatalk/voice/transfer.py` does not change.** The transfer action is already the
   call-control one, and on a call-control leg it is native. `TelnyxTransfer`,
   `attempt_transfer`, the 20-second budget and the `Captured` fallback all stay.

6. **Tests.** `tests/test_voice_texml.py` becomes a webhook test: a `call.initiated` event
   with a valid signature produces an `answer` then a `streaming_start` carrying a token that
   `verify_stream_token` accepts, against a fake HTTP client; an unsigned event is rejected;
   the loop guard still refuses a call from one of our own numbers before answering. The
   transfer tests in `tests/test_voice_transfer.py` are unaffected.

7. **Runbook.** `docs/runbooks/failover.md` section 1 keeps its bin; the "TeXML application"
   wording in `docs/runbooks/accounts-and-env.md` needs updating to "Call Control
   application" for the voice number.

### What Option B costs

One extra API round trip before the caller hears anything (answer, then streaming_start),
which shows up as first-word latency and should be measured against the E5 budget after the
switch. Against that, transfer is a supported action rather than a hopeful one, and the
runtime controls the call rather than describing it.

---

## 4. Spike result

> Not yet run. Fill this in the morning you run section 2, and commit it.

| field | value |
|---|---|
| date run | |
| Telnyx number called | |
| back-line used | |
| clinic open at the time | |
| transfer accepted (Option A works) | |
| HTTP status and Telnyx error code if refused | |
| seconds from "One moment" to ring or fallback | |
| ledger item created when refused | |
| decision | Option A stays / switch to Option B |

Until this table is filled in, `transfer_number` stays `null` in the shipped bundle and every
caller who asks for a person gets the tracked urgent callback. That is the honest default,
and it is the behaviour the tests enforce.

---

## 5. After a successful spike

1. Ask the clinic for a back-line **that does not forward to the Telnyx number**. A TELUS
   extension or a second line is fine; the main number is not.
2. Call that number from an outside phone and confirm a person answers during opening hours.
   A back-line that rings out is worse than a callback, because the caller has already been
   told they are being connected.
3. Set it as `transfer_number`, re-import the bundle, and repeat section 2 steps 2 and 4 once
   against the real line.
4. Watch the first week: `docker compose logs app | grep "transfer to"` shows every attempt,
   with the number masked. A run of failures means the back-line is not being answered, and
   the fallback is filing urgent items nobody asked for — turn `transfer_number` back to
   `null` until it is.
