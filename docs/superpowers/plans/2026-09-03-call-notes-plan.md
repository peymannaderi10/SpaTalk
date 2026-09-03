# Call Notes Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Tests first (write the test, see it fail, make it pass, commit). Read `CLAUDE.md`, spec §3, §5 and §7.4, `docs/reference/data-model.md` and `docs/reference/tenant-config.md` first. Status: **drafted 2026-09-03 after the founder's 16:09 call, awaiting the founder's yes.** It amends the reading of `CLAUDE.md` non-negotiable 2 as stated under Global Constraints, and that amendment needs the founder's explicit decision before any code is written.

**Goal:** When a request card is opened, the person following it up reads a short set of notes about the call before they dial: what the caller wants, what they are hoping to get out of it, anything they asked the team to know. Today the card carries a one-line summary composed from closed fields and a link to the transcript; nothing tells staff *why* the caller rang in the caller's own terms. The founder's words: "a mini pre-consultation to get some notes to help the practitioner easily know what is going on."

**Architecture:** Two additions. (1) The assistant asks one more question before it files a booking or callback: whether there is anything the caller would like the team to know before they call, and it takes no for an answer. (2) A post-conversation job drafts **notes** from the stored transcript with a model, stores them on the **conversation** (never on the item), and the portal card, the staff email and the Slack post show them under the label *"AI notes, drafted from the transcript."* The item's fields stay exactly the nine closed fields. The notes live and die with the transcript under the tenant's retention, are never spoken or sent to the caller, and never re-enter a model's context on a later turn.

**Tech Stack:** existing runtime (jobs table and scheduler, `LLMClient` through `make_llm`, Alembic, FastAPI internal API), portal (Wasp 0.25, typed client regenerated from `docs/contracts/runtime-internal.openapi.json`).

**Spec:** §3 (the ledger is the product), §5 (structural honesty; fixed wording is config), §7.4 (data minimisation is schema, not prompt; transcripts are the honest limit). Reference pages win over this plan where they disagree, except where this plan changes them on purpose (listed per task).

## Why this is allowed and where the line is

Non-negotiable 2 says no free text on tracked items, and the spec's reason is that the item is the record staff act on and the model must have nowhere to put a symptom. This plan keeps both: `items` gains no column, the tool schemas gain no notes parameter, and `summarize_item` stays derived from closed fields. The notes are a **derived view of the transcript**, stored next to it on `conversations`, with the transcript's retention and the transcript's audit (reading a card with notes is a `read_transcript` audit row). Staff already read the transcript for the detail; the notes are the same detail, shorter, and labelled as drafted.

The health line holds. The assistant still never asks about a condition. If the caller volunteers one, the health-context lexicon flags the conversation as today, and the notes job replaces any sentence that matches the health-context or clinical lexicon with the fixed line from `scripts.notes_health_line` ("Caller mentioned a health matter; read the transcript before calling."). So the notes can say *"Wants help with dark spots on the cheeks before a wedding in November"* and cannot say *"is on isotretinoin"*.

## Global Constraints

- Everything in `CLAUDE.md` "Non-negotiables", read with this plan's one clarification: free text drafted by a model may be stored **on a conversation** as `conversations.notes`, labelled, retained with the transcript, never on an item, never in a tool schema, never spoken, never sent to the caller, never fed back into a model on a later turn. Task N1 adds this sentence to non-negotiable 2.
- The notes are grounded or they are not stored. The drafting prompt allows only what the caller said or asked; no inference, no advice, no adjectives about the caller, no mention of price or availability. The job runs a deterministic check after the model: every sentence must share at least three content words with the transcript's user turns, or it is dropped. An empty result stores `NULL`, never a placeholder.
- One extra exchange on the call, asked once, no for an answer. The question is cosmetic and goal-shaped; it never invites a medical history.
- Fixed wording is config: the question is in the prompt as an instruction, not a script; the health line and the label are scripts.
- Do not restart or touch the running runtime, its `.env`, or its database. Work against scratch test databases; the orchestrator imports the bundle and restarts.

