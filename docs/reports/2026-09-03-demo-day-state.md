# Demo day state, 2026-09-03 (afternoon)

Where everything stands after a day of live test calls on the founder's laptop. Written so a fresh session can pick up without the conversation. Newest facts first; the "How to" section at the end has the exact commands.

## In flight right now

- **Nothing.** The lead-context verifier findings were closed by an Opus agent (`3ff71a5`, report `docs/reports/tasks/lead-context-fixes.md`; suite 1054 passed, 0 xfail). The bundle was re-imported (config version 12, `team` present) and the runtime restarted at that code on 2026-09-03 ~15:20, so the qualification step, lead fields and one-line summaries are live. Requests filed before the restart carry no lead fields and render generic summaries; new ones carry the facts.
- Next candidates, in the founder's order: the delivery-failed webhook (a failed text becomes a request), the cost model refresh for Gemini 3.5 Flash, a promptfoo run on the new model, and the lead follow-up decisions (automatic post-call text, lead record, funnel numbers).

## What is live on the laptop

| Piece | State |
|---|---|
| Runtime | `spatalk serve` on port 8000, started from the session shell; log `scratchpad/serve.log` (rotated copies `serve-call*.log`) |
| Tunnel | `https://radio-gorgeous-try-universities.trycloudflare.com` via `C:\Program Files (x86)\cloudflared\cloudflared.exe`; log `scratchpad/cloudflared.log`. Hostname changes if it restarts |
| Telnyx | TeXML app `spatalk-demo` (id 3040385824425248764) voice URL and messaging profile `spatalk-sms` (id 4001a064-4921-4479-b618-fe4c44844bf1) webhook both point at the tunnel; number +1 289 917 0079 (voice and SMS) |
| Skincentrix config | version 12 in the dev database (`spatalk` on `runtime-db-1`, host port 5434), `team` present |
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

Restart the runtime (from Git Bash; never `uv run`, the entry point is locked):

```bash
cd /c/Users/Peyman/source/repos/SpaTalk/runtime
PID=$(powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)" | tr -d '\r'); [ -n "$PID" ] && powershell -NoProfile -Command "Stop-Process -Id $PID -Force"
(.venv/Scripts/python.exe -c "import sys; from spatalk.cli import app; sys.argv=['spatalk','serve','--host','0.0.0.0','--port','8000']; app()" > "$SCRATCH/serve.log" 2>&1 &)
curl -s https://radio-gorgeous-try-universities.trycloudflare.com/healthz
```

Import the bundle after editing it: `.venv/Scripts/python.exe -c "import sys; from spatalk.cli import app; sys.argv=['spatalk','tenant','import','tenants/skincentrix']; app()"` then restart.

Run tests: `SPATALK_NO_ENV_FILE=1 TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_review .venv/Scripts/python.exe -m pytest -q` (create the scratch database first if an agent dropped it: `docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_review"`).

If the tunnel restarts: read the new hostname from `scratchpad/cloudflared.log`, update `PUBLIC_BASE_URL` and `MEDIA_WS_HOST` in `runtime/.env`, PATCH the Telnyx TeXML app `voice_url` and the messaging profile `webhook_url` (curl with `TELNYX_API_KEY`), update `RUNTIME_INTERNAL_URL` in `portal/.env.server`, restart runtime and portal.

Portal: `powershell -NoProfile -File scratchpad/start-portal.ps1` to start (about 40 to 90 s), `wsl -e bash -c 'bash .../stop-portal.sh'` to stop. Do not run `wasp build` while it runs: it regenerates `.wasp/out` and the dev server dies.

Read a call: `grep -a "Generating chat from context" scratchpad/serve.log` for what the caller said, `grep -a "Generating TTS"` for what was spoken, `grep -a "turns="` for latency.

`$SCRATCH` = `C:\Users\Peyman\AppData\Local\Temp\claude\C--Users-Peyman-source-repos-SpaTalk\7e74060c-108a-4dc0-9708-e397c6cf43b6\scratchpad`.
