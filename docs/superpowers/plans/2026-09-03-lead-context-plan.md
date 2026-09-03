# Lead Context Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Tests first (write the test, see it fail, make it pass, commit). Read `CLAUDE.md`, spec §3 and §5, `docs/reference/data-model.md` and `docs/reference/tenant-config.md` first. Founder decision 2026-09-03 (after live demo calls): requests must carry enough context to follow up a lead, and the assistant must qualify a caller before booking. This plan widens the closed set of request fields deliberately; `CLAUDE.md` non-negotiable 2 is updated by task L1 to the new list. No free text is added anywhere.

**Goal:** When a caller wants to book, the assistant learns four things in a natural exchange: new or returning client, what they want or the concern behind it, a preferred practitioner if they have one, and a preferred day and time of day for a callback. Each lands on the request as a closed-vocabulary field, and every request renders as one readable summary line in the portal and in the owner's text, with the service by name, never by id.

**Architecture:** Three new closed fields on `ItemDraft` and `items` (`returning_client`, `practitioner`, `concern`), each an enum or boolean drawn from the tenant config (`team`, `concerns`), plus a deterministic `summarize_item(item, cfg) -> str` in the runtime used by the SMS builder, the email builder and the internal API (`ItemOut.summary`, `ItemOut.service_name`, `ItemOut.preferred_text`). The prompt gains a qualification step and the clinic's real incentives (new-client credit, free consultation) as offers the assistant may make once it knows the caller is new. The portal's request card shows the summary and the fields in words.

**Tech Stack:** existing runtime (pydantic schema, Alembic, FastAPI internal API, Pipecat tool schemas), portal (Wasp 0.25, typed client regenerated from `docs/contracts/runtime-internal.openapi.json`).

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §3 (ledger), §5 (no free text; fixed wording is config). Reference pages win over this plan where they disagree, except where this plan changes them on purpose (listed in each task).

## Global Constraints

- Everything in `CLAUDE.md` "Non-negotiables", with one deliberate amendment in L1: `ItemDraft` fields become exactly `type, urgency, service_id, contact, preferred_window, health_context, returning_client, practitioner, concern`. Still no free text: `practitioner` and `concern` are enums from the tenant config, `returning_client` is a boolean or null.
- Health stays out of the fields. `concern` is a cosmetic taxonomy (pigmentation, acne, ageing, dryness, hair removal, hair loss, body contouring, skin tightening, tattoo removal, glow, other). Anything medical still goes through the clinical lexicon and the transcript, never a field.
- The summary is composed from fields and fixed labels only, in the runtime, once; the portal and the SMS show the same sentence.
- The qualification step costs at most two extra exchanges on a booking call. The assistant asks once and takes no for an answer.
- Offers are the clinic's own, from the knowledge file: the `$50` first-visit credit on advanced facials and the free virtual consultation. The assistant may mention them to a new client; it never invents a discount.
- Do not restart or touch the running runtime, its `.env`, or its database. Work against scratch test databases; the orchestrator imports the bundle and restarts.

## File Structure

```
runtime/spatalk/tenants/schema.py            TeamMember, team: list[TeamMember]; concerns: list[str] with defaults
runtime/spatalk/brain/ports.py               ItemDraft gains returning_client, practitioner, concern
runtime/spatalk/brain/requests.py            CaptureRequest / BookingLinkRequest carry the three fields
runtime/spatalk/brain/tools.py               tool schemas expose the three fields as enum/boolean
runtime/spatalk/brain/prompt.py              qualification step, offers, preferred day and time question
runtime/spatalk/models.py + alembic 0011     items.returning_client bool null, items.practitioner text null, items.concern text null
runtime/spatalk/ledger/items.py              persist the fields
runtime/spatalk/ledger/summary.py (new)      summarize_item(item, cfg) -> str; preferred_text(window) -> str; service_name(item, cfg) -> str
runtime/spatalk/ledger/delivery.py           SMS/email/Slack builders use summarize_item
runtime/spatalk/http/internal.py             ItemOut gains summary, service_name, preferred_text, returning_client, practitioner, concern
runtime/tenants/skincentrix/tenant.yaml      team (11 names from skincentrix.com), concerns (defaults)
runtime/tests/test_lead_context.py, test_structural_honesty.py (updated field list), test_delivery.py (summary in SMS)
docs/reference/data-model.md, tenant-config.md, api-surface.md; CLAUDE.md non-negotiable 2
portal/src/client/RequestsPage.tsx, formatting.ts (+ tests), src/runtime/client.ts (regenerated)
```

## Task L1: Fields, summary, prompt, delivery

**Files:** everything under `runtime/` in the structure above, `CLAUDE.md`, `docs/reference/{data-model,tenant-config,api-surface}.md`.

