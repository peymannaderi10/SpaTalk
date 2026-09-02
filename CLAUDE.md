# SpaTalk

Multi-tenant AI front desk for appointment-based clinics: answers phone, SMS, web chat and Instagram from one knowledge base per tenant, and turns every non-self-serve request into a tracked item a human completes. First tenant: Skincentrix, a medspa in Mississauga, Ontario. The product is the reliability of that ledger and the guarantee that the system never claims an action it did not take.

## Where the truth lives

- Product brief: the founder's brief (sections referenced as §N throughout) is summarised in the spec.
- Architecture spec: `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md`. Read §3, §4, §5 before touching anything.
- Plans, executed in this order: `docs/superpowers/plans/2026-09-01-runtime-voice-ledger-plan.md` (fully coded), then `…-text-channels-plan.md`, `…-portal-plan.md`, `…-instagram-plan.md`, `…-operations-plan.md` (contract level: files, interfaces, tests, done criteria).
- Reference (wins over a plan when they disagree): `docs/reference/data-model.md` (every table, index, enum, retention), `docs/reference/tenant-config.md` (every config field and every fixed script with its wording), `docs/reference/api-surface.md` (every endpoint, provider payload shapes for fixtures, every environment variable), `docs/reference/flows.md` (step lists for the nine key flows).
- Build orchestration and agent briefs: `docs/agents/`.
- Provider facts and prices: `docs/research/`. Cost model: `python docs/research/costmodel.py docs/research/rates.json`.
- Founder runbooks: `docs/runbooks/`.
- Roadmap and competitive map (what is built, parked or out of scope): `docs/roadmap.md`.

## Repository layout

```
runtime/        Python 3.12 service: Pipecat voice, FastAPI webhooks, brain, ledger, jobs, CLI   (package: spatalk)
portal/         TypeScript control plane cloned from wasp-lang/open-saas (Wasp 0.25): auth, orgs, billing, dashboards
edge/           Cloudflare Worker: SMS webhook front door with offline auto-reply and replay
docs/           spec, plans, research, runbooks, agent briefs, contracts (OpenAPI for the runtime internal API)
```

## Commands

Runtime (run from `runtime/`):

```
uv venv --python 3.12 && uv pip install -e ".[dev]"      # once
docker compose up -d db                                  # local Postgres (creates spatalk and spatalk_test)
uv run pytest -q                                         # unit + integration tests
uv run ruff check spatalk tests scenarios                # lint
uv run alembic revision --autogenerate -m "<msg>"        # after model changes
uv run alembic upgrade head
cd scenarios && npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache   # needs GOOGLE_API_KEY
uv run spatalk --help
```

Portal (run from `portal/`): `wasp start`, `wasp db migrate-dev`, `wasp test client`, `npm run e2e` (Playwright).
Edge (run from `edge/sms-worker/`): `npm test` (vitest + miniflare), `npx wrangler deploy`.

## Non-negotiables (tests enforce most of these; do not weaken the tests)

1. **Structural honesty.** Tier C code never imports or constructs `Completed`. Outcome wording comes from tenant `scripts`, never from a model. Every model utterance passes `guard()` before reaching a channel. A refusal never claims anything was sent or filed. Tests: `tests/test_structural_honesty.py`, `tests/test_renderer.py`, `tests/test_guard.py`, `tests/test_driver.py`, `tests/test_voice_processors.py`.
2. **No free text on tracked items.** `ItemDraft` fields are exactly `type, urgency, service_id, contact, preferred_window, health_context`. Tool schemas exposed to the model have no notes parameter. Volunteered health context is a boolean flag; the detail lives only in the transcript.
3. **Fixed wording is config.** Disclosure, clinical, complaint, payment, callback and goodbye scripts live in `tenants/<id>/scripts.yaml`, not in code and not in prompts.
4. **Providers are swappable by environment or tenant config.** Never hard-wire a vendor; go through `make_stt`, `make_tts`, `make_llm`, `SmsPort`, `DeliveryPort`, `LLMClient`.
5. **Secrets never enter tenant bundles or the repo.** Bundles reference environment variable names. `.env` is gitignored. Tests use fakes (`MemoryLedger`, `MemorySms`, `MemoryDelivery`, `FakeLLM`).
6. **Pipecat 1.8 API only**: `PipelineWorker` + `WorkerRunner`, `LLMContext` + `LLMContextAggregatorPair`, services configured through `Service.Settings(...)`. `PipelineTask`/`PipelineRunner` patterns from older docs are wrong here.
7. **Two planes, zero shared tables.** The runtime owns the Postgres schema `runtime` (Alembic). The portal owns `public` (Prisma). The portal reads and writes runtime data only through `/internal/*` with `X-Internal-Key`.
8. **Business time is tenant time.** All due-time arithmetic goes through `BusinessCalendar` in the tenant's timezone. Never naive datetimes.
9. **Recording off by default, transcripts on, 30-day default retention.** Do not add audio persistence without a tenant flag.
10. **Every task ends with a commit.** Conventional messages. Never `--no-verify`. Never commit `.env`.

## Definition of done for a task

- The task's listed tests exist, were seen failing, and now pass. The full suite for that app passes.
- `ruff check` is clean for the runtime; `wasp` builds for the portal.
- Interfaces named in the task's "Produces" block exist with those exact names and signatures.
- No placeholder text (`TODO`, `TBD`, `pass  # implement`) in shipped code.
- A commit exists with the task's message.
- The task report (format in `docs/agents/ENGINEER.md`) lists any deviation from the plan and why.

## When the plan and reality disagree

Verify against the library's source (`uv run python -c "import inspect, X; print(inspect.signature(X.__init__))"`), make the smallest change that satisfies the task's tests and interfaces, and record the deviation in the task report. Do not silently change an interface another task consumes; note it so the orchestrator can propagate it.

## Things agents must not do overnight

- Buy phone numbers, submit verifications, deploy to the VPS, or change DNS. Those are the founder's morning steps in `docs/runbooks/accounts-and-env.md`.
- Call paid provider APIs except Gemini for the promptfoo suite when `GOOGLE_API_KEY` is present, capped at one run per QA gate.
- Add a dependency that pulls a product-sized stack (Chatwoot, Langfuse, Redis) or a provider with a subscription floor.
- Weaken, skip or delete a test to get green.