## File Structure

```
runtime/spatalk/brain/prompt.py                     "anything you'd like the team to know" step in WHEN THEY WANT TO BOOK
runtime/spatalk/tenants/schema.py                   Scripts.notes_health_line, Scripts.notes_label; TenantConfig.call_notes: bool = True
runtime/spatalk/models.py + alembic 0012_call_notes  conversations.notes text null, notes_model text null, notes_at timestamptz null
runtime/spatalk/ledger/notes.py (new)               draft_notes(messages, cfg, llm) -> str | None; ground(notes, user_turns) -> str | None; scrub_health(notes, cfg) -> str
runtime/spatalk/jobs.py                             kind "call_notes": queued by end_conversation (voice) and close (text); idempotent per conversation
runtime/spatalk/ledger/conversations.py             set_notes(sf, conversation_id, notes, model, at); notes cleared by the retention job with the messages
runtime/spatalk/ledger/delivery.py                  email and Slack builders append the notes block; SMS and WhatsApp unchanged (segment budget)
runtime/spatalk/http/internal.py                    ConversationOut.notes/notes_at; ItemOut.notes (joined, read-only) so the card needs one call
runtime/tenants/skincentrix/scripts.yaml            notes_health_line, notes_label
runtime/tests/test_call_notes.py, test_structural_honesty.py (notes never in a tool schema, never in TTS, never in the prompt), test_retention.py (notes deleted with messages)
docs/reference/data-model.md, tenant-config.md, api-surface.md; CLAUDE.md non-negotiable 2 (the clarification sentence)
portal/src/client/RequestsPage.tsx, ConversationsPage.tsx (notes block with the label), src/runtime/client.ts (regenerated)
docs/research/rates.json + costmodel.py (one drafting call per conversation, about 2,000 input and 150 output tokens)
```

## Task N1: The question, the job, the storage, the delivery

**Files:** everything under `runtime/` in the structure above, `CLAUDE.md`, the three reference pages.

