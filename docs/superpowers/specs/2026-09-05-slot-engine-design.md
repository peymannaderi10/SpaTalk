# Slot engine: the runtime owns the booking conversation

Date: 2026-09-05. Status: design approved by the founder in conversation (sections 1–4), written up for review before the implementation plan.

## 1. Why

The order of the booking conversation — been in before, practitioner, treatment, first name, number, preferred time, file — is enforced today by about fifteen prose bullets in the middle of a ~5,400-token system prompt, on every turn, with all five tools always offered. A language model follows a mid-prompt sentence most of the time, not every time. On 2026-09-05 the assistant, on Gemini 3.5 Flash, filed a booking with the practitioner's name in the caller's name field, having never asked for a name; earlier on Flash-Lite it recited the new-client offers without asking. The one hard rule in that flow (a booking is refused without a name, added the same morning) was passed with the wrong name.

Research memo: `docs/research/research-3-deterministic-flows.md` (2026-09-05). Its findings, in short: rule adherence falls as instruction count and prompt length rise; the reliable pattern in Rasa CALM, Pipecat Flows, Vapi and Retell is that the runtime owns the state and the model fills one slot at a time; Pipecat Flows ships inside the Pipecat 1.8.1 pinned here.

The founder's requirement: **hard rules and requirements for every call**, regardless of model, so the cheapest and fastest model can be used.

## 2. Goals and non-goals

Goals
- The order and the wording of every request conversation are decided by the runtime and are the same on every call and every channel.
- No tracked item is ever filed without a first name and a phone number, and no item field ever comes from a model argument.
- A caller's answer can only land in the slot whose question was just asked.
- The model's job shrinks to understanding one answer and phrasing one acknowledgement, so the Lite tier of models is sufficient.

