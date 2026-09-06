# Deterministic booking flow for SpaTalk: research memo

Date: 2026-09-05. Read-only research; nothing in the repo was changed.

## 0. What the code does today (measured)

- Voice system prompt for Skincentrix: 21,501 chars, ~5,400 tokens; tool schemas ~1,700 tokens (measured with `build_system_prompt` / `to_genai_declarations` on the live bundle). `rates.json` budgets 5,000 cached + 600 uncached input tokens per turn, so ~190k input tokens per 30-turn call is the expected number, not a leak.
- The booking sequence lives in ~15 prose bullets under "WHEN THEY WANT TO BOOK", positioned in the middle of the prompt, after ~20 other rules and before 42 services plus the knowledge text.
- All five tools are exposed on every turn (`tools.py`, set once per call in `LLMContext(tools=...)`). `capture_request` accepts `contact.name` as a free string; the only structural check is `TierCCapabilities.capture` refusing a booking with no name. Today's failure (practitioner's name in the name field) passes that check.
- Pipecat 1.8.1 already contains Pipecat Flows: `pipecat.flows.FlowManager` (merged from the standalone repo at pipecat 1.5.0). `FlowManager(llm=..., context_aggregator=..., worker=PipelineWorker)`; per node it pushes `LLMUpdateSettingsFrame(system_instruction=role_message)`, `LLMMessagesAppendFrame(task_messages)` (or `LLMMessagesUpdateFrame` under RESET), `LLMSetToolsFrame(tools)`, then `LLMRunFrame`. All of these are handled by `LLMContextAggregatorPair` (`llm_response_universal.py` lines 826-832), so it composes with the pair already in `pipeline.py`. Handlers return `(result, next_node)`; the manager registers them through `llm.register_function`, which `LLMRouter` proxies to both vendors.
- Forced tool calls: `LLMContext.tool_choice` exists (OpenAI-shaped) but `GoogleLLMService` only reads `tool_config` from its constructor (`llm.py` lines 214, 532-540), so on Gemini it is static per service, not per turn. The text path (`GeminiClient.complete`) calls google-genai directly and can pass a per-turn `tool_config` trivially.

## 1. The options

### A. More rules in the prompt (status quo)
Rejected on evidence (section 4). Each added rule dilutes the others; the models are already at the point where a mid-prompt rule is followed "some of the time".

### B. Post-hoc validation only
Keep one prompt; harden `dispatch_tool`/Tier C: refuse a booking whose `contact.name` fuzzy-matches a `team[].name` when the practitioner slot names the same person; refuse when required lead fields are missing; the existing `refuse_no_name` script re-asks. Half a day. Catches today's bug, does not stop the model skipping the phone confirmation or the preferred window, and every refusal costs the caller a re-ask. Worth shipping now as a stopgap, not as the fix.

### C. Runtime slot ledger, state-scoped tools, per-state task message (recommended)
The runtime owns a `BookingSlots` record and a pure `next_step(slots, channel)` function. The model does two things only: fill one slot at a time through small closed tools, and phrase the question the runtime tells it to ask. `capture_request` is not in the tool list until every required slot is filled, and the item is built from the runtime's slots, never from tool arguments. This is Rasa CALM's design (flows own the business logic; the LLM emits `SetSlot`/`StartFlow` commands) and Pipecat Flows' design (a node "focuses the LLM on a single task with only the tools it needs"), implemented as one small module and consumed by both drivers.

Per-state prompt size: Pipecat's own `NodeConfig` example is `"Ask the user for their name..."`; Vapi's guidance for a node is "a focused prompt (1-3 goals max)". A SpaTalk step message would be 1-3 sentences, e.g. `The caller has chosen Hydrafacial. Ask for their first name and whether the number they are calling from is the best one to reach them, in one question. Call give_name when they answer.` with tools `[give_name, escalate, end_conversation]`.