**Interfaces (produces):**
- `TeamMember(BaseModel, frozen=True)`: `name: str`, `role: str = ""`. `TenantConfig.team: list[TeamMember] = []`. `TenantConfig.concerns: list[str]` default `["pigmentation", "acne", "ageing", "dryness", "hair removal", "hair loss", "body contouring", "skin tightening", "tattoo removal", "glow", "other"]`.
- `ItemDraft` gains `returning_client: bool | None = None`, `practitioner: str | None = None` (must be a `team[].name` or `"any"`; validated in the ledger, not the model: an unknown name becomes `None` and is logged), `concern: str | None = None` (must be in `cfg.concerns`; otherwise `None`).
- `items` columns `returning_client boolean null`, `practitioner varchar(80) null`, `concern varchar(40) null`; migration `0011_lead_context` with downgrade.
- Tool schemas: `capture_request` and `send_booking_link` accept `returning_client` (boolean), `practitioner` (enum: `["any"] + team names`), `concern` (enum: `cfg.concerns`). All optional. No other new parameters.
- `summarize_item(item, cfg) -> str`, deterministic, one sentence, no free text, for example: `"New booking: Mirapeel facial for pigmentation. New client, no practitioner preference. Callback any day, afternoons."` Rules: `"{Type label}: {service name}"`, `" for {concern}"` when set, `". New client" | ". Returning client" | ""`, `", would like {practitioner}" | ", no practitioner preference" (only when a preference was asked, i.e. the field is `"any"`) | ""`, `". Callback {preferred_text}"` when the item is a booking or callback. `preferred_text(window)`: `"any day"`, `"Thursday"`, `"Thursday afternoon"`, `"mornings"`; never `"any any"`. `service_name(item, cfg)`: the catalog name, or the type label when there is no service.
- SMS builder: the second line becomes the summary (replacing the bare type label), still within the three-segment rule; email and Slack builders show the summary as the first line.
- `ItemOut` gains `summary: str`, `service_name: str | None`, `preferred_text: str`, `returning_client: bool | None`, `practitioner: str | None`, `concern: str | None`. Regenerate `docs/contracts/runtime-internal.openapi.json`.
- Prompt (voice and text): under WHEN THEY WANT TO BOOK, before the name and number: `"Ask whether they have been in to see us before. If they have not: mention the {credit} and the free virtual consultation once, warmly, as options, then ask what they have in mind or what they would like help with. If they have: ask whether there is someone in particular they would like to see, and what they are coming in for."` and for a callback booking: `"Ask which day or time of day suits them best; any is a fine answer."` Fill `returning_client`, `practitioner`, `concern` and `preferred_window` on the tool call from what they said; never guess. The credit and consultation wording come from the knowledge file, not the prompt: the prompt only says to offer "the clinic's new-client offers listed in the facts".
- Skincentrix bundle: `team` with the 11 names from `knowledge.md` (Sabah Shaikh, Amanda Coutts, Faisal Rohile, Anne Perez, Ruru Ahlam, Helen Courbetis, Alexandra Debski, Sanober Ijaz, Mariam Khaizaran, Hala Saeed, Emma Walker) with roles where known; `concerns` left to the default.
- `CLAUDE.md` non-negotiable 2 lists the nine fields and the enum rule; `data-model.md` items table, `tenant-config.md` (`team`, `concerns`), `api-surface.md` (`ItemOut` additions).

**Tests:** `tests/test_lead_context.py`: schema defaults and validation; ItemDraft carries the fields; the ledger stores them and nulls an unknown practitioner or concern; `summarize_item` for a new booking with everything set, a callback with nothing set (`"Callback: Callback requested. Callback any day."` style, no "None", no "any any"), a send-link item, an escalation; `preferred_text` table; tool schema enums equal team names plus any and the concerns list; the prompt contains the qualification step for voice and text; SMS builder second line is the summary and the 459-character rule still holds with a long name; `ItemOut` serialises the new fields. `tests/test_structural_honesty.py`: field list updated to the nine fields (deliberate). `tests/test_qa_gate_a.py` and the promptfoo provider: unchanged unless they pin the field count; if they do, update the pin and note it.

**Done when:** tests pass, migration applies and downgrades, full suite green, ruff clean, contract regenerated, docs updated. Commit `feat(ledger): lead context fields, one-line request summaries, qualification step`.

## Task L2: Portal request cards read like a lead

**Files:** `portal/src/client/RequestsPage.tsx`, `portal/src/client/formatting.ts` (+ `formatting.test.ts`), `portal/src/runtime/client.ts` (regenerated with `npm run gen:client`), `portal/e2e-tests/tests/client.spec.ts` (only if it pins the card layout).

**Interfaces (produces):**
- The request card's title is `summary` from the runtime. Below it, a compact fact list in words: Contact (name and number), Service (by name), Client (New, Returning or blank), Practitioner (name, "No preference", or blank), Concern, Preferred (`preferred_text`), Promised by, State. No raw ids, no `"any any"`, no field shown when empty.
- `formatting.ts`: `clientLabel(returning: boolean | null | undefined) -> "New client" | "Returning client" | ""`, `practitionerLabel(value) -> name | "No preference" | ""`, with unit tests.
- A transcript link on the card (the conversation id is on the item) so a follow-up starts from what was said.

**Tests:** vitest unit tests for the two labels; `wasp build` succeeds in WSL; `wasp test client run` passes.

**Done when:** build and tests pass; screenshot not required. Commit `feat(portal): request cards carry the lead summary and facts in words`.

## Self-review against the spec

- §3 ledger: every request still becomes an item; the summary is derived, not stored, so it cannot drift from the fields.
- §5 no free text: three enums and a boolean; unknown values are nulled, never stored raw. The credit and consultation wording live in the knowledge file, not the prompt.
- Health: the concern list is cosmetic; medical words still route to the clinical script and the transcript.
- Honesty: the assistant asks once and may mention an existing offer; it never promises a price or a booking.
- Type consistency: `TeamMember`, `team`, `concerns`, `returning_client`, `practitioner`, `concern`, `summarize_item`, `preferred_text`, `service_name`, `ItemOut.summary` are used with the same names in both tasks.