Non-goals
- No change to the rules gate's matching, the guard, the renderer, Tier C's honesty rules, the ledger, delivery, or the portal's request views. The gate's *action* for a non-emergency clinical match changes from "file and speak" to "speak the offer and open the clinical flow"; the emergency action is untouched.
- No retrieval system and no tool-based fact lookup; the facts stay in the static prompt (see the memo's section on cost).
- No feature flag and no second code path: the old prompt-driven flow is removed when this ships.

## 3. Invariants (tests enforce these; they join the CLAUDE.md non-negotiables)

1. `file_request` and `send_link` are absent from the tool list until every required slot for the open flow is filled.
2. An `ItemDraft` is built from the conversation's slot record only. The tool schemas exposed to the model carry no contact, lead, notes or free-text field except the transient `said` / `first_name` / `digits` arguments of the slot tools, which never reach an item except through a resolver.
3. Every closed slot (practitioner, service, window, yes/no) stores a value from the tenant's list or nothing. Matching is code.
4. Every question the caller hears is a tenant script. The model contributes at most one acknowledgement sentence, which passes `guard()`.
5. Business time, structural honesty, fixed wording, provider swappability: unchanged.

## 4. Flows, slots and order

### 4.1 Booking and callback

One question per turn, fixed order. A step already answered (the caller volunteered it, or an earlier step captured it) is skipped. The runtime asks; the model interprets.

| # | Step | Script key | Stored in |
|---|---|---|---|
| 1 | Returning | `ask_returning` | `returning_client` (bool) |
| 2 | Offers, new clients only | `ask_offers`; on yes the offers from the facts, then `ask_after_offers` | — |
| 3 | Practitioner (returning: before treatment; new: after) | `ask_practitioner` | `practitioner` (`team[].name` or `any`) |
| 4 | Treatment | `ask_service`; a kind or an unsure caller gets `ask_service_kind` | `service_id` |
| 5 | Name | `ask_name` | `first_name` |
| 6 | Number | voice: `ask_phone_same`, then `ask_phone` + `confirm_phone` on no; SMS: skipped, sender's number; chat, Instagram, Messenger: `ask_phone` + `confirm_phone` | `phone` |
| 7 | Window | `ask_window` | `preferred_window` |
| 8 | Team note | `ask_team_note`, once; no is fine | transcript only |
| 9 | Route (booking only; callback files directly) | `ask_route` → `send_link` or `file_request`, then the existing outcome script | — |

### 4.2 Other flows on the same engine

- Reschedule, cancel: name → number → (reschedule: window) → file.
- Question for the team: name → number → file.
- Clinical, non-emergency: the rules gate speaks `clinical_offer`. Yes → name → number → filed urgent, then the existing `clinical` outcome script. No → `clinical_declined`.
- Emergency: unchanged — the `emergency` script and an urgent item at once, no slots.
- A flow starts when the model calls `start_request(kind)` from the Q&A state, or when the gate starts the clinical flow.

### 4.3 Rules inside the steps

- Practitioner does not do the treatment (`team[].services`): `practitioner_not_service` → yes: `practitioner_suggest` with the team members who do → no: `practitioner_else`.
- Close match: `confirm_match` ("Did you mean Helen?"); only yes stores it.
- Refuses a name: `ask_name_again` once, then `no_name` and nothing is filed.
- A clinical gate mid-booking: the clinical flow runs; the booking slots are kept; "anything else?" at the end lets the caller return to the open step.
- Changing an earlier answer: the closed tool `change_answer(slot)` reopens that step.
- A side question at any step: the model answers from the facts in words; the runtime then re-asks the open question.

## 5. Matching and confirmation

Resolvers live in `spatalk/brain/resolve.py`, pure functions over the tenant config.

Order: normalise (case, punctuation, "with", "Dr.") → exact match on full or first name / service name → phonetic match on first names (Double Metaphone) → fuzzy similarity (rapidfuzz `WRatio`, 0–1).

| Result | Action |
|---|---|
| Exact, or ≥ 0.90 | Stored, no confirmation. |
| 0.60 – 0.90 | `confirm_match`; yes stores, no re-asks the step. |
| < 0.60 | The step's re-ask script (`ask_practitioner_again`, `ask_service_again`). |
| Two misses | Practitioner: `practitioner_any`, store `any`. Treatment: `ask_service_kind`. |
| Two list entries match equally | `confirm_which` ("Did you mean Amanda C. or Amanda K.?"). |

Kinds: services already carry `category` (consultation, facial, …). A `said` that matches a category rather than a service is a kind, which triggers `ask_service_kind`. The consultation named in that script is the tenant's service with `category: consultation`; without one, the line falls back to "the team can help you pick when they call".

Name sanity: if `first_name` phonetically matches the practitioner just chosen, `confirm_name_staff` once; yes stores. Any other name is stored as given.

Phone: the model passes the digits it heard; the runtime normalises to E.164 with a Canadian default, rejects anything that is not ten digits after the country code, and reads back in groups of three-three-four (`confirm_phone`). Yes stores; no re-asks; two misses on a call → `phone_fallback` and the caller id.

Yes/no steps take `answer(yes | no | unsure)`. Unsure on "been in before" is treated as new. Anything that is not an answer to the open question is a side question.

Preferred window keeps `PreferredWindow` (an ISO date, a weekday or `any`; a part of day or `any`).

Dependencies: `rapidfuzz` and `metaphone` (both permissive, no service behind them).

## 6. Architecture

### 6.1 `spatalk/brain/flow.py` (pure, no I/O)

- `Slots` (pydantic, frozen, JSON-serialisable): `flow` (`new_booking | callback | reschedule | cancel | question | clinical | None`), the slot values (`returning_client`, `offers_heard`, `practitioner`, `service_id`, `first_name`, `phone`, `phone_confirmed`, `preferred_window`, `team_note_asked`), `pending` (a confirmation awaiting yes/no: kind, candidate value, the slot it belongs to), and per-slot miss counters.
- `next_step(slots, cfg, channel) -> Step`: the fixed order above. `Step` is an enum: `QA, RETURNING, OFFERS, PRACTITIONER, SERVICE, NAME, PHONE, WINDOW, TEAM_NOTE, ROUTE, COMPLETE`.
- `step_question(step, slots, cfg, channel) -> (script_key, fills)`.
- `step_tools(step, slots, cfg, channel) -> list[FunctionSchema]`: the slot tool for the step, plus `answer` when a confirmation is pending, plus `escalate`, `end_conversation`, `change_answer`, and `transfer_to_human` where enabled; `file_request` and `send_link` only at `ROUTE`/`COMPLETE`.
- `apply(slots, tool_call, cfg, channel) -> Applied(slots, say: list[(script_key, fills)])`: runs the resolver and returns the new record and the fixed lines to speak.
- `draft_from(slots, flow, cfg) -> ItemDraft`: the only constructor of an `ItemDraft` in the request path.

### 6.2 Tools (closed; `tools.py`)

| Tool | Arguments | Where offered |
|---|---|---|
| `start_request` | `kind` enum | `QA` |
| `answer` | `value: yes/no/unsure` | yes/no steps and pending confirmations |
| `choose_practitioner` | `said: string` | `PRACTITIONER` |
| `choose_service` | `said: string` | `SERVICE` |
| `give_name` | `first_name: string` | `NAME` |
| `give_phone` | `digits: string` | `PHONE` |
| `choose_window` | `date`, `part_of_day` (closed) | `WINDOW` |
| `change_answer` | `slot` enum | every step after `QA` |
| `file_request` | none | `COMPLETE` (and `ROUTE` for the call-me option) |
| `send_link` | none | `ROUTE`, when the tenant has an SMS number and the phone is confirmed |
| `escalate`, `end_conversation`, `transfer_to_human` | as today | every step |

Removed: `capture_request`, `request_appointment_change`, `send_booking_link` and their `contact` / lead arguments. Each tool description ends with "only what the caller said in answer to the question just asked".

### 6.3 Storage

`conversations.flow` JSONB, nullable — the serialised `Slots`. Alembic migration `0013_flow_slots`. Written after every turn on both channels; a dropped call or a text thread resumed within its 24-hour window picks up at the open step. `docs/reference/data-model.md` gains the column.

### 6.4 Text adapter (`Brain.turn`, `text/service.py`)

Per turn: rules gate as today → load `Slots` → model call with the static prompt (persona, style, facts, hours; the "WHEN THEY WANT TO BOOK" block and the name/number bullets removed), the history, a one-to-three-sentence step message as the final instruction ("Known: returning client, wants to see Helen. Open: which treatment. Use `choose_service` with what they say. Ask nothing yourself."), and `step_tools` → any tool call goes through `apply` → the guard runs on the model's text → reply = at most one acknowledgement sentence from the model + the fixed lines from `apply` + the next step's question. `file_request` → `caps.capture(ref, draft_from(slots))`.

### 6.5 Voice adapter (`voice/pipeline.py`, `voice/handlers.py`)

Pipecat Flows (`pipecat.flows.FlowManager`, in Pipecat 1.8.1) with node configs generated from the same table: role message = static prompt, task message = step message, functions = the step tools wrapped as `FlowsFunctionSchema`, handlers call `apply` and return the next node. Fixed questions and lines are spoken with `TTSSpeakFrame` as outcome scripts are today. `RulesGateProcessor`, `FillerProcessor` and `OutputGuardProcessor` stay in place. Day-one check: `FlowManager` is typed for a plain LLM service and SpaTalk's LLM stage is the failover `LLMRouter`; if the manager cannot drive it, a small processor of our own reuses Flows' four-frame sequence (`LLMUpdateSettingsFrame`, `LLMMessagesAppendFrame`, `LLMSetToolsFrame`, `LLMRunFrame`).

### 6.6 Prompt

`build_system_prompt` keeps persona, tone, general style, the Q&A rules, services, facts and hours. It loses the booking-order bullets, the offers bullets and the name/number bullets. The per-turn step message replaces them. Target: the static prompt shrinks by roughly 1,500 tokens and the tool schemas by roughly 1,200.

### 6.7 Config additions (bundle first; portal editing is a follow-up)

- `scripts.yaml`: the keys in section 7.
- `services.yaml`: `category` already exists and is used as the kind.
- `tenant.yaml` `team[]`: `services: [service_id, …]`; empty or absent means every service.

### 6.8 When something goes wrong

- Model outage: the existing failover and `model_unavailable` script.
- A tool call with bad arguments or a tool not offered at this step: ignored, logged, the open question re-asked; no refusal is spoken.
- Ledger or SMS failure at filing: the existing `refuse_unavailable` path; nothing is claimed.
- Guard blocks the model's acknowledgement: the fixed question is spoken alone.

## 7. Scripts (founder to review every line)

New keys, with the default wording that goes into `spatalk/tenants/schema.py`, `tenants/skincentrix/scripts.yaml` and `docs/reference/tenant-config.md`. Fills in braces.

| Key | Wording |
|---|---|
| `ask_returning` | Have you been in to see us before? |
| `ask_offers` | Would you like to hear our new-client offers? |
| `ask_after_offers` | What did you have in mind? |
| `ask_practitioner` | Is there someone in particular you'd like to see, or whoever's available? |
| `ask_practitioner_again` | Sorry, who would you like to see? Anyone's fine too. |
| `practitioner_any` | No problem, I'll leave it as whoever's available. |
| `practitioner_not_service` | Unfortunately {practitioner} doesn't do {service}. I can suggest someone, if you don't have anyone else in mind? |
| `practitioner_suggest` | {names} can do {service}. Would one of them work? |
| `practitioner_else` | Who else did you have in mind? |
| `ask_service` | What would you like to come in for? |
| `ask_service_kind` | I can run through two or three options, or {consultation} can help you pick — which would you prefer? |
| `ask_service_again` | Sorry, which treatment did you have in mind? |
| `confirm_match` | Did you mean {value}? |
| `confirm_which` | Did you mean {first} or {second}? |
| `ask_name` | Could I get your first name? |
| `ask_name_again` | Just a first name is fine — it's so the team knows who to ask for. |
| `no_name` | No problem — you can reach the clinic at {phone} during opening hours. Is there anything else I can help with? |
| `confirm_name_staff` | Just to check, your first name is {name} as well? |
| `ask_phone_same` | Is the number you're calling from the best one to reach you on? |
| `ask_phone` | What's the best number to reach you on? |
| `confirm_phone` | That's {digits} — is that right? |
| `phone_fallback` | No problem, I'll use the number you're calling from. |
| `ask_window` | Which day or time of day suits you best for the visit? Any is fine. |
| `ask_team_note` | Is there anything you'd like the team to know before they call? |
| `ask_route` | I can text you the booking link now, or have the team call you to book — which do you prefer? |
| `clinical_offer` | That's one for our clinical team rather than me — would you like me to have them reach out to you? |
| `clinical_declined` | No problem. Is there anything else I can help with? |
| `clinical` (changed) | I've passed that to our clinical team as an urgent request, and someone will call you back at this number as soon as possible. Is there anything else I can help with? |
| `clinical_text` (changed) | I've passed that to our clinical team as an urgent request; someone will call you as soon as possible. Anything else I can help with? |

`clinical` and `clinical_text` lose their opening sentence because `clinical_offer` now says it first. Unchanged: `captured`, `link_sent`, `emergency`, `emergency_text`, `goodbye` and every other existing key. `refuse_no_name` and `refuse_no_contact` remain as the last-line refusals in Tier C, which the engine makes unreachable in practice. On text channels `confirm_phone` reads the digits as typed rather than in spoken groups.

## 8. Testing

- Flow tables: every flow × every step; skipping answered steps; two-miss rules; `change_answer`; the clinical flow interrupting a booking; the channel differences at the number step.
- Resolvers: Ellen→Helen, Hydroabrasion→Hydrabrasion, "a facial" → kind, two team members with one first name, threshold edges, phone numbers with and without the leading 1, junk digits.
- Structural honesty (`tests/test_structural_honesty.py` grows): tools absent until slots are filled; `ItemDraft` only from `draft_from`; no contact, lead, notes or free-text field on any tool schema except the three transient arguments; the acknowledgement passes the guard.
- Scripted conversations with `FakeLLM` per flow on SMS and chat, including: the model tries to file early (nothing happens, question re-asked); the model fills a slot with a guess (rejected by the resolver); a side question mid-flow.
- Voice: processor tests for the Flows wiring; then the founder's call-test checklist — new client yes to offers / no to offers; returning with Helen; "a facial" and unsure; Ellen/Helen; a different number; refuses a name; clinical question mid-booking; an emergency phrase.
- promptfoo: one scenario per step on the new flow, run once (paid, at the QA gate) on Gemini 3.5 Flash-Lite, Gemini 3.1 Flash-Lite and gpt-4.1-nano. The winner on pass rate and latency becomes `LLM_MODEL`, as its own change.
- Reference docs: `tenant-config.md` (scripts, `team[].services`), `data-model.md` (`conversations.flow`), `api-surface.md` if the tool list is documented there.

## 9. Rollout

1. Branch `slot-engine`. Order: `flow.py` + `resolve.py` + scripts and schema (2 days) → text adapter + migration + `Brain` tests (1.5 days) → voice adapter + call tests (2 days) → QA gate, shootout, founder call tests (1 day). About seven engineer-days; two to three calendar days with agents on the independent parts.
2. Bundle v23 carries the new scripts and `team[].services`.
3. Go-live: one bundle import and one runtime restart. Rollback: revert the merge and the runtime's existing config rollback.
4. Done means: zero items without a first name and a number (a query, in the suite and on the live database after the call tests); every call on the checklist follows section 4 with section 7 wording; turn latency no worse than today's p95 (about 1.2–1.5 s); promptfoo pass rate at least today's gate on the cheapest model that clears it.

## 10. Risks

- `FlowManager` and the failover router may not compose; the fallback is the four-frame processor (section 6.5).
- Swapping the tool list per step may reduce Gemini's implicit cache hits; the static prompt stays identical turn to turn to keep the cached prefix, and the QA run measures it.
- The phonetic and fuzzy thresholds are starting points from one published production write-up; the call tests tune them.
- In the first version each turn fills one slot, so a caller who volunteers several answers in one breath ("it's Dana, I want a facial with Helen next Tuesday") is still asked the other questions. A later version may offer the next two slot tools together.

## 11. Follow-ups, out of this spec

- Portal setup page: edit service `category`, `team[].services` and the FAQ rows (the FAQ is its own item).
- Model switch to Gemini 3.1 Flash-Lite after the shootout.
- Rotate the provider keys that were pasted in chat.