**Interfaces (produces):**
- `Scripts.notes_health_line: str = "Caller mentioned a health matter; read the transcript before calling."`, `Scripts.notes_label: str = "AI notes, drafted from the transcript"`. `TenantConfig.call_notes: bool = True` (a tenant can switch the job off; the question is still asked, because the transcript still holds the answer).
- Prompt, under WHEN THEY WANT TO BOOK, after the name and number and before the tool call: *"Ask once whether there is anything they would like the team to know before they call, such as what they are hoping to get out of the visit; take no for an answer, never ask about conditions, medications or a history, and do not repeat their answer back."* Test: present on voice and text channels; the words "condition", "medication" appear only in the never-ask clause.
- `conversations.notes text null`, `notes_model text null`, `notes_at timestamptz null`; migration `0012_call_notes` with downgrade. No change to `items`.
- `draft_notes(messages: list[Message], cfg: TenantConfig, llm: LLMClient) -> str | None`: a fixed drafting prompt (in code, since it is an instruction to a model and not wording a caller hears) that asks for at most four plain sentences in the third person about what the caller wants, what they hope to get out of it and anything they asked the team to know; nothing else. Runs `ground()` then `scrub_health()`. Returns `None` for an empty or fully dropped result, and for a conversation with no user turns.
- `ground(notes: str, user_turns: list[str]) -> str | None`: keeps a sentence only if at least three of its content words (four letters or more, not in a small stop list) occur in the user turns; returns `None` when nothing survives.
- `scrub_health(notes: str, cfg: TenantConfig) -> str`: any sentence that `health_context_mentioned` or the clinical lexicon matches is replaced by `cfg.scripts.notes_health_line`, once, in place of the first such sentence; later matches are dropped.
- Job `call_notes` with payload `{conversation_id}`: queued by `end_conversation` for voice and by the text-channel close for SMS, chat and Instagram when `cfg.call_notes` is true; skipped when the conversation already has `notes_at`; the model is `make_llm(settings)` (the same provider switch as the rest); one attempt and a dead-letter on failure, never a retry storm; `notes_model` records the model name. Cost recorded as `usage_events` kind `llm_input_tokens`/`llm_output_tokens` with `channel` of the conversation.
- Retention: the nightly job that deletes messages past `retention_days` also nulls `notes`, `notes_model`, `notes_at` on the same conversations, and the deletion receipt counts them.
- Delivery: the email and Slack builders add, after the summary and facts, a block headed by `cfg.scripts.notes_label` with the notes, only when the notes exist at send time (they usually will not for the immediate alert; the digest and the portal are where notes are read). SMS and WhatsApp unchanged.
- `ConversationOut` gains `notes: str | None`, `notes_at: datetime | None`; `ItemOut` gains `notes: str | None` (read from the item's conversation). Reading an item list does not write an audit row; opening a conversation still does. Regenerate `docs/contracts/runtime-internal.openapi.json`.
- `CLAUDE.md` non-negotiable 2 gains: *"Model-drafted notes exist only as `conversations.notes`: labelled, retained with the transcript, never on an item, never in a tool schema, never spoken, never sent to the caller, never fed back to a model."* `data-model.md` (conversations columns, the derived-summary paragraph gains one sentence), `tenant-config.md` (`call_notes`, the two scripts), `api-surface.md` (the two outputs).

**Tests:** `tests/test_call_notes.py`: the prompt asks the question once on every channel and never asks about conditions; `ground` drops an invented sentence and keeps a grounded one; `scrub_health` replaces a sentence about a medication with the fixed line and drops a second one; `draft_notes` with `FakeLLM` returns `None` for an empty transcript and a grounded string otherwise; the job stores notes once and is a no-op the second time; the job is not queued when `call_notes` is false; the email carries the block only when notes exist; retention nulls the columns and counts them; `ItemOut.notes` serialises. `tests/test_structural_honesty.py`: no tool schema has a `notes` parameter (already true, keep), the notes never appear in `build_system_prompt` output for a later turn, the notes never pass through `OutputGuardProcessor` or a `TTSSpeakFrame`. `tests/test_retention.py`: extended, not weakened.

**Done when:** tests pass, migration applies and downgrades, full suite green, ruff clean, contract regenerated, docs updated. Commit `feat(ledger): call notes drafted from the transcript, stored on the conversation, asked for once`.

## Task N2: The portal shows the notes where staff act

**Files:** `portal/src/client/RequestsPage.tsx`, `ConversationsPage.tsx`, `src/runtime/client.ts` (regenerated with `npm run gen:client`), `formatting.ts` (+ tests) if a helper is needed, `e2e-tests/tests/client.spec.ts` only if it pins the card layout.

**Interfaces (produces):**
- On the request card, under the summary and the fact list: a paragraph with the notes, preceded by the label from the runtime (`notes_label` travels in `ItemOut` or is fetched with the tenant settings; either is fine, but it is the tenant's wording, not the portal's). No paragraph when `notes` is null. The transcript button stays.
- On the conversation page, the same block above the messages.
- A `data-testid="request-notes"` on the paragraph.

**Tests:** `wasp test client run` passes; a unit test for any formatting helper; `wasp build` succeeds in WSL (never while the founder's dev server runs).

**Done when:** build and tests pass. Commit `feat(portal): call notes on the request card and the conversation page`.

## Self-review against the spec

- §3 ledger: items unchanged; the notes are attached to the conversation the item already links to.
- §5 honesty: nothing about the notes is spoken; the caller never hears "I've noted that"; the tool schemas do not change; the guard and renderer are untouched.
- §7.4 minimisation: the model still has nowhere to put a symptom on an item; the notes are transcript-derived, health-scrubbed, retention-bound and labelled. The honest limit the spec already states for transcripts now covers the notes too, and the onboarding wording for a PHIPA custodian should say so.
- Cost: one short model call per conversation; add it to the cost model rather than absorb it silently.
- Founder decision needed: the clarification to non-negotiable 2, and whether SMS alerts should wait for the notes (this plan says no: the alert goes now, the notes follow in the portal within a minute).
