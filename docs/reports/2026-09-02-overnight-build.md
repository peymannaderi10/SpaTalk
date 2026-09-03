# Overnight build report, 2026-09-02

## Result
all phases complete: plans A (runtime, voice, ledger), B (text channels), C (portal), D (Instagram and Messenger), E (operations E1 to E10) and S (SMS staff delivery) are built and committed; QA gates A, B and C passed with majors and every major that touched product code is fixed; the final review is `docs/reports/review-2026-09-03.md`. The workflow's own reviewer and report agents failed on Anthropic's side (login expiry, then HTTP 529), so the orchestrating assistant wrote both.

## Test evidence
runtime: pytest 948 passed, 2 skipped of 950 (scratch database, tree at `fc392cb`), ruff clean yes
portal: wasp build ok yes (gate C); unit 108/108, client 70/70, e2e 77/77 with `RUNTIME_SEED_COMMAND` set (0 ran without it: open minor)
edge: vitest 23/23
promptfoo: not completed — 5 passed, 2 failed, 23 quota errors of 30 on the free-tier Google key; the two failures are the Python grader crashing on Windows, no product failure. Re-run once on the paid key from WSL or the VPS.

## Deviations from the plans
- runtime A1-A16: Pipecat 1.8 API confirmed from source; `attach_router` helper for FastAPI 0.141; Postgres on host port 5434 (`docs/reports/tasks/runtime-A*.md`)
- fix after gate A: payment lexicon widened; Slack button values became signed tenant-bound tokens (`runtime-fix-payment-lexicon.md`, `runtime-fix-slack-signed-buttons.md`)
- fix after gate B: `SPATALK_NO_ENV_FILE` makes the suite hermetic; opt-out keywords normalised (`runtime-fix-hermetic-settings-in-tests.md`, `runtime-fix-sms-optout-matching.md`)
- real-model fixes: existing-appointment questions captured as band 2; two graders relaxed for clarifying turns; judge model is `gemini-2.5-flash` (`runtime-fix-real-model-findings.md`)
- E1: loop guard from `public_phone`, `sms_from_number`, `voice_numbers` and the registry (`ops-E1.md`); its alert path was corrected in review (`841df3f`)
- E6: OpenAI added as the second vendor behind `LLM_MODEL=openai:<model>`; one temperature for both (`ops-E6.md`)
- E10: live transfer spike and implementation; `transfer_number` stays null until a real non-forwarding back-line exists (`ops-E10.md`, `docs/runbooks/transfer.md`)
- S1/S2: staff SMS delivery replaces Slack and WhatsApp for the demo; escalation prefix applied inside the builder; bare `done` without an id is refused (`sms-staff-S1.md`, `sms-staff-S2.md`); verifier gaps closed in `29e4a9b`
- W1 only of the WhatsApp plan is in the tree (destination kind, migration 0008), dormant by founder decision (`whatsapp-W1.md`)
- fix after gate C: `runtime/spatalk/rates.json` synced with `docs/research/rates.json` (`fix-rates-table-drift.md`)

## QA gate findings
- gate A: major payment lexicon gap -> fixed `runtime-fix-payment-lexicon`; major Slack buttons unbound to tenant -> fixed `runtime-fix-slack-signed-buttons`
- gate B: major suite reads `runtime/.env` -> fixed `c4cd291`; major opt-out whole-string match -> fixed `a79c47b`
- gate C: blocker packaged rates drift -> fixed `c3db47c`; major loop-guard alert never sent or deduplicated -> fixed `841df3f`; major 10.1 GB image with CUDA -> fixed `841df3f` (size to confirm on next build); major portal e2e cannot seed a runtime from containers -> open (test infrastructure); major promptfoo cannot complete on this machine -> open until the paid Google key exists; minor clinical voice wording on text channels -> fixed `841df3f`; minor promptfoo grader crash on Windows -> open (run elsewhere); minor `api-surface.md` two portal variables -> open; minor portal test commands rewrite a committed file -> open; minor `tsc --noEmit` on a clean edge checkout -> open (passes with `node_modules`)

## Reviewer findings (open)
- `runtime/spatalk/ops/retention.py` retention coverage: `meta_events` dedup rows are never pruned; add one delete older than `retention_days`.
- `runtime/spatalk/voice/pipeline.py` `make_tts` soniox branch: correct by construction, latency unmeasured; the week-1 bake-off (Soniox vs Inworld) is still owed.
- Everything else in the review is fixed (`841df3f`, `fc392cb`) or verified; see `docs/reports/review-2026-09-03.md`.

## What the founder must do this morning
1. Google: create the paid `spatalk` project with billing, make a new API key, put it in `runtime/.env` as `GOOGLE_API_KEY`. The free tier is capped at 20 requests a day and cannot carry a demo call. This also rotates the key that passed through chat; rotate the Soniox and Telnyx keys the same way when convenient.
2. `runtime/.env` already carries `SKINCENTRIX_STAFF_SMS`, `TTS_PROVIDER=soniox`, `SONIOX_VOICE=Bryce`. Fill `portal/.env.server` and the edge secrets per `docs/runbooks/accounts-and-env.md` when the portal or the edge worker is needed; neither is needed for the phone demo.
3. Demo day: `docs/runbooks/local-demo.md` (tunnel, `.env` host lines, `spatalk serve`, Telnyx TeXML voice URL and messaging profile `spatalk-sms` webhook to the tunnel, one warm-up call). Deploy to the VPS per `docs/runbooks/deploy.md` only when a clinic goes live.
4. Not verifiable without keys or accounts: the promptfoo suite on the paid key (one run), a live Soniox voice bake-off, the Deepgram opt-out on a Deepgram account, the Telnyx failover bin and a real transfer once a back-line exists, Meta app review before real Instagram or Messenger accounts connect, the Jane feed timing test in `docs/runbooks/jane-sync-test.md` after Jane answers the Terms question, and whether the Telnyx messaging profile offers a sender blocklist (plan F).
5. Queued next by founder decision: plan F, the SMS flood guard (`docs/superpowers/plans/2026-09-02-sms-flood-guard-plan.md`), as its own workflow with a verifier.