What it replaces: the "WHEN THEY WANT TO BOOK" block and the name/number bullets in `prompt.py`; the `contact`/lead arguments on `capture_request` and `send_booking_link` in `tools.py`; nothing in `rules.py`, `guard.py`, `renderer.py`, `tier_c.py` or the scripts. `driver.py`'s `Brain.turn` stays the text driver and gains a flow step; `pipeline.py` gains a `FlowManager` whose nodes are generated from the same table.

### D. Pipecat Flows alone
Same mechanics for voice, but `FlowManager` needs a `PipelineWorker`, so it cannot drive `Brain.turn` for SMS/chat/Instagram. Used alone it means two hand-written copies of the flow. Used as the voice adapter of C, it is the right tool: the frame choreography is exactly what a custom processor would have to reproduce.

### E. Forced extraction call per turn
Gemini `tool_config=ToolConfig(function_calling_config=FunctionCallingConfig(mode="ANY", allowed_function_names=[...]))`: "constrained to always predict a function call and ensures function schema adherence"; `VALIDATED` (default when tools are combined with structured output on Gemini 3) constrains to "either function calls or natural language, and ensures function schema adherence". OpenAI: `tool_choice: "required"` or `{"type":"function","name":...}`, `strict: true` ("reliably adhere to the function schema, instead of being best effort"), `parallel_tool_calls: false`. Reliable for *shape*; it does not fix *meaning* (today's bug was a well-formed call with the wrong value). As a separate pre-call it adds a full model round trip to every turn (section 3). Use it where a turn is not on the voice critical path: the text channels, the nightly judge, and optionally a background re-check that runs under the filler.

### F. Rasa CALM, LangGraph, hosted builders
Rasa Pro is a licensed server, a product-sized stack (CLAUDE.md "must not"). LangGraph is a dependency for a graph of eight states whose nodes are request/response, not streaming frame processors; it would sit beside Pipecat, not inside it. Retell's "Extract Dynamic Variable" node (Text/Number/Enum/Boolean) and Vapi Workflows (AI-judged or logical edge conditions) confirm the pattern but are hosted. Copy the patterns, not the products.

### G. Facts through tools or retrieval
Not now. The 42 services and the knowledge text are needed in the Q&A state, which is most turns; a `lookup_service(id)` tool turns a one-round-trip price answer into two. On 3.5 Flash-Lite the whole ~7k-token static prefix costs $0.0021 per turn uncached and $0.0002 cached; on 3.5 Flash $0.0105 / $0.001. Explicit caching (min 4,096 tokens on 3.5 Flash, default TTL 1 hour, storage $1.00 per M tokens per hour, so a 7k-token cache kept warm all day is about $0.17) pays only on 3.5 Flash and only at volume; Pipecat's `GoogleLLMService` does not pass `cached_content`, so it needs a subclass. Option C helps caching for free: the static persona+facts prompt becomes `role_message` (system instruction, unchanged all call) and the per-state text travels as conversation messages, so the cached prefix stays identical turn to turn. One caveat to measure: swapping the tool list per state changes the request config and may reduce implicit cache hits.

## 2. Recommended architecture

**`spatalk/brain/flow.py`** (pure, no I/O, table-driven tests):
- `BookingSlots` (pydantic, frozen): `returning_client: bool|None`, `practitioner: str|None` (a `team[].name` or "any"), `service_id`, `concern`, `first_name`, `phone_confirmed: bool|None`, `alt_phone`, `preferred_window`, `team_note_asked: bool`.
- `Step` enum: `QA, RETURNING, PRACTITIONER, SERVICE, NAME_PHONE, WINDOW, TEAM_NOTE, ROUTE, DONE`. `next_step(slots, channel)` is a fixed function; on SMS `NAME_PHONE` asks the name only.
- `step_message(step, slots, cfg, channel) -> str`: 1-3 sentences, code-owned wording for *questions*; every outcome/refusal/confirmation sentence stays in `scripts.yaml` (add `confirm_practitioner`, `confirm_service`, `confirm_name`).
- `step_tools(step, cfg) -> list[FunctionSchema]`: the slot tool for that step plus `escalate`, `end_conversation` (and `transfer_to_human` when enabled). `file_request()` takes no arguments and exists only in `ROUTE`; `send_booking_link(service_id)` likewise. `ItemDraft` is built from `BookingSlots`, so the closed-field rule is enforced by construction, and Tier C still never sees `Completed`.
- Resolvers: `resolve_practitioner(text, cfg)`, `resolve_service`, `resolve_concern`: normalise, exact match, then Double Metaphone (jellyfish) on first names, then rapidfuzz `WRatio`. Thresholds from ML6's production write-up (96% accuracy at a 0.85 similarity threshold, 0.2-0.5 ms per match): >=0.90 accept and echo (`confirm_practitioner` script with the resolved name), 0.60-0.90 ask "Did you mean Helen?", below re-ask. Store only the list value; the ledger's existing null-and-log rule stays as the last gate. Name sanity: if `first_name` phonetically matches a `team[].name`, ask `confirm_name` once before accepting.

**Text adapter** (`driver.py`): `Brain.turn` loads `BookingSlots` from the conversation (new JSONB column, Alembic), runs the rules gate as today, then calls the LLM with the static prompt, the history, `step_message` as the last system/developer message, and `step_tools`. Slot tool calls update the record; only `file_request` reaches `caps.capture`. `guard()` unchanged. On text, a forced-call pre-step (Gemini ANY, OpenAI required) is affordable and can be tried behind a setting.

**Voice adapter** (`pipeline.py`, `handlers.py`): generate `NodeConfig`s from the same table: `role_message` = static prompt, `task_messages` = `step_message`, `functions` = `FlowsFunctionSchema`s wrapping the same handlers, handlers return `(result, next_node)`; outcome scripts still spoken with `TTSSpeakFrame` as in `handlers.py`. `FlowManager(llm=llm_stage(...), context_aggregator=pair, worker=worker)`. Keep `RulesGateProcessor`, `FillerProcessor`, `OutputGuardProcessor` where they are.

**Migration and effort**
1. Stopgap validation (option B): 0.5 day, ship today.
2. `flow.py` + resolvers + tests + scripts: 2 days.
3. Text adapter, migration, `Brain` tests with `FakeLLM`: 1.5 days.
4. Voice adapter with `FlowManager`, `LLMRouter` compatibility check, call tests: 2 days. Risk: `FlowManager` type-hints `llm: LLMService | LLMSwitcher` and may touch adapter methods `LLMRouter` lacks; if so, register handlers directly and reuse only the four-frame choreography (~60 lines).
5. promptfoo scenarios per step, one paid QA run, founder call test: 1 day.
Total about 7 engineer-days plus a call-test day. Old prompt path can stay behind a tenant flag for one release.

## 3. Cost and latency numbers found

- Gemini 3.5 Flash: $1.50 in / $9.00 out per M; cached $0.15; storage $1.00 per M tokens per hour. 3.5 Flash-Lite: $0.30 / $2.50; cached $0.03. 2.5 Flash: $0.30 / $2.50; cached $0.03. 2.5 Flash-Lite: $0.10 / $0.40; cached $0.01.
- Explicit/implicit caching minimum: 4,096 tokens for 3.5-3.8 Flash, 2,048 for 2.5 Flash/Pro; Flash-Lite not in the table (a forum thread says the table is inconsistent; Firebase docs say 1,024 for Flash models). Default explicit TTL 1 hour.
- Latency: 2.5 Flash-Lite time-to-first-token 0.29 s and 301 tokens/s (Artificial Analysis, Google API). In this pipeline, `processors.py` records ~0.7 s to first token and `llm_router.py` counts a second sequential model call as "about a second". A forced pre-extraction call therefore costs roughly +0.5-1.0 s per voice turn, which is why it is not on the voice critical path in the recommendation. Per-state prompts shrink prefill by ~1.5k rule tokens and ~1.2k tool tokens, a small TTFT gain.
- Money is not the argument: a 30-turn call's input tokens cost about $0.05 on 3.5 Flash-Lite uncached; the fix is for adherence.
- Function-calling evals: the BFCL table is rendered client-side and the mirror refused the fetch; the one figure retrieved is Gemini 3.1 Flash-Lite Preview at 76.5% on BFCL v3 (June 2026 snapshot). DeepMind's 3.5 Flash-Lite card lists agentic scores (Terminal-bench 2.1 54.0%, OSWorld 74.0%) but no BFCL. Treat forced-call reliability on 3.5 Flash-Lite as unmeasured; it is the QA gate's job.

## 4. Evidence on prompt length and instruction following

- IFScale (Jaroslawicz et al., arXiv 2507.11538): adherence degrades as instruction density rises; best models reach only 68% at 500 instructions; a bias towards earlier instructions; gemini-2.5-pro shows threshold decay, gpt-4.1 linear decay.
- Lost in the Middle (Liu et al., arXiv 2307.03172): accuracy drops by more than 30% when the relevant content sits mid-context; U-shaped across six model families. SpaTalk's booking rules sit mid-prompt.
- LLMs Get Lost in Multi-Turn Conversation (Laban et al., arXiv 2505.06120): 39% average drop from single-turn to multi-turn underspecified conversations; "when LLMs take a wrong turn in a conversation, they get lost and do not recover". A per-state message that restates what is known and what is next is the consolidation the paper recommends.

## 5. Sources

- Pipecat Flows API: https://docs.pipecat.ai/api-reference/pipecat-flows/flow-manager ; guide: https://docs.pipecat.ai/guides/features/pipecat-flows ; changelog (1.4.0, `pipecat-ai>=1.0.0`, `role_message`, `respond_immediately`): https://github.com/pipecat-ai/pipecat-flows/blob/main/CHANGELOG.md ; archived repo (merged into pipecat 1.5.0): https://github.com/pipecat-ai/pipecat-flows ; pinned source: `runtime/.venv/Lib/site-packages/pipecat/flows/{manager,types}.py`
- Gemini function calling modes and `tool_config`: https://ai.google.dev/gemini-api/docs/generate-content/function-calling ; newer page (Gemini 3 combines function calling with structured output): https://ai.google.dev/gemini-api/docs/function-calling
- Gemini context caching: https://ai.google.dev/gemini-api/docs/generate-content/caching ; https://ai.google.dev/gemini-api/docs/caching ; Flash-Lite minimum inconsistency: https://discuss.ai.google.dev/t/context-caching-docs-list-wrong-minimum-token-count-for-gemini-2-5-flash-flash-lite-missing-entirely/178942
- Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- OpenAI function calling (`tool_choice`, `strict`, `parallel_tool_calls`): https://developers.openai.com/api/docs/guides/function-calling ; structured outputs: https://openai.com/index/introducing-structured-outputs-in-the-api/
- BFCL: https://gorilla.cs.berkeley.edu/leaderboard.html ; snapshot with Gemini 3.1 Flash-Lite 76.5%: https://pricepertoken.com/leaderboards/benchmark/bfcl-v3 ; Gemini 3.5 Flash-Lite card: https://deepmind.google/models/gemini/flash-lite/
- Latency: https://artificialanalysis.ai/models/gemini-2-5-flash-lite ; https://artificialanalysis.ai/models/gemini-3-5-flash-lite
- Rasa CALM flows and collect steps: https://rasa.com/docs/reference/primitives/flows/ ; https://rasa.com/docs/learn/concepts/calm/ ; https://rasa.com/docs/learn/concepts/dialogue-understanding/
- LangGraph interrupts and conditional edges: https://docs.langchain.com/oss/python/langgraph/interrupts
- Vapi Workflows: https://docs.vapi.ai/workflows/overview ; Retell Extract Dynamic Variable node: https://docs.retellai.com/build/conversation-flow/extract-dv-node
- Name matching in voice AI (Double Metaphone + Levenshtein, 96%, 0.85 threshold): https://www.ml6.eu/en/blog/why-voice-ai-fails-at-name-matching-and-how-we-achieved-96-accuracy
- IFScale: https://arxiv.org/abs/2507.11538 ; Lost in the Middle: https://arxiv.org/abs/2307.03172 ; Lost in Multi-Turn: https://arxiv.org/abs/2505.06120
