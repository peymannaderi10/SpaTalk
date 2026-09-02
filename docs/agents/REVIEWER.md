# Reviewer brief

Two readers use this: the reviewer agent after QA gate C, and the founder's reviewing assistant in the morning. Read the diff against the spec's invariants, not against taste. Findings, not rewrites.

## Read in this order

1. `docs/reports/<date>-overnight-build.md`, then every `docs/reports/tasks/*.md` "Deviations" section. Deviations are where drift hides.
2. `runtime/spatalk/brain/` in full. This is the product.
3. `runtime/spatalk/voice/pipeline.py`, `processors.py`, `handlers.py`.
4. Every HTTP entry point: `runtime/spatalk/http/*`, `voice/texml.py`, text-channel and Instagram routers, the edge worker, portal server actions.
5. Migrations and models.
6. Tests, checking that they assert behaviour rather than restate the implementation.

## Invariants to check line by line

- `tier_c.py` contains no `Completed`. `dispatch_tool` returns rendered text and the voice handler passes `run_llm=False`. `OutputGuardProcessor` sits between the LLM and TTS in the pipeline list. A guard block files an item before it speaks "passed it to the team".
- No `Refused` template and no failure path speaks "sent", "filed", "passed it", or a callback time.
- Every inbound webhook verifies its origin: Telnyx SMS signature (Ed25519 with timestamp tolerance), Slack signing secret, Meta HMAC-SHA256 against both app secrets, stream tokens expire, action links are GET-confirm then POST-act, internal API requires `X-Internal-Key` with constant-time compare.
- `ItemDraft` has exactly six fields; no model or migration adds a text column to `items` beyond `contact_*`, `service_id`, `type`, `owner`, `state`, `urgency`, `channel`.
- Provider construction only in the factory functions; no vendor SDK imported elsewhere in the brain.
- Aware datetimes everywhere; `BusinessCalendar` for due times; `ZoneInfo(cfg.timezone)` for anything shown to humans.
- Transcripts are written from context messages at call end; recording is not enabled anywhere.
- Retention job covers conversations, messages, usage detail; deletion receipt written.
- Portal: no Prisma model references the `runtime` schema; all runtime data flows through the generated client; authorization checks on every query that takes an organisation id (a client must never see another tenant).
- Edge worker: forwards with a shared secret, auto-replies only on upstream failure, replays from KV, never replies twice to the same message id.

## Red flags that are always findings

- A test that mocks the function under test.
- A `try/except: pass`.
- A prompt that contains a script (disclosure, clinical, complaint, payment wording) instead of `scripts.yaml`.
- `datetime.now()` without `timezone.utc`.
- A migration that drops or renames a column in the same file that adds one.
- `allow_interruptions`, `PipelineTask`, `OpenAILLMContext`: pre-1.8 Pipecat patterns.
- Any URL or phone number literal outside tests and tenant bundles.

## Output (write to `docs/reports/review-<date>.md`)

```
# Review <date>
Verdict: ship to VPS for the first call | fix these first
Findings (most severe first):
- [blocking|major|minor] <file:line> <invariant> <one sentence: what is wrong and what would fix it>
Verified invariants: <bulleted list of the checks above that passed, with the file you checked>
```
