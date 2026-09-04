# Demo day state, 2026-09-03 (late afternoon)

> Note (2026-09-03, late evening): the commit hashes quoted in this document and in `docs/reports/tasks/*` predate a history rewrite that removed attribution trailers from every message before the first push to https://github.com/peymannaderi10/SpaTalk. The commits are the same, in the same order, with new hashes; find one by its message with `git log --oneline --grep`.

Where everything stands after a day of live test calls on the founder's laptop. Written so a fresh session can pick up without the conversation. Newest facts first; the "How to" section at the end has the exact commands.

## In flight right now

- **Nothing.** The lead-context verifier findings were closed by an Opus agent (`3ff71a5`, report `docs/reports/tasks/lead-context-fixes.md`; suite 1054 passed, 0 xfail). The bundle was re-imported (config version 12, `team` present) and the runtime restarted at that code on 2026-09-03 ~15:20, so the qualification step, lead fields and one-line summaries are live. The 15:56 and 16:09 calls then produced the booking-flow and echo fixes below; the runtime was restarted at that code with config version 13 at ~16:25. Requests filed before the restart carry no lead fields and render generic summaries; new ones carry the facts.
- **Nothing.** Call notes is live end to end: N1 landed (`225e096`, report `docs/reports/tasks/call-notes-N1.md`, suite 1105 passed) and was fixed after its first live run (`55df1a5`: the transcript goes to the model as one document because a request ending on the assistant's goodbye got an empty answer; grounding compares word stems; no gender guessed from a name). Migration 0012 is applied to the dev database, config version 15 is imported, the runtime restarted on `55df1a5` at ~17:35, and job 42 drafted notes for the 16:27 call that the internal API now returns on request #10. N2 landed (`a47a388`, report `docs/reports/tasks/call-notes-N2.md`, 82 client tests). The portal was restarted at ~17:50 so it recompiled: on this machine `wasp start` does NOT pick up edits under `portal/src` (the compiled copy under `.wasp/out/sdk` stayed dated 15:07 until the restart), so every portal change needs `stop-portal.sh` then `start-portal.ps1`. Verified in the browser: request #10 shows the "AI notes, drafted from the transcript" block. Plan: (`docs/superpowers/plans/2026-09-03-call-notes-plan.md`): the assistant asks once what the caller would like the team to know, and a post-call job drafts short notes from the transcript onto the conversation (never the item), shown on the request card under an "AI notes, drafted from the transcript" label. It clarifies non-negotiable 2, so it is not built until the founder says so.
- **Late evening (22:30 onward).** Config version 19 (`fix(voice): a short quiet answer ends the turn...`): lower detector thresholds, Soniox endpointing, two-second turn watchdog, interim dedupe and promotion, the `still_there` nudge. History rewritten to remove attribution trailers and pushed to https://github.com/peymannaderi10/SpaTalk (founder rule: no trailers in this repo). Portal: tailwind-merge 3, forms plugin on the class strategy, plain light/dark switch, no front-desk link (`fix(portal): square logo tile when collapsed...`). **Landed (`feat(portal): login lands in the one business...`, report `docs/reports/tasks/portal-entry-E1.md`):** `/app` is an entry resolver (admin -> /admin, one org -> /app/<slug>, none -> empty state, several -> list); the business shell has no Platform section; /admin/tenants rows have "View dashboard"; admins sign in at /admin/login, owners at /login, both routed by role after auth. Verified in the browser after a portal restart.
- **LLM failover is live (config version 18, ~22:10).** `b2ac659` (vendor breaker, text failover, any OpenAI-compatible host as a vendor: openai, openrouter, deepseek, xai, groq, together, fireworks, dashscope with the US endpoint, compat) and `7aaed7f` (per-turn voice router, `model_down` line, `/healthz` `llm` block); reports `docs/reports/tasks/llm-failover-F1.md` and `-F2.md`. `runtime/.env` now has `LLM_MODEL=gemini-3.5-flash`, `LLM_MODEL_FALLBACK=openai:gpt-4.1-mini` and an `OPENAI_API_KEY` (passed through chat, rotate). Healthz reports primary google, secondary openai, active google. gpt-4.1-nano was tried as primary at 21:42 and was a clear regression (filed a booking with no name or service, spoke a tool name, lost the thread); the bracket guard `ab08ad6` came out of it. Cost finding from the usage table: about 190k input tokens per call with only 46% cached, roughly CA$0.05 of model cost per call; next engineering pass is prompt-cache hit rate and duplicate requests per turn. Also queued: the ledger refusing a booking or callback capture without a first name; the promptfoo vendor shootout once keys exist (OpenRouter, DashScope).
- **21:03 and 21:05: Google answered every model request with 503 "high demand" and the caller heard silence** until the idle timeout. Fixed in `5199b8e` (config version 17): every Gemini client retries 429/5xx three times within about four seconds; when a turn still fails the pipeline speaks the tenant's `model_unavailable` script once per ten seconds ("Could you say that once more?"); the call-notes job retries a transient provider error instead of dead-lettering. Provider outages are outside our control; a second vendor on standby (the OpenAI path in `make_llm`) is the next resilience step and needs an `OPENAI_API_KEY`.
- **First outside callers (20:38 from a 437 number, 20:50 from a 647 number) and what they changed** (`acb5be8`, config version 16): a vague "I want to book" is asked what to book; the preferred day is when they want to come in and the assistant never says when the team will call (staff summary now reads "Would like to come in ..."); calmer voice (persona tone, [warm] greeting, one exclamation mark per reply); every booking link is https://skincentrix.janeapp.com/ (the /locations path did not work; the text itself reached the Canadian number, so SMS works for Canadian callers); call-notes grounding keeps a short sentence made only of the caller's words. Transcript sheet scrolls (`b6aa18d`). **Incident:** the 20:50 call was cut off at 20:52 by a runtime restart that ran despite one live call; the conversation row was marked ended, its transcript is lost. Restart the runtime only with `scratchpad/restart-runtime.sh`, which refuses while a voice conversation is open.
- **Portal reskin R0 to R3 landed the same evening** (`fff2906`, `5e3bd41`, `3bdbb5f`, `21fa87c`, `6a51365`, `6d1546f`, `e698d18`, reports `docs/reports/tasks/portal-reskin-R0..R3.md`): the portal is shadcn-admin's shell and pages with SpaTalk's content, 141 client tests, type-check clean, dev server restarted on each step. Still owed for R4 (acceptance): the Playwright suite, which needs an isolated runtime and portal database because `e2e-tests/seed_runtime.py` deletes everything belonging to the `skincentrix` tenant it targets and the suite starts its own `wasp start` on port 3000; a `wasp build`; light and dark screenshots of every route; the accessibility pass. Vitest in WSL needs `source ~/.nvm/nvm.sh && nvm use 22.23.2` first (R3 report).
- Earlier that evening's decision: (`docs/superpowers/plans/2026-09-03-portal-reskin-plan.md`, recommended kit `satnaing/shadcn-admin`, MIT; runner-up `shadcndashboard/shadcndashboard`). Awaiting the founder's confirmation of the kit before Task R0 starts. Brand stays "SpaTalk" for now but moves into one `brand.ts` module so it can change later.
- Also fixed this evening: the admin analytics page logged "Query data cannot be undefined" on every focus because `getDailyStats` returned `undefined` when no stats row exists; it returns `null` now. The stats job itself runs hourly and fails on the dummy Stripe key in `portal/.env.server` ("Invalid API Key provided: sk_test_*ummy", three job-error rows in the portal `Logs` table), so no stats row exists until a real Stripe test key is set.
- Next candidates, in the founder's order: the delivery-failed webhook (a failed text becomes a request), the cost model refresh for Gemini 3.5 Flash, a promptfoo run on the new model, and the lead follow-up decisions (automatic post-call text, lead record, funnel numbers).

## What is live on the laptop

| Piece | State |
|---|---|
| Runtime | `spatalk serve` on port 8000, started from the session shell; log `scratchpad/serve.log` (rotated copies `serve-call*.log`) |
| Tunnel | `https://radio-gorgeous-try-universities.trycloudflare.com` via `C:\Program Files (x86)\cloudflared\cloudflared.exe`; log `scratchpad/cloudflared.log`. Hostname changes if it restarts |
| Telnyx | TeXML app `spatalk-demo` (id 3040385824425248764) voice URL and messaging profile `spatalk-sms` (id 4001a064-4921-4479-b618-fe4c44844bf1) webhook both point at the tunnel; number +1 289 917 0079 (voice and SMS) |
| Skincentrix config | version 19 in the dev database (migration 0012 applied) (`spatalk` on `runtime-db-1`, host port 5434), `team` present |
| Portal | Wasp dev server in WSL, http://localhost:3000 (client) and :3001 (server); started by `scratchpad/start-portal.ps1`, stopped by `scratchpad/stop-portal.sh`; log `scratchpad/wasp-start.log`; its own database `portal` on the same Postgres; `RUNTIME_INTERNAL_URL` is the tunnel; Dummy email provider prints links to the log |
| Portal login | peymon18@gmail.com, agency admin (password was given in chat; reset via "Forgot password", link prints to the wasp log) |
| Mailpit | http://localhost:8025; all runtime email goes here (`SMTP_HOST=localhost`, `SMTP_PORT=1025`) |
| Model | `LLM_MODEL=gemini-3.5-flash` on the founder's paid Google project. That project does NOT serve `gemini-2.5-flash` (404). Gemini 3.x needs `thinking_level` (`minimal`; `low` for 3.7 and 3.8), handled by `gemini_thinking_kwargs` |
| Speech | Soniox STT `stt-rt-v5`; Soniox TTS `tts-rt-v2`, voice `Kayla`; audio tags on for voice only |

`runtime/.env` (gitignored) holds: the paid `GOOGLE_API_KEY` (passed through chat, rotate), `SONIOX_API_KEY`, `TELNYX_API_KEY` (both also passed through chat earlier, rotate), `INTERNAL_API_KEY` (value also in `scratchpad/internal_key.txt`), `SKINCENTRIX_STAFF_SMS=+18567451025`, `PUBLIC_BASE_URL` and `MEDIA_WS_HOST` set to the tunnel host. `TELNYX_PUBLIC_KEY` is still EMPTY, so inbound texts to the runtime are refused with 401 until the founder pastes it from Telnyx (Account, Auth, Public Key).

## What the day changed (all committed on main)

Voice and conversation, in order of impact:

- Model: `gemini-3.5-flash`; Flash-Lite was erratic (0.9 s to 10 s), `flash-latest` stalled; 3.x rejected `thinking_budget=0` with 400 until `gemini_thinking_kwargs` (`4760f0f`, `acf5e01`, `04bbac2`).
- End of turn: Smart Turn v3 with a 1.0 s fallback instead of Pipecat's 3 s (`ae688a9`, `1fc602b`). Barge-in needs three transcribed words while the assistant speaks (`0216195`).
- Echo scrubber: the assistant remembers what it said; a transcription that opens with those words is trimmed, pure echo dropped (`3b4bf70`).
- Guard: an offer to arrange a booking ("help you get that booked") is not a claim; claims still blocked (`b2ae38e`). Prompt bans the words even in offers.
- Prompt: Ava persona, three sentences a turn, greeting is not a question, no preambles, booking flow (name and number in one question, link or callback), audio tags, clock line last for caching (`66decf9`, `fc392cb`, `b2ae38e`, `ecac571`, `acf5e01`).
- Fillers: built (`1fc602b`) then switched off by founder taste; empty by default, opt-in per tenant (`ecac571`).
- Outcome scripts end with "Is there anything else I can help with?" (`21c30c6`).
- Knowledge and catalog from skincentrix.com: 1,200 words, 42 services with prices, website hours (Monday closed) (`66decf9`).
- After the 15:56 and 16:09 calls: the echo scrubber only touches speech the phone picked up while the assistant was talking (plus a one-second tail) and only when the matching words start at the front of the utterance, because "I'd prefer a call from the team" had been dropped as an echo of the question and Ava fell silent; the output guard keeps a space after each sentence so TTS no longer runs "Welcome!We" together; a new caller is asked whether they want to hear the new-client offers before any are recited, a suggested treatment is offered as a choice ("go with that or hear another option") and the name is asked only once they have chosen; `knowledge.md` lists the offers in one section with the $50 credit first (config version 13).
- Founder decision after the 16:09 call: the caller no longer hears a clock time ("by 7:29 p.m."); every team script says "as soon as they're free" (normal) or "as soon as possible" (urgent). The due time is still computed, stored on the item, shown as "Promised by" in the portal and sent in the staff alert; only the spoken wording changed (`scripts.yaml`, reference rule updated, config version 14).
- Lead context (plan L, `docs/superpowers/plans/2026-09-03-lead-context-plan.md`): `returning_client`, `practitioner`, `concern` on items; `summarize_item`; qualification step; portal card leads with the summary (`69dd0bf`, `13977db`, verifier `7eaf2e8`). CLAUDE.md non-negotiable 2 widened to nine closed fields.

Earlier today: final review and overnight report (`f7fa0b1`), SMS flood guard F1 to F3 (`7f030d7`, `53f9324`, `df60698`), SMS staff delivery gaps (`29e4a9b`), roadmap and review-replies plan, Jane sync probe and runbook, cost sheet artifact (https://claude.ai/code/artifact/9e795b55-0ea0-401b-b43e-0cc6ceef9958).

## Known limits and open founder items

- **Texts to the founder's phone fail**: Telnyx error 40010, the 289 number is not 10DLC-registered and US carriers require it. Options: register 10DLC on Telnyx, buy and verify a Canadian toll-free (covers US too), or test with a Canadian mobile. Canadian customers are not affected.
- The assistant says "I've just texted you" on Telnyx acceptance; delivery can fail afterwards. Planned, not built: handle Telnyx's `message.finalized` delivery-failed webhook by filing an item and alerting.
- Keys passed through chat: Google (paid), Soniox, Telnyx. Rotate.
- Portal admin dashboard daily-stats tile needs a real Stripe test key in `portal/.env.server`.
- Cost model (`docs/research/rates.json`, cost sheet) still prices Gemini 2.5 Flash; refresh for 3.5 Flash.
- Promptfoo suite not yet re-run on the new model (judge must not be 2.5 Flash on this project).
- Lead follow-up ideas awaiting a founder decision: automatic post-call follow-up text (consent question), lead record at call end, funnel numbers on the overview.
- Jane: partner program is closed to AI products; read-only feed poller needs Jane's written OK (runbook `docs/runbooks/jane-sync-test.md`).
- Meta app review before real Instagram or Messenger accounts connect.
- The QA fixtures seeded into the dev database were deleted (555 numbers, e2e tenant); only the founder's real calls remain.

## How to

Restart the runtime: `bash $SCRATCH/restart-runtime.sh` (refuses while a call is live; `--force` only for a stale row). The manual sequence it wraps, from Git Bash (never `uv run`, the entry point is locked):

```bash
cd /c/Users/Peyman/source/repos/SpaTalk/runtime
PID=$(powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)" | tr -d '\r'); [ -n "$PID" ] && powershell -NoProfile -Command "Stop-Process -Id $PID -Force"
(.venv/Scripts/python.exe -c "import sys; from spatalk.cli import app; sys.argv=['spatalk','serve','--host','0.0.0.0','--port','8000']; app()" > "$SCRATCH/serve.log" 2>&1 &)
curl -s https://radio-gorgeous-try-universities.trycloudflare.com/healthz
```

Import the bundle after editing it: `.venv/Scripts/python.exe -c "import sys; from spatalk.cli import app; sys.argv=['spatalk','tenant','import','tenants/skincentrix']; app()"` then restart.

Run tests: `SPATALK_NO_ENV_FILE=1 TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_review .venv/Scripts/python.exe -m pytest -q` (create the scratch database first if an agent dropped it: `docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_review"`).

If the tunnel restarts: read the new hostname from `scratchpad/cloudflared.log`, update `PUBLIC_BASE_URL` and `MEDIA_WS_HOST` in `runtime/.env`, PATCH the Telnyx TeXML app `voice_url` and the messaging profile `webhook_url` (curl with `TELNYX_API_KEY`), update `RUNTIME_INTERNAL_URL` in `portal/.env.server`, restart runtime and portal.

Portal: `powershell -NoProfile -File scratchpad/start-portal.ps1` to start (about 40 to 90 s), `wsl -e bash -c 'bash .../stop-portal.sh'` to stop. Do not run `wasp build` while it runs: it regenerates `.wasp/out` and the dev server dies. Restart it after any change under `portal/src`: the dev server does not recompile edits on its own here, so the browser keeps running the old code until a restart.

Read a call: `grep -a "Generating chat from context" scratchpad/serve.log` for what the caller said, `grep -a "Generating TTS"` for what was spoken, `grep -a "turns="` for latency.

`$SCRATCH` = `C:\Users\Peyman\AppData\Local\Temp\claude\C--Users-Peyman-source-repos-SpaTalk\7e74060c-108a-4dc0-9708-e397c6cf43b6\scratchpad`.
