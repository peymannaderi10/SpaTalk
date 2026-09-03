# operations Task E10: Live transfer spike and implementation

Status: done with deviations
Commit: <pending>
Tests: `uv run pytest tests/test_voice_transfer.py -q` -> 20/20; full suite `uv run pytest -q` -> 934/935 (1 pre-existing failure, see Deviations)
Interfaces produced: `Transferred(number_masked)`; `TransferRequest`; `Capabilities.transfer`; `TierCCapabilities.transfer`; `build_tools(cfg, transfer_enabled=False)`; `tools_schema(cfg, transfer_enabled=False)`; `TRANSFER_TOOL`; `spatalk.voice.transfer.{TransferPort, TelnyxTransfer, MemoryTransfer, make_transfer, attempt_transfer, transfer_available, mask_number, suppress_auto_hangup, TRANSFER_TIMEOUT_SECONDS}`; `VoiceSession.{call_control_id, transfer, transfer_enabled, transferred, hangup_params}`

## What was built

The spike itself cannot run tonight (it needs a live call, a Telnyx application and a second
phone; `CLAUDE.md` forbids all three to an agent). `docs/runbooks/transfer.md` is therefore
the spike as a founder procedure, with an empty result table to fill in, plus Option B
written out as a change set rather than as code.

Everything around the spike is implemented and tested against a fake carrier, coded for
**Option A**: transfer the TeXML-originated leg with
`POST /v2/calls/{call_control_id}/actions/transfer`, using the `call_control_id` Telnyx puts
in the media stream's start message (`call_data["call_id"]`, the same id the serializer
already uses to hang up).

- **Exposure by calendar state.** `transfer_available(cfg, now)` is true only when the tenant
  has a `transfer_number` and `BusinessCalendar.is_open(now)`. `run_call` computes it once
  per call and passes it to `tools_schema(cfg, transfer_enabled=...)`; the handler is
  registered only when it is true. Outside hours or without a back-line the tool does not
  exist for the model at all. Skincentrix ships `transfer_number: null`, so today it never
  appears; a test pins that.
- **The tool.** `transfer_to_human`, no parameters, therefore no free text. It is deliberately
  **not** in `TOOL_NAMES`: that tuple is what every call always has, and this one is a
  property of the moment rather than of the tenant.
- **The outcome.** `Transferred(number_masked)`, in the `Outcome` union, rendered by the
  renderer from `scripts.transferring` — the same script the handler speaks before it dials,
  so the two cannot drift. `spatalk/brain/tier_c.py` does not contain the word `Transferred`
  and a test asserts it never will, mirroring the `Completed` rule.
- **The fallback.** `TierCCapabilities.transfer` files an urgent `escalation_human_request`
  item and returns `Captured`. It runs when no number is configured, and when the carrier
  refuses, errors, or stays silent past `TRANSFER_TIMEOUT_SECONDS` (20 s). The item is written
  *before* the `human_request` wording is spoken, so the sentence the caller hears is backed
  by a row. If the ledger itself fails, the handler speaks `refuse_unavailable` and promises
  nothing.
- **The carrier behind a port.** `TransferPort` with `TelnyxTransfer` (httpx) and
  `MemoryTransfer` (records calls; `fail=True` refuses, `delay=` never answers).
  `attempt_transfer` never raises and never blocks past the budget: a missing port, a missing
  leg id, a missing number, a refusal and a timeout are one answer, `False`. No test touches
  a network; the Telnyx client is exercised through `httpx.MockTransport`.

## Deviations

- **`spatalk/voice/transfer.py` is a new file the plan's Files list does not name.** The plan
  put the tool in `handlers.py` and the capability in `tier_c.py`, but the task also asks for
  a carrier client behind a port with a fake. Putting the port, the client, the fake, the
  budget and the availability rule in one voice-owned module keeps the vendor named in one
  place (the same shape as `spatalk/sms.py` for `SmsPort`) and keeps `handlers.py` about
  handlers. `TRANSFER_TOOL` lives in `brain/tools.py` with the other tool names and is
  re-exported from `voice/transfer.py`, so the import direction stays voice → brain.
- **`spatalk/voice/texml.py` is unchanged.** Option A transfers the live leg over the API and
  needs nothing from the front door; the `call_control_id` arrives on the media socket, not in
  the TeXML form post. A test asserts the TeXML response is still `<Connect><Stream>` for a
  tenant that has a back-line, so "Option A leaves the front door alone" is pinned rather than
  assumed. Option B replaces this handler wholesale; the change set is section 3 of the runbook.
- **`runtime/tenants/skincentrix/tenant.yaml` is unchanged.** `transfer_number: null` with its
  UNVERIFIED comment was already added by runtime plan Task 1, and it is the correct shipped
  value until the spike runs.
- **Two things outside the plan's Behaviour list, both needed for a successful transfer to
  survive:**
  1. `TelnyxFrameSerializer` hangs the call up on the first `EndFrame` or `CancelFrame` when
     `auto_hang_up` is on, which is the default. Our pipeline shuts down seconds after a
     transfer, so without intervention the runtime would hang up the leg the caller is now
     talking on. `run_call` now holds the serializer's own `InputParams` instance and a
     successful transfer switches `auto_hang_up` off on it (`suppress_auto_hangup`). Evidence:
     `python -c "import inspect; from pipecat.serializers.telnyx import TelnyxFrameSerializer as T; print(inspect.getsource(T.serialize)[:400])"` →
     `if (self._params.auto_hang_up and not self._hangup_attempted and isinstance(frame, (EndFrame, CancelFrame))): ... await self._hang_up_call()`.
     No `EndFrame` is queued on the success path either, for the same reason.
  2. `schedule_missed_call_textback` (text-channels B3) treats a short call with speech as a
     missed call. A transferred call is short because we handed it over, so the caller who is
     mid-conversation with a staff member would have been texted "You just called us. Reply
     here and I can help." One guard added: `if session.transferred: return False`.
- **Full suite is 934/935.** The one failure,
  `tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table`, is
  pre-existing drift between `runtime/spatalk/rates.json` and `docs/research/rates.json` (E9's
  files, neither touched here). Evidence: `git stash push -u -- runtime/spatalk runtime/tests`
  then running that test alone → `1 failed in 0.10s` with my changes stashed.

## Notes for neighbours

- `build_tools` and `tools_schema` gained a keyword-only-by-convention second argument with a
  default of `False`. Every existing caller (`brain/driver.py`, `scenarios/voice/eval_bot.py`,
  the tests) is unaffected; the text channels never expose the tool, and a `transfer_to_human`
  call arriving on a text channel falls through `dispatch_tool` to `Refused(out_of_scope)`.
- `Outcome` is now `Captured | LinkSent | Refused | Transferred | Completed`. Anything that
  switches exhaustively on outcome kind — scenario asserts, portal views, the nightly audit —
  should expect `"transferred"`, which `docs/reference/data-model.md` already lists.
- `Capabilities` gained `transfer(ref, TransferRequest) -> Transferred | Captured`. A future
  Tier A adapter must implement it; Tier C's returns `Captured` and is the honest default.
- The spike result table in `docs/runbooks/transfer.md` §4 is the gate. Until it is filled in
  and a real back-line exists, `transfer_number` stays `null` and no caller is ever offered a
  transfer.
