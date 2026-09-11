# Open-source survey: what a human-style receptionist would borrow

Date: 2026-09-11. Read-only research; no repo code was changed. Every external claim carries a URL
and an access date in §9; everything not verified against a primary source is marked UNVERIFIED
inline. Local claims are cited to a file and line. Companion to
`docs/research/research-3-deterministic-flows.md` (2026-09-05), which asked "how do we make the
model obey"; this memo asks the opposite question — "how do we give the conversation back to the
model without giving up the ledger" — and corrects two of that memo's findings.

## 1. Executive summary

1. The field has converged on one shape: **the runtime owns the record and the transitions, the
   model owns the words and the repairs.** Nobody except us enforces honesty in code; every other
   project does it with a prompt sentence, and Google, Anthropic and LangChain each document that
   the sentence fails. So the flip is safe — but only if `guard()`, `draft_from` and the closed
   fields stay exactly where they are.
2. **Borrow one: an always-live answer tool.** `pipecat.flows` takes a `global_functions` list in
   the `FlowManager` constructor and mixes it into every node, so a caller asking "what was the
   facial one again?" mid-step hits a `describe_service` tool instead of having their words crushed
   into `choose_service`. Flows is already installed in our venv at 1.8.1 — this is a constructor
   argument, not a migration.
3. **Borrow two: a readiness check that reports, not just refuses.** Parlant's `ToolInsights`
   (`missing_data` with `datum_name`, `description`, `choices`) refuses the tool, tells the model
   which fields are missing *and what the legal values are*, and lets the model do the asking in
   its own words. Our `next_step()` is already that function — it just drives instead of reporting.
4. **Borrow three: a digression stack with a code-owned resume.** Rasa CALM pushes an interrupted
   flow onto a LIFO stack and pops it into a scripted `pattern_continue_interrupted`. Thirty lines
   in `flow.py`; no framework and, given CALM's licence, no code.
5. **Stop doing one thing: speaking a fixed step question on every turn.** `handlers.py` appends
   `next_question()` to every tool result with `run_llm=False`; that queued "What did you have in
   mind?" seven times on 2026-09-10 and it is the whole of "answering machine". It is also the
   worst-measured repair strategy in the literature: 49.2% recovery against 64.4% for moving to a
   different question (Bohus & Rudnicky, SIGdial 2005, §5.4).
6. Per-step tool *narrowing* is right and every project does it. Per-step tool *forcing* is the
   bug. Bolna's fix is one clause: drop the force once the tool has been called this node visit.
7. Cost is not the constraint people assume. One extra Flash-Lite call on every turn at our full
   prompt costs **+CA$0.0056/min** (64.3% → 58.6% margin at CA$0.0994). A short dedicated
   classifier call costs **+CA$0.0007/min**. Upgrading every turn to 3.5 Flash costs
   **+CA$0.0218/min** and drops margin to 42% — do it selectively or not at all.
8. The largest single cost win in this survey is not a model choice: **pre-render the fixed scripts
   to audio at bundle-build time.** TTS is CA$0.0094 of our CA$0.0355 minute; the fixed lines are
   25–40% of spoken characters, so this returns CA$0.0024–0.0038/min *and* removes the TTS
   handshake from the disclosure — 2.5–4× the entire 3.1-vs-3.5 model delta.
9. Reject outright: LiveKit's turn detector and ultraVAD (licence), TEN (Agora non-compete), VAP in
   the call path, every open-weights full-duplex model (no tool calling, no transcript, 5–90× our
   cost), Rasa Pro (proprietary, 1,000 conversations/month, one use case), GPTCache and RouteLLM
   (dormant, and a semantic cache's failure mode is a confident wrong answer for 0.4% of a minute).
10. For evaluation: Pipecat 1.9.0 (shipped 2026-09-10) adds `persona:`/`goal:` simulations with a
    local Ollama judge; τ²-bench's MIT `simulation_guidelines_voice.md` is the single artifact that
    generates the exact behaviours the founder is complaining about the absence of.

## 2. The ranked table

Cost column is the change to our measured CA$0.0355 all-in call-minute
(`docs/reports/tasks/cost-gap-C1.md`), computed at our measured call shape: 3 model turns a minute,
3,900 uncached + 2,500 cached input tokens and 37 output tokens per turn, FX 1.3896.

| # | Candidate | Licence | Activity | Mechanism to borrow | Maps to | CA$/min | Honesty risk | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | **`pipecat.flows`** (in pipecat core) | BSD-2 | 15.4k★, pushed today | `global_functions`; `tts_say` pre-actions; result-keyed branch tables; `(result, next_node)`; `NO_RESPONSE` | `flow.py`, `pipeline.py`, `handlers.py` | 0.0000 | Low — adds nothing, replaces nothing; `guard()` stays | **Adopt** |
| 2 | **Parlant** | Apache-2.0 | 18.3k★, last release 2026-04-28 | `ToolInsights.missing_data` + `choices`; per-state `CANNED_STRICT`; `on_message_generated` + `BAIL` | `flow.py`, `prompt.py` | 0.0000 (pattern only) | Low as a pattern; **high if adopted whole** — 4 LLM passes/turn, honesty is self-critique | **Borrow the pattern, not the runtime** |
| 3 | **Rasa CALM** | **Proprietary** (`rasa-pro`) | rasa-pro 3.19.3, 2026-09-10 | LIFO dialogue stack; `pattern_continue_interrupted`; the closed command vocabulary | `flow.py` | 0.0000 | Low as a design | **Copy the design. Never the code.** |
| 4 | **Pipecat evals 1.9.0** + **τ²-bench** | BSD-2 / MIT | both pushed 2026-09-11 | `persona:`/`goal:` sims, local judge, `calls: []`; `simulation_guidelines_voice.md`; pass^k | `scenarios/` | ~0 (local Ollama) | None — it measures the invariant | **Adopt** |
| 5 | **Bolna** | MIT | 754★, pushed today | Self-releasing forced `tool_choice`; `NodeType.STATIC/LLM/ROUTER`; `static_audio_hash` | `flow.py`, `pipeline.py` | −0.0024 to −0.0038 (audio cache) | Medium — its `extraction_agent.py` is a direct §2 violation; do not copy it | **Steal three ideas; do not adopt** |
| 6 | **Pipecat TTS cache / LiveKit `say(audio=)`** | BSD-2 / Apache-2.0 | third-party, 19★ / 14.1k★ | Pre-synthesised audio for fixed lines; deterministic key excluding secrets | `renderer.py`, `pipeline.py` | **−0.0024 to −0.0038** | Low — fixed scripts interpolate tenant config only | **Reimplement, don't depend** |
| 7 | **LiveKit `AgentTask` prebuilts** | Apache-2.0 (code) | 14.1k★, pushed 2026-09-10 | `GetPhoneNumberTask`: regex→`ToolError`, confirm tool installed only after a hypothesis, `IGNORE_ON_ENTER` | `tools.py`, `flow.py` | 0.0000 | Low; their own ladder stops at 2 rungs and never hands off | **Borrow the task shape** |
| 8 | **Pipecat Smart Turn v3.2 / eager generation** | BSD-2 | in our venv | `TurnMetricsData.probability`; two-threshold speculation; `EagerUserTurnStrategies` (1.9.0) | `pipeline.py`, `observers.py` | +0.0022 to +0.0031 | Low | **Instrument now, speculate after 1.9.0** |
| 9 | **OpenAI Agents SDK** | MIT | 29.3k★, pushed 2026-09-10 | `ToolGuardrailFunctionOutput.reject_content(message=)`; the neutral-filler clause | `flow.py`, `guard.py` | 0.0000 | Low as patterns | **Borrow two clauses** |
| 10 | **Dialogflow CX playbooks** | Proprietary SaaS | — | Routine-vs-task (one LLM call per turn vs per hop); typed params with *no* injection syntax; `PREVIOUS_PAGE` | `flow.py` | 0.0000 | Design validation only | **Read; don't adopt** |
| 11 | **Deepgram/Soniox per-word confidence** | vendor feature | current | Confidence-gated confirmation: confirm only when the acoustic evidence is weak | `resolve.py`, `processors.py` | 0.0000 (already paid) | Low — strictly reduces wrong stores | **Adopt (cheapest high-value item)** |
| 12 | **semantic-router** | MIT | 3.9k★, pushed today | Embedding route with **abstention** (returns `None` on no match) | `driver.py` (FAQ path) | −0.0013 ceiling | Medium if it answers without abstaining | **Park — ceiling too low** |
| 13 | **NeMo Guardrails / Colang 2.0** | Apache-2.0 | 7.1k★, pushed 2026-09-10 | `@override flow _bot_say` — one guarded egress with a reentrancy flag | `guard.py`, `processors.py` | 0.0000 (pattern) | **High if adopted** — runtime code generation; +1.5 s, ~30× tokens | **Borrow fifteen lines of design** |
| 14 | **LangGraph (library)** | MIT | 41.4k★ | `dialog_state` push/pop reducer; reject-with-feedback into the model's context | `flow.py` | 0.0000 (pattern) | **High if adopted** — `interrupt()` re-runs nodes, duplicate ledger writes | **Two ideas; reject the framework** |
| 15 | **Anthropic agent patterns** | doc | 2024-12-19 | Receipt-or-retract; "poka-yoke your tools"; workflow-vs-agent burden of proof | `guard.py` | 0.0000 | Low | **Vocabulary and a gate** |
| 16 | **Ultravox** | MIT code; weights UNVERIFIED | stale 9 mo | — | — | +0.05 USD/min floor | **Elevated** — speech-in/text-out still needs TTS, and it removes the transcript our health-context rule depends on | **Reject** |
| 17 | **LiveKit turn detector, ultraVAD** | **Model licence forbids use outside LiveKit Agents** / none declared | current | — | — | n/a | Legal | **Reject** |
| 18 | **TEN Framework** | Apache-2.0 **+ Agora non-compete** | 11.1k★ | (VAD/turn-detection repos only) | — | n/a | Legal — clause bars "enabling any third party to develop or deploy Applications" | **Reject** |
| 19 | **VAP / MaAI** | code MIT, **best models CC BY-NC-ND** | 2026-09-09 | Offline turn-taking scoring of recorded calls | eval only | n/a | Licence + 0.73 RTF/core/call | **Offline only** |
| 20 | **Full-duplex (Moshi, PersonaPlex, MiniCPM-o, CSM)** | mixed; two are NC | mixed | — | — | +0.18 to +0.59 | **Fatal** — no tool calling, no transcript, no text to guard | **Reject** |
| 21 | **Vocode** | MIT | **dead since 2024-11-15** | — | — | — | — | **Reject** |
| 22 | **Rasa Pro as a product**, **GPTCache**, **RouteLLM**, **Coval/Hamming/Bland** | proprietary / dormant / SaaS | — | — | — | — | — | **Reject** |

## 3. LLM-led dialogue with enforced business rules

### 3.1 `pipecat.flows` — and the finding that reframes the decision

`pipecat-flows` is not a dependency to add. It was merged into pipecat core at 1.5.0 and **is
already on disk** at `runtime/.venv/Lib/site-packages/pipecat/flows/` (`manager.py`, `types.py`,
`actions.py`, `adapters.py`, `exceptions.py`) under `pipecat-ai 1.8.1`, BSD-2-Clause. The standalone
repo is `"archived": true`, frozen at 1.4.0. Adopting Flows is an import statement.

Three corrections to the 2026-09-05 memo, which described the older API:

- **Static flows were removed.** `FlowConfig`, `transition_to` and `transition_callback` do not
  exist in 1.8.1 (grep of the installed package returns nothing; the Flows CHANGELOG records all
  three as breaking removals). In 1.8.1 there is exactly one model: build a `NodeConfig` dict in
  Python and return the next one from a tool.
- **It is `role_message` (singular `str`), not `role_messages`.** The list form is deprecated since
  1.5.0; `manager.py` warns and prefers the singular. It is delivered as a real system instruction
  via `LLMUpdateSettingsFrame` and *persists across node transitions* until a node sets it again.
- **`FlowResult` is deprecated with no replacement.** The handler contract is plain `Any`.

`NodeConfig`, verbatim from the installed `types.py`:

```python
class NodeConfig(TypedDict, total=False):
    task_messages: Required[list[dict]]
    name: str
    role_message: str
    functions: "list[FlowsFunctionSchema | FlowsDirectFunction]"
    pre_actions: list[ActionConfig]
    post_actions: list[ActionConfig]
    context_strategy: ContextStrategyConfig
    respond_immediately: bool
```

**Does it let the model word the questions? Yes — and it lets us keep the fixed ones fixed, in the
same node.** That split is the answer to the tension between the founder's request and
non-negotiable 3:

- `task_messages` are *instructions*, not text. The patient-intake example reads
  `content: "Ask whether they have any allergies, and record the answer with record_allergies"` —
  the caller hears the model's own phrasing.
- `pre_actions: [{type: "tts_say", text: "..."}]` pushes a `TTSSpeakFrame` that **never touches the
  LLM**. Verified in the installed `actions.py`: `_handle_tts_action` queues
  `TTSSpeakFrame(text=text, append_to_context=action.get("append_text_to_context", True))`. The
  three registered action types are exactly `"tts_say"`, `"end_conversation"`, `"function"`.

So the disclosure, clinical, complaint, payment, callback, goodbye and outcome scripts stay verbatim
`tts_say` strings from `scripts.yaml`; only the negotiable middle — "which treatment?", "who would
you like to see?" — becomes model-worded. `append_to_context=True` means the model knows a fixed
line was spoken and will not repeat it.

**Transitions.** A tool returns `ConsolidatedFunctionResult = tuple[Any, NodeConfig | None | _NoResponse]`:
`(result, next_node)` transitions; `(result, None)` stays and responds; `(result, NO_RESPONSE)`
stays and says nothing ("the next response will be triggered by something else, like a user
utterance"); `(None, next_node)` is transition-only and the manager substitutes
`{"status": "acknowledged"}`. `_check_and_execute_transition` gates on
`assistant_aggregator.has_function_calls_in_progress`, so two tools fired in one turn cannot tear
the state — which is the class of bug we hit on 2026-09-10.

**Tool constraint is by replacement, not by forcing.** `_set_node` computes
`functions_list = self._global_functions + node_config.get("functions", [])` and pushes
`LLMSetToolsFrame(tools=functions)`. It *narrows the menu*; it does not force a call. **Our slot
engine is stricter than Flows, and that strictness is the bug.**

**Digressions — the fix for "what was the facial one again?"** `FlowManager.__init__` takes
`global_functions: list[FlowsFunctionSchema | FlowsDirectFunction] | None = None`, stored and mixed
into every node. An `answer_question` / `describe_service` tool is live at every step; the node's
own `task_messages` stay in force, so the model returns to the step's job afterwards. In the
food-ordering example `get_delivery_estimate` is declared under `global_functions` for exactly this.

`respond_immediately=False` defers `LLMRunFrame` until the user speaks (and defers the node's
`post_actions` until after the first response) — the clean way to open the clinical flow after the
rules gate has spoken.

New in 1.9.0 (published 2026-09-11, hours before this research): a declarative `FlowConfig` layer —
`from_file`/`from_yaml`/`from_json`, `transition_only` entries, `{{ }}` placeholders, `!include`,
and a vendorable JSON Schema at `src/pipecat/flows/flow_config.schema.json`. The single most
valuable thing in it for us is the **result-keyed branch table**:

```yaml
functions:
  - name: check_availability
    transition_to:
      field: status
      cases:
        available: confirm
        unavailable: no_availability
```

The model cannot route here. Only a real check can produce `status: available`. That makes a
dishonest transition structurally impossible rather than merely discouraged — the same property our
"Tier C cannot import `Completed`" test buys, expressed in the graph. `Flow(config, handlers=...)`
also raises `FlowReferenceError` at construction listing every tool, handler or variable the config
names but cannot resolve: exactly the fail-fast we want for tenant-bundle validation.

**What Flows does not give us.** Structural honesty. Upstream grounds outcome claims with prompt
text ("Only give a delivery time that came from `get_delivery_estimate`") — precisely the promise
`guard()` exists because prompts do not keep it. It also holds a single scalar `_current_node`: no
stack, no resume, no digression memory. Both stay ours.

**Known bug to plan around:** issue #3925 (opened 2026-03-05, still open, no maintainer reply) — a
query with two informational intents fires a global tool twice and the bot speaks two separate
responses. For us that is a cosmetic double utterance; both halves still pass `guard()`.

**Risk: low.** `FlowManager(*, llm: LLMService | LLMSwitcher, context_aggregator, worker:
PipelineWorker, ...)` *requires* a `PipelineWorker`, which `pipeline.py` already builds, and
`adapters.py` is now 68 lines that only format conversation summaries — all provider-specific
adapters were removed in favour of the universal `LLMContext`, so Gemini/Soniox/Telnyx are
untouched (non-negotiable 4 and 6 both satisfied). The 2026-09-05 risk note about `FlowManager`
and `LLMRouter` not composing still needs a call to settle, but the type hint now reads
`LLMService | LLMSwitcher`.

### 3.2 Parlant — the closest match, and the one to read line by line

Apache-2.0, 18,283★, last release v3.3.2 on 2026-04-28, last `develop` commit 2026-06-26. **Flag
the cadence:** monthly releases through April, then 4.5 months of silence. Single-vendor project;
budget for vendoring if adopted.

**The readiness check we want already exists, and it is called `ToolInsights`.** From
`src/parlant/core/engines/alpha/tool_calling/tool_caller.py`:

```python
class ToolCallEvaluation(Enum):
    NEEDS_TO_RUN = "success"
    DATA_ALREADY_IN_CONTEXT = "data_already_in_context"
    CANNOT_RUN = "cannot_run"
    """Indicates that the tool call could not be executed, e.g., due to missing or invalid parameters."""

@dataclass(frozen=True)
class ToolInsights:
    evaluations: Sequence[tuple[ToolId, ToolCallEvaluation]] = field(default_factory=list)
    missing_data: Sequence[MissingToolData] = field(default_factory=list)
    invalid_data: Sequence[InvalidToolData] = field(default_factory=list)
```

`message_generator.py` renders that into a prompt section, verbatim:

```
MISSING DATA FOR TOOL REQUIRED CALLS:
The following is a description of missing data that has been deemed necessary in order to run tools.
The tools would have run, if they only had this data available and the rest of the data was valid.
If it makes sense in the current state of the interaction, you may choose to inform the user about
this missing data. If you inform of missing data that contains choices then present all of the
choices to the user.
```

`_format_missing_data` emits `datum_name`, `description`, `significance`, `examples` and
**`choices`**. `ToolParameterOptions` carries `hidden: bool` ("agents would not be able to inform
customers when it is missing") and `source: Literal["any","context","customer"]`.

That is both halves of the hypothesis in one mechanism: the tool is refused, the refusal names the
missing fields *and their legal values*, and the model asks in its own words. `choices` is
"candidates not verdicts" expressed as a prompt section.

**Per-moment fixed wording is a first-class configuration.** `CompositionMode` is
`FLUID | CANNED_FLUID | CANNED_COMPOSITED | CANNED_STRICT`; on STRICT, "the agent can only output
responses from the provided ones… the agent will send a customizable no-match message", and the most
restrictive mode wins. Critically, `composition_mode` is a parameter on `create_agent`,
`create_journey`, **every `transition_to` overload**, `create_guideline`, `create_observation` and
`create_capability`. **"FLUID everywhere, CANNED_STRICT at the outcome" is supported, not a hack** —
which is the exact posture non-negotiable 3 needs under a model-led dialogue.

**A chat state names the question's intent, not its wording.** From `examples/travel_voice_agent.py`:
`transition_to(chat_state="Ask about preferred travel dates")`, with edge cases handled by
journey-scoped guidelines rather than more states — and journey guidelines *override* journey
states. The same file sets `container[p.PerceivedPerformancePolicy] =
p.VoiceOptimizedPerceivedPerformancePolicy()`.

**Tools can steer one turn.** `ToolResult` carries `data`, `metadata` ("not seen or considered by
the agent"), `control`, `canned_responses` and `guidelines: Sequence[TransientGuideline]`. A resolver
can return candidates as `data`, inject a one-turn instruction, and hand the model the exact
sentences it may say this turn.

**A pre-send hard gate exists.** `hooks.py` `on_message_generated` runs "right after a message was
generated (but not yet emitted)" and `EngineHookResult.BAIL` drops the response. That is `guard()`'s
position, in a framework.

**Its honesty story is weaker than ours, and this is the reason not to adopt it wholesale.** The
ARQ schema (`message_generator.py`, from arXiv:2503.03669 — ARQs 90.2% vs CoT 86.1% vs direct
81.5% across 87 scenarios) includes `all_facts_and_services_sourced_from_prompt: Optional[bool]` and
per-fact `FactualInformationEvaluation(fact, source, is_source_based_in_this_prompt)`. That is the
model auditing itself. Nothing checks that a tool actually ran before the model asserts an outcome.
`guard()` plus "Tier C never imports `Completed`" is strictly stronger and must stay on top. Two
further routes by which text we did not write would reach a caller: `canned_responses` on
`ToolResult`, and `{{generative.*}}` template fields.

**Cost is the other reason.** `engine.py` runs at least four inference passes per turn (guideline
matching → tool inference → optional re-match → message generation → response analysis), more with
preparation iterations, and canned mode adds a selection pass. Their mitigation is a spoken
preamble, with `BasicPerceivedPerformancePolicy` inserting `random.uniform(1.0, 2.0)`s delays — a
UX patch, not a latency fix. At our shape four passes is CA$0.0074/turn = CA$0.022/min and lands
margin at ~46%.

### 3.3 Rasa CALM — the best-documented design, disqualified by licence

The licence position is worse than "source-available" and needs stating plainly.
`github.com/RasaHQ/rasa` is Apache-2.0, 21,322★, in maintenance mode — **and contains none of
CALM**: no `rasa/dialogue_understanding/`, no pattern YAML, `version.py` reads `3.7.0a1`. CALM ships
only in `rasa-pro` (3.19.3, uploaded 2026-09-10), whose PyPI metadata has `license: null`, no OSI
classifier and no LICENSE file in the wheel, gated at runtime by `RASA_LICENSE`. The Developer
Terms cap the free tier at **1,000 external conversations a month**, state "the license covers only
one use case", and forbid derivative works. For a multi-tenant product sold to many clinics, all
three are hard blockers. `rasa-calm-demo` carries Early Release Access Terms and is not an escape
hatch. **Copy the design; do not copy the YAML.**

**The split.** The command generator "generates a list of commands that represent how the user wants
to progress the conversation" and **does not execute them**; the FlowPolicy executes them against a
dialogue stack. The shipped v3 prompt template's command list is a natural-language DSL of six:
`start flow`, `set slot`, `disambiguate flows`, `search and reply`, `cancel flow`, `repeat message`,
closing with "Do not use any freeform text in your response - only use the action list format."
Internally there are 22 command classes; `HumanHandoffCommand` has been removed, and the shipped
default `pattern_human_handoff` body *declines* handoff.

**Digressions push; they do not cancel.** From source
(`stack/frames/flow_stack_frame.py`, `commands/start_flow_command.py`,
`core/policies/flows/flow_executor.py`): a digression mid-flow gets
`frame_type = FlowStackFrameType.INTERRUPT`; `KnowledgeAnswerCommand` does exactly one thing —
`stack.push(SearchPatternFlowStackFrame())`; and `trigger_pattern_continue_interrupted` fires when
the popped frame is an `INTERRUPT` user frame **or a `SearchPatternFlowStackFrame`**. So "the caller
asked a question mid-form" is a first-class, resumable stack frame, and the *runtime* pushes the
fixed-script resume offer when it pops. `utter_ask_continue_interrupted_flow_confirmation` is
"Would you like to continue with {{context.interrupted_flow_options}}?" — Rasa asks permission to
resume; on a phone a silent re-ask is probably better.

Twenty-one built-in repair patterns ship, overridable by defining a flow of the same name. The ones
that name our gaps: `pattern_clarification`, `pattern_continue_interrupted`, `pattern_correction`,
`pattern_skip_question`, `pattern_cannot_handle`, `pattern_collect_information`, and the
voice-specific `pattern_user_silence` (0 timeouts → repeat, 1 → `utter_ask_still_there`, >1 →
`utter_inform_hangup` + `action_hangup` — which is `IDLE_NUDGE_SECS` in `pipeline.py`, already
built).

Questions are fixed `utter_ask_{slot_name}` templates. An opt-in `rephrase` NLG exists, with Rasa's
own warnings: "Sometimes, the LLM will not generate a true paraphrase, but slightly alter the
meaning"; "a malicious user can potentially override the instructions in your prompt". A genuine bug
worth knowing: `patterns/continue_interrupted.py` sends a hard-coded Python string with *unrendered
Jinja* to the channel, so the caller hears the braces — exactly the failure "fixed wording is
config" prevents.

**Risk if we borrow the split without the discipline.** Rasa is safe because the *flow* is the only
thing that can speak; the LLM has no channel to the caller. Adopt the split but let the model author
wording and you lose the property that makes it safe. And `search and reply` /
`KnowledgeAnswerCommand` is a model-authored free-text path with no schema — the hole through which
"yes, I've booked you" arrives.

### 3.4 Bolna — the closest architectural match, and a warning

MIT, 754★, released 0.10.234 on 2026-09-11, multiple releases a week. Already supports Soniox STT
and Gemini — our exact stack. Its `enums.py` is the cleanest statement of the design we are reaching
for:

```python
class NodeType(str, Enum):      LLM = "llm"; STATIC = "static"; ROUTER = "router"
class EdgeConditionType(str, Enum):  LLM; EXPRESSION; UNCONDITIONAL; EVENT
class ToolScope(str, Enum):     GLOBAL = "global"; NODE = "node"
```

`NodeType.STATIC` returns `_static_message_chunk(...)` and **returns before any `generate_stream`
call** — verbatim wording, model never invoked: our fixed scripts, exactly. `ROUTER` is a silent
node that resolves to a speaking node without uttering anything. `EdgeConditionType.EXPRESSION`
with `ExpressionOperator` (eq/neq/gt/gte/lt/lte/in/not_in/contains/exists/not_exists) is
deterministic routing the model cannot influence — the same property as Flows' branch tables.
`ToolScope.GLOBAL` is their `global_functions`.

Two gems worth lifting regardless of framework, both from `graph_agent.py`:

1. **`static_audio_hash`** — `_static_message_chunk` returns
   `{"static_message": text, "static_audio_hash": get_md5_hash(text)}`. Hash the fixed scripts to a
   pre-synthesised audio cache. See §6.4; this is the biggest cost line in the survey.
2. **Forced tool calls that release themselves** — `_get_tool_choice_for_node`: "Return forced
   tool_choice for the current node, or None if not forced. Drops the force when required prompt
   vars aren't in `recipient_data`, **or when the tool has already been called this node visit**."
   That last clause is a targeted fix for our exact bug: force the slot tool once, then stop
   forcing, so the caller's follow-up question is not crushed into it.

They share our instinct, too (`graph_agent.py`): "Never yield the error as text: a chunk here is
indistinguishable from model output and gets spoken."

**The warning.** `bolna/agent_types/extraction_agent.py` is three lines: an unconstrained
`self.llm.generate(history, request_json=True)` whose output becomes the structured record. That is
a direct violation of non-negotiable 2. Borrow the node taxonomy and the two gems; leave the
extraction agent alone. Secondary risk: 133 open issues on a 754★ project, and adopting it means
abandoning Pipecat.

### 3.5 Dialogflow CX generative playbooks — validates the shape, shows the failure mode

Proprietary SaaS; the design is worth citing. A playbook is Goal + Instructions + Examples +
Parameters + tools. **The routine-vs-task distinction is the most useful thing on the page and it is
a cost finding:** *task* playbooks decompose via input/return parameters and "each time a task
playbook calls another task playbook, there is a LLM call"; *routine* playbooks read and write
session parameters directly and "each routine playbook in a series of transitions occurs within a
single conversational turn, so there is only a single LLM call." Prefer stage transitions carrying
typed state (one call per turn) over nested sub-agent invocations (one per hop).

A page/flow stack does exist, on the handler page rather than the parameter page: `PREVIOUS_PAGE`
restores "the page state from the previous page", flows push onto a flow stack (limit 25), and "the
session returns to Page P, which becomes active again with a preserved state". **And the evaluation
order is the escape hatch we lack:** intent routes are evaluated *before* parameter-level reprompt
handlers — interpret the turn as a route first, a parameter value second. Our `choose_service`
resolver is currently the first and only interpreter of the turn.

Its readiness check is an English sentence in a prompt: "Do not proceed until the user has made this
clear." Google's own best-practices page then records the consequence, verbatim: **"Sometimes, the
playbook AI Generator will hallucinate information in a response in lieu of a tool result."** Their
remedy is more prompt text. Two further traps: examples are retrieved and "omitted if approaching
token limits regardless of strategy", so honesty behaviour encoded in few-shot traces degrades worst
on the long messy calls where it is most needed; and "Playbooks, unlike flows, do not support
injecting parameter values with a particular syntax" — parameter *values* come from the model with
no control, which is why our "the ledger nulls and logs anything else" rule is the missing half of
their design. The one idea worth taking: typed input/output parameters as a stage's only contract,
with the model given **no injection syntax at all**.

### 3.6 OpenAI Agents SDK and the chat-supervisor pattern

`openai/openai-agents-python`, MIT, 29,343★, pushed 2026-09-10. Two narrow primitives.

**`is_enabled` on `handoff()`** — "Either a bool or a callable that takes the run context and agent
and returns whether the handoff is enabled… Disabled handoffs are hidden from the LLM at runtime."
The SDK's only dynamic-affordance lever, and the closest analogue to `step_tools()`. Its `input_type`
guidance keeps handoff payloads to closed metadata ("`reason`, `language`, `priority`, `summary`"),
not narrative — the same instinct as nine closed fields.

**`ToolGuardrailFunctionOutput` — the real find.** `src/agents/tool_guardrails.py` gives a typed
three-way pre-invocation outcome: `allow(...)`, **`reject_content(cls, message: str, ...)`** —
"Rejects the tool call/output but continues execution with a message to the model" — and
`raise_exception(...)`. That is our readiness check's exact semantics as a typed primitive, and the
message lands *in the model's context as the tool result*, so the model cannot proceed believing it
filed something. Note the headline input/output guardrails are **not** this: they are per-run, run
only for the first and last agent in a chain, and halt by exception — they cannot say "you are
missing `preferred_window`, ask for it."

**The chat-supervisor pattern** (`openai/openai-realtime-agents`, MIT, 6,974★, **pushed 2026-01-07 —
eight months stale; a demo, not a framework**). A cheap realtime junior holds the conversation with
exactly one tool, `getNextResponseFromSupervisor`; a `gpt-4.1` supervisor runs the whole tool loop
locally and returns a sentence the junior "should read verbatim". Its allowlist for the junior is
worth reading: greetings, basic chitchat, **"Respond to requests to repeat or clarify information
(e.g. 'can you repeat that?')"**, and collecting fields for the supervisor's tools.

And the filler rule, with an honesty clause inside it, verbatim:

> Before calling `getNextResponseFromSupervisor`, you MUST ALWAYS say something to the user…
> **Filler phrases must NOT indicate whether you can or cannot fulfill an action; they should be
> neutral and not imply any outcome.**

That second sentence is a real gap in `guard()`, which checks claims but not outcome-*implying
stalls* — and a stall is where a model-led dialogue is most tempted to pre-announce.

**Why not adopt the pattern itself.** Nothing enforces the verbatim read; no code compares spoken
text to `nextResponse`, so a realtime model that paraphrases "here is the booking link" into "I've
gone ahead and booked that" would not be noticed. The realtime output guardrail is debounced and
fires after audio may already be buffered ("Your audio player should still listen for
`audio_interrupted`… because some audio may already be buffered when the tripwire fires") — adopting
it downgrades a pre-send invariant to a best-effort retraction. And the economics run against us: a
`gpt-4.1`-class call on nearly every non-chitchat turn, with the README quantifying neither the
latency nor the cost, and admitting "more assistant responses will start with 'Let me think'."

### 3.7 NeMo Guardrails / Colang 2.0 — fifteen lines worth stealing, and nothing else

Apache-2.0 (the LICENSE.md is the SPDX short form, which is why GitHub reports NOASSERTION),
7,102★, v0.24.0 on 2026-08-26. Repo moved to `NVIDIA-NeMo/Guardrails`.

**Do not adopt.** Colang 2.0 is still "a beta version" at v0.24.0; the new fast `IORails` engine
"does not run the Colang dialog runtime" and "accepts Colang 1.0 configurations only"; and
`llm continue interaction` has the **model emit executable Colang source**
(`GenerateFlowContinuationAction` → `CheckValidFlowExistsAction` → `AddFlowsAction(config=$flow_info.body)`),
where a generated body can contain an arbitrary `bot say`. That defeats structural honesty at the
root. Latency: their committed benchmark (`qa/latency_report_openai.tsv`) puts dialog rails at 2.85 s
mean and 1,793 mean tokens against 1.31 s / 60 tokens for no rails; "Hi" goes from 0.42 s/16 tokens
to 0.76 s/602 tokens. (The TSV is from 2023-11-02 against `gpt-3.5-turbo-instruct` — treat the
ratios as durable, the seconds as historical. **No Colang 2.0 latency benchmark exists: UNVERIFIED.**)

**The one mechanism worth borrowing** is `colang/v2_x/library/guardrails.co`:

```
# meta: exclude from llm
@override
flow _bot_say $text
  global $bot_message
  global $output_rails_in_progress
  $bot_message = $text
  # We need to avoid running output rails on messages coming from the output rails themselves.
  if not $output_rails_in_progress
    await run output rails $text
  ...
```

Four ideas in fifteen lines: **one overridden egress primitive** rather than N call sites, so guard
coverage is structural rather than a discipline proved by import analysis; **a guard-owned
reentrancy flag**, which we will need the moment `guard()` substitutes tenant wording (the
alternative, a `skip_guard=True` parameter, is a door that will eventually be called from the wrong
place); **a rail that may rewrite, falling back to the original**; and **`# meta: exclude from llm`**,
marking the enforcement layer invisible to the model.

### 3.8 LangGraph — two ideas, reject the framework

MIT library (41,434★, pushed 2026-09-10); the server is `langgraph-api` under **Elastic-2.0** and
the local server wants a LangSmith key. Adopt neither.

**Reject `interrupt()` outright.** Its own docs: "the runtime restarts the entire node from the
beginning—it does not resume from the exact line where `interrupt` was called… any code that ran
before the `interrupt` will execute again", with the worked warning that an API call before the
interrupt "will be re-run multiple times when the node is resumed, potentially overwriting the
initial update or creating duplicate records", plus exponential re-execution for `while True` +
`interrupt()` and strictly index-based resume matching. Today "filed exactly once" is a property of
one place in code plus an import-graph test; under LangGraph it becomes a property maintained by
idempotency keys and correct `@task` placement — and a duplicate `Completed` is the specific failure
this product exists to exclude. Index-based matching also breaks precisely where model-led dialogue
is the point, since a model handling digressions will not ask the same questions in the same order.
A Postgres checkpointer would be a third schema owner beside Alembic's `runtime` and Prisma's
`public` (non-negotiable 7), and `interrupt()` is built for hours-to-days approval on a durable
thread — our pause is 300 ms of a phone call.

**Two ideas worth ~30 lines each.** From the retired customer-support tutorial (pinned at tag
0.2.37), the `dialog_state` push/pop reducer and `route_to_workflow` returning `dialog_state[-1]`:

```python
def update_dialog_stack(left: list[str], right: Optional[str]) -> list[str]:
    if right is None: return left
    if right == "pop": return left[:-1]
    return left + [right]
```

And from the modern `HumanInTheLoopMiddleware`, the **rejection-feedback loop**: "The `message` is
added to the conversation as feedback to help the agent understand why the action was rejected and
what it should do instead", with an argument-level `when` predicate to gate on a call's arguments.
Same shape as OpenAI's `reject_content`. The same page also independently discovers our
non-negotiable 1: **"Do not use `respond` to deny side-effecting tools, because its message is
treated as a successful tool result."**

No credible open-source LangGraph receptionist exists — the top hits are abandoned starters (51★,
5 commits, last push 2025-01-30) or unrelated booking apps. Pipecat's own LangChain processor
(`src/pipecat/processors/frameworks/langchain.py`) is 125 lines with **no tool-call handling at
all**, so a tool-calling LangGraph agent driving Pipecat is custom integration we own, on the
critical path of every spoken turn.

### 3.9 Anthropic's patterns — vocabulary, and a gate on the whole project

"Building effective agents" (2024-12-19) gives the taxonomy: workflows are "orchestrated through
predefined code paths", agents "dynamically direct their own processes", and "agentic systems often
trade latency and cost for better task performance… consider adding complexity only when it
demonstrably improves outcomes." **By that taxonomy our current design is a workflow, and the
article is complimentary about it.** The condition for reaching for an agent is "flexibility and
model-driven decision-making at scale" — task variety — not "the script feels rigid." A single
clinic's intake with nine closed fields sits near the *routing* sweet spot. The defensible reading
is augmented-LLM-plus-routing-with-programmatic-gates: model-authored wording and digression
handling *inside* a step, code owning the record and the transitions. And the article puts the
burden of proof on the new architecture — an A/B on the promptfoo suite before the state machine
comes out.

Two things to take. **"Poka-yoke your tools"** (from the appendix: "change the arguments so mistakes
are harder to make") is the principled justification for nine closed fields and no `notes`
parameter. And from `reduce-hallucinations`, the strongest honesty statement Anthropic publishes:
"Verify with citations… have Claude verify each claim by finding a supporting quote after it
generates a response. **If it can't find a quote, it must retract the claim.**" Generalise
"supporting quote" to "ledger receipt": any utterance asserting an outcome must name an item id the
ledger actually issued *this conversation*, or `guard()` strips it. Anthropic states this as a
prompt technique and admits prompts do not eliminate the failure; making it structural is strictly
stronger. Pair it with "allow Claude to say 'I don't know'" — the model needs a first-class,
always-available way to say "I've noted this for the team" that asserts nothing, or it will invent
one.

A dedicated customer-support *architecture* guide: not found (UNVERIFIED). The real material is the
customer-support chat use-case guide (static company context, few-shot interactions, an
`ADDITIONAL_GUARDRAILS` block including "Don't make promises or enter into agreements it's not
authorized to make", a recommendation of a separate intent classifier with the honest caveat that it
"requires an additional call… that can increase latency", and a **95%+ escalation-accuracy target**
worth adopting as a gate). `anthropic-cookbook` is now `anthropics/claude-cookbooks`;
`tool_use/customer_service_agent.ipynb` is stubs over hardcoded dicts with no system prompt and no
anti-fabrication instruction.

## 4. Turn-taking and barge-in

Our current settings (`spatalk/voice/pipeline.py`): `SmartTurnParams(stop_secs=1.5,
pre_speech_ms=300)`; `VADParams(confidence=0.6, start_secs=0.15, min_volume=0.4)` with `stop_secs`
left at the 0.2 default, which is what Pipecat recommends alongside smart turn and is **not** a bug;
start strategies `[MinWordsUserTurnStartStrategy(min_words=3, use_interim=True)]` only;
`user_turn_stop_timeout=2.0`; `user_idle_timeout=10.0`.

### 4.1 Smart Turn v3.2 — what it is, and the benchmark that should worry us

Whisper Tiny (39M) encoder plus a linear classifier ≈ **8M params**, int8 QAT ONNX, 8 MB on CPU
(the file in our venv is 8,679,182 bytes), 32 MB fp32 on GPU. Audio-native: 16 kHz mono PCM up to
8 s, no transcript, no VAD stream. Output is a single sigmoid with a **hard-coded 0.5 threshold** —
but the probability is surfaced as `TurnMetricsData(processor, model, is_complete, probability,
e2e_processing_time_ms)`. Inference 12.6 ms on a c7a.2xlarge, 3.3 ms on an L40S; marginal cost
effectively zero. v3.1 lifted English accuracy 88.3% → 94.7% by swapping synthetic for real human
audio.

**The uncomfortable number.** On LiveKit's open `eot-bench` (Apache-2.0), SmartTurn v3.2 is one of
the weakest endpointers measured: **35.2% false cutoffs at a 300 ms budget, 1051 ms of held silence
to reach a 5% false-cutoff rate.** Soniox's own server-side endpointing — which we already pay for
and have explicitly switched **off** — scores **647 ms and 5.5% at 600 ms**. LiveKit's own detector
tops the table.

Three caveats before acting. The benchmark is published by LiveKit, whose model wins. The Soniox row
is degenerate: the README states Soniox "map[s] endpoint events to binary scores: 0.0 before the
provider endpoint event has fired and 1.0 after", so there is no threshold to sweep and it cannot
reach a 300 ms budget at all. And Soniox's own Pipecat guide recommends `vad_force_turn_endpoint=True`
(their endpointing off) as "the recommended setup for low-latency voice agents" because it
"significantly reduces the time to final segment" — which measures transcript finalisation, not
turn-decision quality. Both can be true.

What is not in doubt is the interaction with our own setting. Pipecat's docs are explicit that "if a
turn is classified as incomplete but silence continues for longer than `stop_secs`, the turn is
automatically marked as complete", and that this is *not* the VAD's `stop_secs`. Our 1.5 s means
every unsure prediction costs the caller up to 1.5 s of silence, and the 2026-09-10 log shows it
firing on 2 of 13 turns for 1.39 s and 1.44 s each. Given a 35%-at-300 ms profile, "unsure" is
common. **We have no data on how often it fires**, because `spatalk/voice/observers.py` captures
`TTFBMetricsData` and not `TurnMetricsData`. That is the first thing to fix and it is free.

### 4.2 Barge-in false positives — the number that indicts `min_words=3`

Alibaba's *Duplex Conversation* (KDD 2022 ADS), from production telephone traffic: **only ~11% of
detected barge-ins are genuine; ~89% are false** — backchannels, noises, echoes, misplaced turns.
Their three subtasks are the right decomposition: user state detection, backchannel selection,
barge-in detection. They reported a 50% reduction in response latency in online A/B. No code.

Krisp's technical post is the only source with a rigorous head-to-head on *interruption* rather than
endpointing. At their recommended threshold 0.4: Krisp IP v1 (~6M params, 24 MB, CPU-only) gives
**5.9% FPR and 0.833 s mean interruption time**; VAD-based barge-in **66.3% FPR**; and
**minimum-word-count 1.528 s** — the slowest of the three.

**Read that middle row against our config.** `MinWordsUserTurnStartStrategy(min_words=3)` is our
only start strategy, and Krisp measures that family at ~1.5 s to a genuine interruption. The
2026-09-10 log measured 0.23–0.59 s from first *transcribed* word to audio stopping, which is
consistent — the cost is the words themselves. A caller interrupting to correct us waits about a
second. That is very likely a real contributor to "answering machine", and `INTERRUPT_MIN_WORDS = 3`
was the right fix for 2026-09-03's echo problem, not a permanent answer.

Krisp ships in Pipecat as `KrispVivaIPUserTurnStartStrategy(model_path, threshold=0.5,
frame_duration_ms=20, api_key)` — but the `.kef` model file is sales-gated with no public pricing,
which is a subscription floor and therefore blocked by CLAUDE.md. **There is no open-source
equivalent of Krisp IP v1.** The closest is `vap_bc_en` at F1 0.43 (§4.4).

**Pipecat has no false-interruption recovery.** `pipecat.turns` contains only `user_mute`,
`user_start`, `user_stop`; the CHANGELOG has no match for "resume" or "false interrupt". LiveKit's
`InterruptionOptions` is the design to copy: `min_duration=0.5`, `min_words=0`,
`false_interruption_timeout=2.0`, `resume_false_interruption=True`,
`discard_audio_if_uninterruptible=True`, and — the subtle one —
**`backchannel_boundary=(1.0, 1.0)`**, "a cooldown window at each turn edge so genuine corrections
and late-arriving transcripts aren't discarded as backchannels". The naive rule "short utterance
during bot speech = backchannel" misfires precisely at turn edges, where "no, Friday" lands. A
cooldown fixes it with no model.

### 4.3 Latency masking — the richest vein, and most of it is free

**Eager/speculative generation shipped in Pipecat 1.9.0 (2026-09-10).** `LLMContextFrame` carries a
`speculation` flag; `pipecat.turns.speculation_gate.SpeculationGate` has states OPEN/HOLDING/DROPPING
and buffers from `LLMFullResponseStartFrame`, released by `UserStoppedSpeakingFrame` and discarded by
`EagerEndOfTurnCancelFrame`; `EagerUserTurnStrategies(match_policy=…, speculation_timeout=5.0)` wires
it. **Soniox is not on the eager list** — only `DeepgramFluxSTTService`,
`DeepgramFluxSageMakerSTTService` and `CartesiaTurnsSTTService` push `EagerTranscriptionFrame`. (Docs
say `speculation_timeout` defaults to 3.0, source says 5.0 — UNVERIFIED which ships.) Verified absent
from our installed 1.8.1.

Deepgram Flux publishes the tradeoff: `eager_eot_threshold` 0.3–0.5 gives "EagerEndOfTurn 150–250 ms
earlier than EndOfTurn, at the cost of 50–70% more LLM calls", with an overall claim of 200–600 ms
saved and ~30% fewer false interruptions. **The important consequence for us: we already have
`probability` in `TurnMetricsData`, so a subclass of `LocalSmartTurnAnalyzerV3._predict_endpoint`
that speculates at p>0.35 and confirms at p>0.5 gets eager generation with no STT vendor change.**
`pipecat-examples/speculative-user-aggregator` is the template (it uses Cartesia's
`TurnEagerEndFrame`/`TurnResumeFrame` and claims ~half a second).

Cost: +50–70% LLM calls = **+CA$0.0028 to +CA$0.0039/min** at our shape (the 3-turn minute becomes
4.5–5.1 turns). Switching Soniox STT → Deepgram Flux English would add **+CA$0.0062/min** on top
(Soniox $0.002/min vs Flux $0.0065/min PAYG) and give up the better endpointer — so build the
two-threshold version instead.

**The free item: sentence aggregation is costing us 200–300 ms a sentence for nothing.** Pipecat's
own `TextAggregationMode` docstring, from our installed 1.8.1: `SENTENCE` "produces more natural
speech but **adds latency (~200-300ms per sentence)**"; `TOKEN` "streams text tokens directly to
TTS". We pass no `text_aggregation_mode`, so it resolves to `SENTENCE` — and Soniox explicitly
supports mid-sentence streaming ("speech starts before the sentence ends"). Cost CA$0; risk is
prosody, so A/B on one call. Avoid `LLMFullResponseAggregator`, which buffers the whole response.

`reduce_silence` on Soniox TTS is new in Pipecat 1.9.0 — "shortens the pauses between words on
models that support silence reduction", i.e. "trims the pauses without rushing the voice". Config
only, CA$0, and close to a direct answer to "sounds like an answering machine". Not present in our
1.8.1 `SonioxTTSSettings` (fields are `model, extra, _aliases, voice, language, speed`).

Also free: only `disclosure` in `tenants/skincentrix/scripts.yaml` carries an audio tag (`[warm]`).
Adding tags to the other scripts is config-only and satisfies non-negotiable 3 — but **the Soniox
audio-tag vocabulary is UNVERIFIED** (three candidate doc URLs 404'd), and whether an unrecognised
tag is honoured, ignored or spoken aloud needs a 30-second listening test.

### 4.4 Backchannels and fillers

**Is there an open-source backchannel predictor? Two, both weak.** VAP fine-tuned for backchannels
(NAACL 2025, "Yeah, Un, Oh") predicts timing and type on unbalanced real data at frame-wise
**F1 42.85% timing / 38.11% continuer / 31.76% assessment**, RTF < 1.0 on an i7-11700. It ships as
MaAI `vap_bc_{en,jp,ch,tri}` under **MIT** — and it is the one place in the whole VAP literature
where the two channels are explicitly *user speech* and *system audio*, which is exactly a phone
agent's situation and both streams we hold bit-exactly. MM-F2F (ACL 2025, MIT) reaches audio-only
F1 0.779 but publishes no latency and demonstrates no streaming inference. **A 43%-F1 predictor that
says "mm-hm" at the wrong moment sounds worse than silence.** Offline spike, not the call path.

**What the commercial products actually do is a word list and a dice roll.** Retell's create-agent
API: `enable_backchannel` (bool, off by default), `backchannel_frequency` (0–1, **default 0.8** —
"how often the agent would backchannel when a backchannel is possible"), `backchannel_words`
(string array). That is the state of the commercial art.

LiveKit shipped `ctx.with_filler()` in 1.6.0 (2026-06-11): an async context manager that plays a
fixed line via `session.say()` in quiet gaps, **bypassing the LLM**, with `delay`, `interval` and
`max_steps`, paired with `await ctx.update(message)` to give the LLM a synthetic return value.
Design note worth keeping: "Acknowledgment under one second prevents perceived call drops during
slow backends."

**Pipecat's equivalent is manual and already available to us**:
`await params.llm.push_frame(TTSSpeakFrame("Looking up…", append_to_context=False))`. There is no
`on_function_calls_started` event and no framework-level filler trigger. We already have
`FillerProcessor` and `UserIdleController` (`IDLE_NUDGE_SECS = 10.0`), and `cfg.scripts.fillers` is
`[]`, which makes the processor a no-op. **A filler is the safest possible utterance under our
rules** — it claims nothing, it comes from `scripts.yaml`, and with `append_to_context=False` it
never feeds back to a model. It must never be model-generated. Cost: CA$0 if pre-rendered (§6.4).

### 4.5 Voice Activity Projection — offline only

Correct the brief: VAP is not a 2×256 bitmap. It is 2 speakers × **4** bins = 8 bits → a single
**256-way softmax** over the joint state (bins 200/400/600/800 ms, 2 s horizon); the joint softmax
*is* the contribution. Ekstedt & Skantze, Interspeech 2022, trained on Switchboard (US telephone
speech — unusually apt). Real-time on CPU only at ≤1 s context: 76.16% balanced accuracy,
14.61 ms/frame, **RTF 0.73** — one core 73% consumed by one call at 50 Hz.

**Do not put it in the call path.** The licence is a minefield where the good models are the
forbidden ones: MaAI's best English checkpoints (`vap_en`, `vap_mc_en`, `vad_en`) are
**CC BY-NC-ND 4.0** — non-commercial *and* no-derivatives, which arguably forbids ONNX export. The
MIT `_kyoto` variants train on a narrower corpus with no published quality comparison. Add ~76%
accuracy, a PyTorch + CPC/Mimi stack, and the stereo assumption that every real deployment dodged
(the only field deployment, IROS 2025, set "the robot's audio… to zero" and turned the microphone
off while speaking, with full duplex listed as future work), and it is exactly the product-sized
stack CLAUDE.md forbids. **No "full-duplex VAP" paper exists**; the frontier moved to native
full-duplex speech LMs. One legitimate use: run the MIT checkpoints **offline** over recorded eval
audio to score our agent's turn-taking — which is literally what arXiv:2305.17971 does.

### 4.6 Full-duplex speech models — no, and the reason is not latency

Four blockers, in order of severity:

1. **No tool calling, anywhere.** LiveKit's own plugin page for the best open model states it flatly:
   "PersonaPlex doesn't support function calling or tools." Our product *is* the ledger, and the
   ledger is written by tool calls. A model that cannot call a tool would have to *claim* it filed
   something — the exact failure non-negotiable 1 exists to prevent.
2. **No transcript.** The PersonaPlex plugin provides no user speech transcription. Non-negotiable 9
   requires transcripts on, and non-negotiable 2 puts volunteered health-context detail *only* in
   the transcript.
3. **No `guard()` chokepoint.** Audio out means no text utterance to guard and no way to source
   wording from `scripts`.
4. **The economics invert.** Kyutai Moshi needs 24 GB VRAM; the RL-tuned `moshika-rl-seamless` — the
   version with *fixed* turn-taking — is **CC BY-NC 4.0**, so the good one is the one we may not
   sell. NVIDIA PersonaPlex (MIT code / NVIDIA Open Model weights, 7B, 0.070 s turn-taking vs
   Gemini's 1.301 s) is the best demo in open voice and a dead end for a ledger product. Sesame CSM
   is **mis-sold by the internet: it is a TTS** ("cannot generate text"), abandoned since 2025-05-27;
   "Maya" was never released. MiniCPM-o 4.5 (Apache-2.0 both, 9B, genuinely full duplex) is the one
   to watch, but documents "at most four sequences per stage" and three "experimental" labels.

At a medspa's realistic ~90 call-minutes a day, an L40S at US$784.80/month is **CA$0.402 per
call-minute** — 11.5× our entire cost. Break-even against the CA$0.0044 model line needs ~5.7
sustained concurrent calls 24/7 (~91 tenants on one GPU); the only verified concurrency ceiling for
any open-weights full-duplex stack is 4. Serverless does not rescue it: ~20 GB of weights means
scale-to-zero and answer-on-the-first-ring are mutually exclusive. Hosted is the realistic option
and still not today: **Gemini Flash Live at $0.005/min audio in + $0.018/min out ≈ CA$0.016–0.019/min
is 3.6–4.4× our model line and 45–55% of our whole call cost**; OpenAI realtime is 5–16×, and grows
with call length because "the entire conversation is sent to the model for each Response".

**Review trigger, not a calendar reminder:** revisit when all three hold — an open-weights
full-duplex model documents function calling *and* emits a text transcript; verified concurrency
exceeds ~8 streams/GPU; and Pipecat ships a first-party service. Verified against the repository
tree, `pipecat/src/pipecat/services` contains no `moshi`, `kyutai`, `personaplex` or `minicpm`
directory, and Pipecat's entire speech-to-speech list is hosted APIs. A widely-cited blog claiming
"Pipecat supports Moshi as a service" is false.

The interesting adjacent finding: **component substitution, not architecture replacement.** Kyutai
STT (weights CC-BY 4.0) reports 64 concurrent streams on one L40S at 3× RTF, and Pocket TTS is 100M
params real-time on CPU. Both drop in behind `make_stt`/`make_tts` without touching the brain, the
ledger or a single non-negotiable. Our model line is 12.6% of the minute; the money is in the other
87%.

## 5. Clarification, repair and grounding

### 5.1 The named patterns, and the one command we lack

Rasa's `KnowledgeAnswerCommand` — "the caller asked something the flow does not cover" — pushes a
`SearchPatternFlowStackFrame` and is resumable. **We have no equivalent.** At the SERVICE step the
only tool is `choose_service`, so "what was the station one again?" became
`choose_service(said="the station one")`, scored 0.6995 on a substring of "free virtual
consultation", and was confirmed as a choice. The 2026-09-10 fix (`shares_a_word`) stops that
particular match; the structural fault — no tool can express "this was a question" — remains.

Rasa names our position exactly, and calls it broken: when CALM runs on NLU rather than an LLM,
"CALM dialogue understanding output is limited to `set slot` and `start flow` commands" — a
one-or-two-command vocabulary is what Rasa documents as the *degraded* mode. That is our tool set at
every step.

The design to copy is the stack plus the pop-triggered repair: push on digression, pop to a
code-owned resume. Rasa's own resume *asks permission*; on a phone a silent re-ask of the open
question is probably better, and we already have `asked_already()` to stop it being verbatim twice.
Two of its defaults are worth copying as defaults: `pattern_clarification` caps options at three
(`max_clarification_options`, `initial_value: 3.0`) — the same rule as our "never name more than
three treatments in one breath"; and `pattern_chitchat` is **off by default**, its shipped body being
literally `- action: utter_cannot_handle` with the generative response commented out. Every default
utterance in all twenty patterns is config, not code — external validation of non-negotiable 3.

Dialogflow's counted escalation is free where ours is hand-rolled: `sys.no-match-[1-6]` then
`sys.no-match-default`, each with its own handler and optional page transition. Our `misses` dict is
the same idea with two rungs.

Dialogflow's contribution is the **evaluation order**: routes before parameter values. Parlant's is
that **journey-scoped guidelines override journey states**, so an edge case is a guideline rather
than another node. Neither Parlant nor `pipecat.flows` has a stack (verified: `manager.py` holds a
single scalar `_current_node`; grep for `stack|previous_node|resume|digress` finds only
`stacklevel=` and `cancel_on_interruption`). Parlant backtracks a graph instead: "IF conversation
invalidates current progress: BACKTRACK… ELSE IF transition condition met: PROGRESS / ELSE: STAY".
**The resume stack is ours to write either way.** RavenClaw (Eurospeech 2003) got there first and its
resume semantics are better than Rasa's: resumption is a *completion criterion*, not a re-ask —
"the AskName agent already has its completion criterion satisfied… and will not be scheduled for
execution", which is exactly `next_step()` skipping a filled slot.

### 5.2 Mis-heard names — the four-rung ladder, and who has which rung

Two vendors converged independently on the same two-pass policy. Vapi: "First, try reading the email
back naturally… If the user says it is wrong, switch to letter-by-letter spelling for the entire
address", with NATO as the third rung "only if the user is having trouble understanding individual
letters", and the anti-autocorrect rule "Never modify, autocorrect, or guess any part… Treat the
email as an exact string." LiveKit's PR #6990 (merged 2026-09-08) benchmarks it: "GPT-4.1 name
spelling after correction improved from 80% to 95%" using **pre-spaced letters**, and
**"it does not add NATO spelling"** — they deliberately rejected NATO.

**LiveKit's `GetPhoneNumberTask` is the most transferable artifact in the survey.** Its shape:

1. A regex gate raises `ToolError` back to the model —
   `if not re.match(PHONE_REGEX, cleaned): raise ToolError(f"Invalid phone number provided: {phone_number}")`.
   `ToolError.message` reaches the model verbatim with `is_error=True`, so it retries; nothing
   invalid is ever stored.
2. A confirm tool is **installed dynamically** only once a hypothesis exists
   (`await self.update_tools(current_tools)`), and its return string is a directive: "Prompt the user
   for confirmation, do not call `confirm_phone_number` directly."
3. A **stale-closure guard** for parallel tool calls in one turn: if the number changed after the
   confirm tool was installed, confirm refuses and asks again.
4. `decline_phone_number_capture` is `ToolFlag.IGNORE_ON_ENTER` — not offered until the question has
   actually been asked.

Three more details from the same family of tasks, each of which maps onto a live bug of ours.
`decline_name_capture(reason: str)` is a **named escape hatch** — it completes the task with
`ToolError(f"couldn't get the name: {reason}")`, so a refusal can never be mistaken for a capture;
that is the generalisable form of "the model has nowhere to put this". A type-confusion rejection
guards the slot, with a comment that reads like our own incident report: "Reject digit-only or
punctuation-only values so a card number, ZIP code, phone number, etc. accidentally crammed into
`update_name` fails fast instead of being recorded as the user's name" — and a `_clean_name_arg` that
exists because "some models (e.g. gemma) fill optional args with placeholder strings like
'null'/'NULL'". And `GetNameTask.on_enter` carries the anti-re-ask instruction we need most:
**"First scan the conversation — if a name was already given earlier, ask a short confirmation
question rather than asking from scratch… Only ask fresh when the conversation has no name yet."**
`GetDtmfTask` shows the strongest version of the hypothesis/confirm split: **only one of
`confirm_inputs` / `record_inputs` is registered at a time, so the model cannot skip confirmation —
it is not in the schema.**

And in the task's `_BASE_INSTRUCTIONS`, a line that belongs in our prompt verbatim: **"Always
explicitly invoke a tool when applicable. Do not simulate tool usage, no real action is taken unless
the tool is explicitly called."**

**Their ladder has a hole they document themselves**: "Escalation depends on the model calling the
update tool again. A spoken refusal alone does not guarantee that call… it does not establish refusal
detection." Their hermetic test asserts `third == second` — **it stops at two rungs and never hands
off.** For us: drive the attempt counter from *our* turn state (a rejected confirmation increments
it), not from whether the model re-calls a tool, and add the fourth rung — file the item with the
field marked unconfirmed for a human. That is the open item from the 2026-09-10 report ("a
mis-transcribed first name is now stored") with an answer.

**Spelling mechanics.** Pipecat has one example, `examples/features/features-user-email-gathering.py`,
and its mechanism is one prompt line plus a TTS tag: "Enclose all emails with `<spell>` tags".
`CartesiaTTSService.SPELL(text)` and `RimeHttpTTSService.SPELL(text)` exist, and `SkipTagsAggregator`
keeps tags from breaking sentence aggregation. The source comment in `cartesia/tts.py` states
Pipecat's own preference, which is our non-negotiable 3: "The preferred way… is to use an
`LLMTextProcessor` and/or a `text_transformer` to identify and insert these tags for the purpose of
the TTS service alone." **Code inserts the tag; the model does not.** Rime's `spell()` groups
deterministically — `spell(4252528929)` → "4 2 5 ‹pause› 2 5 2 ‹pause› 8 9 ‹pause› 2 9" — whereas
Pipecat's built-in `expand_phone_numbers` flattens to ten ungrouped digits, the thing LiveKit's
prompt forbids. We already group correctly in `resolve.spoken_digits`. Cartesia's own `<spell>` docs
are login-walled: UNVERIFIED at source.

The only NATO *decoder* found is AWS's `verify_spelling.py` (MIT-0): a small-model prompt that
decodes any "X as in word" to its first letter and diffs against the original — tolerant of "B as in
boy", which is what real callers say. One extra small-model call per verification, and an honest
failure mode ("ERROR: Could not verify spelling. Compare manually").

**Phonetic matching used to decide *whether to confirm*: confirmed absent from every licensed
open-source voice agent.** Rasa has zero hits for `levenshtein`; `fuzzy` appears only in a Dialogflow
fixture. The only score→dialogue-act mapping found is an unlicensed interview exercise (0★, reference
only) with thresholds `VALID_AUTO > 0.95`, `NEEDS_CONFIRMATION 0.80–0.95`, `NEEDS_SPELLING < 0.80`
and a four-rung ladder terminating in a human transfer. **Our metaphone + rapidfuzz layer is ahead of
every reference implementation, and there is no prior art for the thresholds** — which is why the
2026-09-05 note that they came "from one published production write-up" is still the honest status,
and why call tests remain the only way to tune them.

**An anti-pattern to name.** Retell ships `smart_matching: bool` — "Treat near-match similar words as
same entity to reduce impact of transcription error". That writes "Brandon" when the caller said
"Brendon". Our instinct is the right one: **the fuzzy score should choose the question, never the
stored value.** Retell's `echo_verification` and `nato_phonetic_alphabet` are the same shape as
Vapi's, priced at ~190/~190/~110 system-prompt tokens on every turn, with the injected text
deliberately unpublished.

### 5.3 Confidence-aware grounding — the cheapest high-value item in the survey

**Yes, the STT exposes it, and one vendor tells us to use it for exactly this.** Deepgram's
confidence doc: per-word confidence in the `words` array, calibrated ("a confidence of 0.93 means the
model estimates a 93% chance the word is correct"), available in streaming, with the recommendation
"around 0.65 works well as an error detector — words below this threshold are very likely to be
genuine errors (high precision)", the caveat "Use confidence values from final transcripts for any
downstream decision-making", and the rule that speaks directly to our fragment bug: **"Low confidence
on an entity word is a stronger signal to escalate than low confidence on a filler word."** Soniox —
our vendor — exposes per-token confidence 0.0–1.0, "always included by default", with the listed use
case "Trigger post-processing, e.g., request user confirmation or re-check with additional context."

**Framework gap, with a free workaround.** LiveKit treats it as first-class (`SpeechData` has
`confidence: float` plus `words`); Pipecat does not — the word "confidence" does not appear in
`src/pipecat/frames/frames.py`, and `TranscriptionFrame` is `user_id/timestamp/language/result/finalized`.
But `result` is documented "Raw result from the STT service" and the Soniox and Deepgram services
pass the provider message through, so **per-token confidence is readable off `frame.result` today
with no library change**.

That closes two live problems at once. "Peyman" heard as "payment" was a *low-confidence* token that
we stored as a name; and a fragment ("Um", "Well") is a *high-confidence, low-content* turn that
should not re-trigger a step question. A confidence-gated policy — accept silently when the acoustic
evidence is strong, confirm when it is weak, spell when it is very weak — is a confirmation policy
driven by acoustic evidence, which **none of the four reference implementations has**.

One cost correction: Deepgram Keyterm Prompting is **not free** — $0.0013/min on top of Nova-3's
$0.0048, a ~27% STT uplift ≈ CA$0.0018/min. AssemblyAI's equivalent is ~19× cheaper (+$0.04/hr), and
its free-text `prompt` alone is documented to cut WER 5–21% by level of detail. Deepgram's own
worked example is a dermatology term, which is the argument for doing this at all: **"tretinoin"
0.712 → 0.965.** Vapi's wrapper exposes *negative* intensifiers (`kansas:-10` **suppresses** a term),
so confusable service names can be actively pushed down rather than only boosted up. Soniox's
`context` field takes up to **8,000 tokens** (16× Deepgram's 500-token cap) with
`terms`/`general`/`text` sections — streaming support and cost UNVERIFIED. Boost `team[].name`,
service names and `concerns`; **never boost digits** ("Avoid sending strings of numbers or
alphanumerics" — use `numerals=true` and DTMF instead).

One more borrow, cheap and channel-aware: LiveKit's `_confirmation_required` defaults to
`ctx.speech_handle.input_details.modality == "audio"` — **confirm on voice, accept on text.** A sane
default before thresholds are tuned, and it generalises across our four channels for free.

**One hazard for non-negotiable 2:** a spelling interaction yields one bit per field (confirmed or
not) plus an attempt count. That is an enum and an integer, never a `confirmation_notes` string. And
DTMF digits land in the transcript by default on both LiveKit and Vapi, so they inherit our 30-day
retention — make that deliberate.

### 5.4 The measured comparison nobody in the current wave has redone

Bohus & Rudnicky, *"Sorry, I Didn't Catch That!"*, SIGdial 2005 (CMU): ten named recovery strategies
with literal wording, 46 participants, and measured recovery rates. This is twenty-year-old work and
it is the only *empirical* ranking of repair strategies found anywhere in this survey.

| Strategy | Recovery |
|---|---|
| **MoveOn** — "advances the task by moving on to a different question" | **64.4%** |
| FullHelp — dialogue state plus what you can say | 58.5% |
| **TerseYouCanSay** — just the options | **56.5%** |
| **Reprompt** — "repeats the previous prompt" | **49.2%** |
| YouCanSay / AskRephrase | 48.6% |
| DetailedReprompt / Notify | 37.7% / 35.7% |
| **AskRepeat** — "Can you please repeat that?" | **33.7%** |
| Yield (silence) | 31.2% |

Their explanation of why: "once an error has occurred, the likelihood of having an error in the next
turn is significantly increased… As we go deeper into a spiral of errors, patience runs out."

**Read our own behaviour off that table.** A fragment re-triggering the fixed question is
**Reprompt, 49.2%**. `ask_service_again` ("Sorry, which treatment did you have in mind?") is
**AskRephrase, 48.6%**. And the instinct to ask the caller to repeat is **AskRepeat, 33.7% — second
worst of ten.** The two best strategies are the two we do not use, and both are nearly free: read the
caller the closed list, which we already hold in `services.yaml` and `scripts.yaml`
(TerseYouCanSay, 56.5%); or move to a different question and come back (MoveOn, 64.4%), which is
exactly what a digression stack makes possible.

The paper also dates the framing we are working inside: the explicit-versus-implicit confirmation
distinction is attributed there to Krahmer et al. 1999 and treated as *solved* for
misunderstandings, with non-understandings the open problem. Our two live bugs are one of each —
"facial" accepted as a firm choice is a misunderstanding; "Um" re-triggering the question is a
non-understanding. (Krahmer et al. 1999 not read: UNVERIFIED.)

## 6. Cost patterns

All arithmetic below uses our own measured shape, not a vendor's example: 3 model turns a
call-minute, 3,900 uncached + 2,500 cached input tokens and 37 output tokens a turn, 58% agent
speaking fraction, FX 1.3896 (`docs/research/rates.json`, re-derived 2026-09-10 in
`docs/reports/tasks/cost-gap-C1.md`). One model turn on 3.5 Flash-Lite is
`3900×$0.30 + 2500×$0.03 + 37×$2.50` per million = **$0.0013375 = CA$0.00186**.

| Change | CA$/min | Total | Margin at CA$0.0994 |
|---|---|---|---|
| Today (3.5 Flash-Lite) | — | 0.0355 | 64.3% |
| Today on 3.1 Flash-Lite | −0.0010 | 0.0345 | 65.3% |
| + a short classifier call every turn (400 in / 20 out) | +0.0007 | 0.0362 | 63.6% |
| + a full second pass every turn (same 6,400-token prompt) | +0.0056 | 0.0411 | 58.6% |
| Every turn on 3.5 Flash ($1.50/$0.15/$9.00) | +0.0218 | 0.0573 | 42.4% |
| One Flash turn a minute, two Lite | +0.0073 | 0.0428 | 56.9% |
| Eager generation (+50–70% LLM calls) | +0.0028…0.0039 | 0.0383…0.0394 | 61.5…60.4% |
| **Pre-rendered fixed-script audio** | **−0.0024…−0.0038** | **0.0317…0.0331** | **68.1…66.7%** |

Read that table as the answer to "is there headroom for naturalness": **yes, for a small extra call
on every turn or a big one occasionally; no, for a Flash-class model on every turn.** And the one
row that moves in our favour is not a model decision at all.

### 6.1 Prompt caching — and a measured disagreement with the documented model

Gemini's cached-input discount is **90%, not 75%**: Vertex's own overview says "90% discount on
cached tokens compared to standard input tokens", and the pricing page agrees exactly (3.5
Flash-Lite input $0.30, caching $0.03). The 75% figure is stale, from the 2025-05-08 launch post.
Implicit caching is "enabled by default for all Gemini 2.5 and newer models" and needs no API
support: "There is nothing you need to do in order to enable this."

**The minimum token count for Flash-Lite is UNVERIFIED.** The published table lists Gemini
3.8/3.7/3.6 Flash and 3.1 Pro at 4,096 and 2.5 Flash/Pro at 2,048; the string "Flash-Lite" does not
appear in either the HTML or the `.md.txt`. Caching *is* supported (the 3.5 Flash-Lite model card
says "Context caching: Supported"). The only rule available is Vertex's generation-level one: Gemini
3 and 3.1 require 4,096, Gemini 2.0 and 2.5 require 2,048.

**The tool-list question has two answers, and the disagreement is ours to record.** The documented
model says a tool-list change invalidates the cache on all three providers. Anthropic is explicit:
"Cache prefixes are created in the following order: tools, system, then messages… Changes at each
level invalidate that level and all subsequent levels", with "Modifying tool definitions (names,
descriptions, parameters) invalidates the entire cache." OpenAI agrees and adds *ordering* to the
list. Gemini's explicit `CachedContent` bakes `tools[]` and `toolConfig` in as "Immutable", so a
per-state tool list would need one cache object per state, each with its own $1.00/MTok/hour storage.

**Our own measurement rejects that for Gemini's implicit cache.** `cost-gap-C1` §"The prefix does not
move, and the cache does not care" logs 13 turns: turn 3 changed step and hit 4,041 cached tokens;
turn 2 changed step and missed; turns 4 and 12 missed with the same tool as turns that hit. No
correlation with the step change. What the four logged calls *do* show is a **ceiling**: the cache
read is 3,985–4,063 tokens every single time it appears, across four calls, including calls whose
static half was 7,400 tokens rather than 5,930. So everything above ~4,050 tokens is billed at full
rate whatever we hold identical, and the cache is best-effort on top of that (29 of 49 turns, 59%).
**Consequence, already decided: sending the full tool list every turn to hold the prefix identical
buys nothing and costs ~550 tokens a turn.**

Two things follow. First, **the escape hatch in Anthropic's own table is the design we want anyway**:
"Tool choice → tools cache OK, system cache OK, messages cache X. Changes to `tool_choice` parameter
only affect message blocks." One stable union of tools every turn, varied by `tool_choice` per state,
is cache-safe *and* is Flows' narrow-don't-force model *and* is Bolna's self-releasing force. Second,
the measured ceiling means our prefix is already ~1,900 tokens past the point where caching helps, so
the only remaining implicit-cache lever is total tokens a turn — which a model-led design reduces,
because the per-step brief replaces prose rules.

Pipecat has no prompt-caching plumbing at all (`context-management.md` has nothing on it; no
`cache_control`, no cacheable-prefix marker). For Gemini implicit caching that does not matter.

Two Anthropic details to record in case a failover ever points there. Tool definitions carry a
**hidden system-prompt surcharge** — Haiku 4.5 adds **496 tokens** with `tool_choice` `auto`/`none`
and **588** with `any`/`tool`, *before* our own schemas; and the cache TTL is measured "from the
start of the request that writes or reads the cache entry, not from the end of its response", which
on a call with 20-second turns is a real difference. Cache-write multipliers are 1.25× at five
minutes and 2× at one hour, reads 0.1×.

### 6.2 Two-model designs

The affordable shape is a **small dedicated classifier with its own short prompt**, not a second pass
at the full context: 400 in / 20 out on 3.5 Flash-Lite is CA$0.00024 a turn = **+CA$0.0007/min, 2% of
the minute and 0.7 margin points**, every turn. A big supervisor on one turn in three costs
CA$0.0073/min (7 margin points) on 3.5 Flash. `gpt-5-nano` at $0.05/$0.005/$0.40 is the cheapest
credible classifier on the market — half the input price of 2.5 Flash-Lite.

**Pipecat routes between models natively**: `LLMSwitcher` from `pipecat.pipeline.llm_switcher`, args
`llms` + `strategy_type` (default `ServiceSwitcherStrategyManual`), switched at runtime by queueing
`ManuallySwitchServiceFrame(service=...)`, with the docs demonstrating cross-provider OpenAI↔Gemini
switching "based on task complexity, cost optimization, or specific model capabilities". **Load-bearing
and UNVERIFIED: whether the context carries across the switch.** Test it before designing on it —
and note `FlowManager` is now typed `llm: LLMService | LLMSwitcher`, which is also the answer to the
2026-09-05 worry about `LLMRouter`.

`aurelio-labs/semantic-router` (MIT, 3,890★, pushed 2026-09-11) is the honest FAQ-shortcut: an
embedding route that **abstains** — "no decision could be made as we had no matches — so our route
layer returned `None`". Local encoders available. Latency is UNVERIFIED (the README's only claim is
"superfast"). Cost is negligible ($0.0000003 per utterance on `text-embedding-3-small`) and so is the
saving: skipping 2 of 7 turns saves ~CA$0.0013/min. **Adopt for latency and abstention if at all,
never for money.** `RouteLLM` (Apache-2.0, 5,474★) has not been pushed since 2024-08-10, publishes no
latency discussion, and routes on prompt *difficulty* — the wrong shape for "which of eight things is
this". Treat as abandoned.

### 6.3 Semantic caching — reject

`GPTCache` (MIT, 8,187★) has not been pushed since 2025-07-11. Its header claims "Slash Your LLM API
Costs by 10x" with no methodology, and its own README states the failure mode: "you may encounter
false positives during cache hits and false negatives during cache misses." Its metrics are Hit
Ratio, Latency and Recall — **no precision metric**, which is the only one that matters here. The
upside caps at ~CA$0.0013/min = 0.4% of the all-in minute, from a dormant dependency whose failure
mode is a fluent, confidently wrong answer to a question nobody asked. Against "never claim an action
it did not take", that is unpriceable for 0.4%. The right shape is a router that maps an utterance
onto *our* YAML-authored answer and abstains on no match; a cache maps onto a previous model output
and has no concept of abstention.

### 6.4 When a fixed line beats a model turn — and the biggest win in the survey

No published measurement of canned-vs-generated latency was found (UNVERIFIED, and it was looked
for). What exists instead is instrumentation to measure it ourselves: Pipecat's TTFB metrics, the
STT-latency-tuning guide, and `UserBotLatencyObserver`.

**But the cost case needs no measurement.** Soniox TTS is $0.011667 per *generated* minute =
CA$0.01621, and at our measured 58% speaking fraction that is **CA$0.0094 per call-minute — 27% of
the all-in minute and 2.1× the entire model line.** (Corroboration from a different direction: the
same figure computed for Deepgram Aura-1 at ~450 spoken characters a call-minute is CA$0.0093, and
CA$0.035 − CA$0.021 telephony+STT − CA$0.0044 model leaves ~CA$0.0096 for TTS and infrastructure.
Three independent routes to the same number.) The fixed scripts are spoken identically on every
call and interpolate only tenant config. On the 2026-09-10 call, of 30 queued utterances roughly a
third were fixed script. At 25–40% of spoken characters pre-rendered, that is
**−CA$0.0024 to −CA$0.0038/min, 7–11% of the all-in minute** — 2.5–4× the entire 3.1-vs-3.5 model
delta of CA$0.00096, and comparable to paying for a whole extra model call on every turn.

It also fixes a latency problem nobody has costed. `pipeline.py` queues the disclosure on
`on_client_connected`, so every caller's first impression is a cold Soniox TTS websocket handshake.
Vapi's latency guide puts "warmed, cached TTS" at 100–200 ms saved.

**Who ships one.** Pipecat's docs carry `TTSCacheMixin` ("transparently wraps any Pipecat TTS
service, caching repeated phrases to cut API costs and response latency"), with `cache_backend`,
`cache_ttl` (default 86400), `cache_namespace`, a key "generated from the normalized text, voice ID,
model, sample rate, and settings" with API keys excluded, and Memory/Redis backends. **Flag it: despite
living in official Pipecat docs it is third-party** — `pipecat-tts-cache` 1.0.1, BSD-2-Clause, 19★,
one contributor, 6 commits, 7 open issues, and it does not document pre-warming. Read it and
reimplement. LiveKit does it more directly: `say(text=..., audio=<pre-synthesized frames>)` —
"Plays the provided audio and the `text` is used for the transcript and chat context", i.e. a correct
transcript entry with zero TTS invocation. Bolna's `static_audio_hash` is the same idea.

**Better than lazy caching: pre-render each fixed script to a WAV at bundle-build time and ship the
audio in the tenant bundle.** Zero TTS calls, no cold miss on the first call of the day, and a
byte-identical disclosure on every call — which is a compliance property, not only a cost one. Do
**not** add Redis (CLAUDE.md forbids the product-sized stack); use the in-memory backend or the
bundle.

Parlant's `CANNED_STRICT` is the other half of the question — "the agent can only output responses
from the provided ones", rationale "completely eliminating the risk of even subtle unwanted or
hallucinated outputs" — but note it still spends a model call per turn. The model's job moves from
generation to *selection*. That is a safety win, not a cost win.

### 6.5 Verified prices, USD per million tokens

Input / cached input / output. Gemini (`ai.google.dev/gemini-api/docs/pricing`, paid tier):
3.5 Flash-Lite **0.30 / 0.03 / 2.50** (+$1.00/MTok/hr storage); 3.1 Flash-Lite **0.25 / 0.025 / 1.50**;
2.5 Flash-Lite 0.10 / 0.01 / 0.40; 3.5 Flash 1.50 / 0.15 / 9.00; 3.8/3.7/3.6 Flash 0.75 / 0.075 / 3.75,
**doubling on 2027-01-01**; 2.5 Flash 0.30 / 0.03 / 2.50. **Generation trap: 3.5 Flash-Lite is 3× the
input and 6.25× the output of 2.5 Flash-Lite — upgrading generation is a 3–6× cost event, not a free
refresh**, which is why `LLM_MODEL` sitting on 3.5 while the quote prices 3.1 was worth catching.
OpenAI: `gpt-5-nano` 0.05 / 0.005 / 0.40; `gpt-4.1-nano` 0.10 / 0.025 / 0.40; `gpt-4.1-mini`
0.40 / 0.10 / 1.60; `text-embedding-3-small` 0.02. Anthropic: Claude Haiku 4.5 1.00 / 0.10 / 5.00
(cache write 1.25× at 5 min, 2× at 1 hr; minimum cacheable 4,096 tokens; and a hidden 496–588 token
tool-use system prompt before our own schemas). For contrast, `gpt-realtime-2.1-mini` audio is
$10 in / $20 out per million — 30–100× text, which is good evidence that our STT+text+TTS pipeline is
the cheap architecture. All model names in the brief exist; "Claude Haiku" currently means 4.5.

Two sanity checks on the architecture rather than the line items. Deepgram's own bundled Voice Agent
API is **$0.056/min PAYG rising to $0.075**; our unbundled pipeline at CA$0.0355 ≈ US$0.026 beats a
vendor's own bundle by roughly 2×, which matches the CA$0.0778–0.0889 Telnyx figure already in
`rates.json`. And Anthropic's newer tokenizer uses "approximately 30% more tokens for the same text"
on Claude 4.7 and later — worth knowing before any prompt is priced against a Claude fallback.

## 7. Evaluation of naturalness

**We already own the harness and are one minor version behind the feature we want.** `pipecat.evals`
is installed (11 modules, `.venv/Scripts/pipecat.exe`), BSD-2-Clause. On our 1.8.1 we already have
scripted scenarios with `send_after: {event: llm_started, delay_ms: 2000}` for **barge-in testing**
(its own docstring: "interrupt 500ms after the bot started responding"), `eval:` LLM-judge criteria,
`calls:` tool-call assertions with argument subsets, `absent: true`, per-event `within_ms` budgets,
`dtmf:` turns and `!include`. Three assertion surfaces, and the docs name the right default:
`response` is "the STT of the bot's *actual synthesized audio* — the real end-to-end check".

**Pipecat 1.9.0 (CHANGELOG 2026-09-10) adds exactly the harness the founder's complaint needs**:
"give a scenario a `persona:` and a `goal:` instead of scripted turns", with `metrics` (each a
`name` + `criterion` + optional `min_score`, scored as "the share of turns that got a yes"),
`measure` (`turns`, `duration`, `words`, `latency`, `function_calls`), `success`, `runs` ("Every run
must pass: a persona does not say the same thing twice, so one run is an anecdote and three are a
check"), and backstops `max_turns` 20 / `max_duration_s` 300 / `max_silence_s` 30. **Judge and
persona both default to local Ollama; audio mode uses local Kokoro TTS and Moonshine STT — "No keys,
no per-run cost"**, which keeps our one paid Gemini run a gate for promptfoo.

Two of its shipped scenarios are near-copies of our problem.
`scenarios/simulated/complete_patient_intake.yaml` has an `efficiency` metric that is a repair
metric — "the reply does not ask the patient to repeat information they already gave (confirming it
back is fine)" — and an `accuracy` metric "when the reply repeats information the patient gave, it
matches what they said". `scenarios/scripted/interruption_{audio,text}.yaml` assert a barge-in is
answered "instead of continuing the Paris story", and `filter_incomplete_turns*.yaml` pin
premature-endpointing regressions.

**Its judge prompt is worth reading for one design decision**: a three-valued verdict
`"yes" | "no" | "continue"`, where `continue` means "the bot has not given its answer yet: it says it
is checking, looking something up… This holds however long and however fluent the reply is." Plus an
STT-tolerance clause — "treat a number as the same value whether it is spelled out, written as a
digit, or transcribed as a homophone" — which is the fix for the false failures we would otherwise
hit judging spoken phone numbers. Verdicts are cached by `(criterion, conversation)` hash, so re-runs
are stable and free.

**The methodology to copy is Sierra's, not Pipecat's.** `tau2-bench` (MIT, 2,001★, pushed
2026-09-11) gives two things. First, `pass^k` — and the source definition matters more than the
prose: `math.comb(success_count, k) / math.comb(num_trials, k)`, the probability that *k* trials drawn
from *n* are all successes. A reliability measure, not best-of-k. Pipecat's `runs: 3` with "every run
must pass" is the degenerate case. Second — **the single highest-value artifact in this survey** —
`data/tau2/user_simulator/simulation_guidelines_voice.md` (MIT, 85 lines), which instructs the
simulated caller in exactly the behaviours the founder says we cannot handle:

- disfluencies and restarts: "Can you [pause] sorry, I meant to ask, can you help me with…"
- "Sorry, could you repeat that? I didn't quite catch it"
- "If the agent asks you to repeat your name, email, or other personal details, offer to spell it out
  letter by letter", with the phone convention "Letters: 'J, O, H, N' NOT 'J O H N'"
- self-interruption mid-form: "I've been trying to… oh wait, should I give you my account number
  first?"
- progressive disclosure: "Make the agent work for information"
- and, straight onto non-negotiable 1: **"Do not end the conversation prematurely. Agreeing to an
  action is not the same as the action being completed."**
- plus hard grounding against fabrication: "You only know what is explicitly stated in the scenario
  instructions… When asked, say you don't know or don't remember."

Paste that into a shared `persona_preamble` and `!include` it, with attribution in a NOTICE. Its
voice-synthesis path is hard-wired to ElevenLabs, so take the persona *text*, not the voice ids; its
`data/voice/background_noise_audio_pcm_mono_verified/` (car horn, siren, busy street, TV news) is a
drop-in STT-robustness noise injector.

**The metric panel to copy verbatim** is `tau2-bench/docs/interaction-metrics.md` (MIT), computed
offline from tick-level trajectories — "no extra runs, no judges, no self-reported numbers":
`response_latency_mean` (L_R↓), `yield_latency_mean` (L_Y↓), `response_rate` (R_R↑), `yield_rate`
(R_Y↑), `agent_interruption_rate` (I_A↓), and three selectivity rates — `selectivity_backchannel`,
`selectivity_vocal_tic`, `selectivity_non_directed` (↑: the fraction the agent *correctly talked
through or ignored*). Detection windows to copy as constants: tick 0.2 s, `no_yield_window_sec` 2.0,
backchannel/vocal-tic/non-directed yield windows 1.0, response windows 2.0, with classification
priority backchannel > vocal tic > non-directed > real interruption. Four methodological rules worth
adopting wholesale: **report the denominator** and suppress any rate under 10 events; strip the
terminator artifact (we would hit the exact analogue with Pipecat's `end_call`); **version-stamp the
metric code** so a metric change reads as a metric change rather than a regression; and never average
incomparable things.

Sierra also states plainly what to leave out, having built both kinds: "FDB's LLM-judged response
quality, MOS/prosody scores, and pause-handling metrics are deliberately out of scope for the
leaderboard (no judged or audio-perceptual metrics)."

**And the assertion our product actually lives on needs no model at all.** Pipecat's
`measure: function_calls` with **`calls: []`** — "Every listed call must have happened and any call
not listed fails it, so `calls: []` says the bot must call nothing, the check for a caller who should
be turned down." Put that on every scenario whose correct outcome is a refusal or a Tier C hand-off,
beside a `success:` criterion asserting the refusal claims nothing. Deterministic, zero-token, and
stronger than any judge because it reads the tool-call record rather than the prose.

**What to reject.** **Full-Duplex-Bench is CC BY-NC 4.0** — verified by fetching the LICENSE file
(GitHub reports NOASSERTION). SpaTalk is commercial: do not vendor its code or data, and do not run
it in a commercial QA gate. Read the four papers for the metric definitions and use tau²'s MIT
reimplementation of the same axis, which is why Sierra wrote it. VoiceBench (Apache-2.0) measures
speech-in LLMs, not agent pipelines — the one usable part is `sd-qa`'s design (hold the question
fixed, vary only the accent/region, report per-region accuracy), which is a cheap STT-robustness
table for a Mississauga clinic. Coval's open repo is STT/TTS provider benchmarking, not conversation
evaluation; the platform is closed SaaS. Hamming is SaaS with no published pricing, but its
**golden-call replay for drift detection** is worth copying with the transcripts we already retain.
Bland is SaaS, and its one genuinely useful contribution is a taxonomy: `BLAND_TONE` decomposes
naturalness into **empathy / conciseness / flow / back-channeling**, which is four `metrics:`
criteria instead of one vague "sounds natural" judge call. NISQA (MIT) is worth keeping for *channel*
quality — its Noisiness and Discontinuity dimensions score the PSTN path, which is a real risk
surface — but only on eval-harness audio, never on production calls, because that would need the
audio-persistence flag non-negotiable 9 deliberately withholds. And state the distinction plainly:
**TTS MOS is not conversational naturalness.** A voice can score MOS 4.5 while the agent talks over
the caller and re-asks for a name it already has.

`promptfoo` has a simulated-user provider, but its docs say "By default, SimulatedUser uses
Promptfoo's hosted conversation models" and document no model override — **partially UNVERIFIED, a
negative from one page; confirm in `src/providers/simulatedUser.ts`**. If it holds, our conversation
content would leave our infrastructure and could not run on Gemini, which rules it out for
tenant-shaped scenarios. Keep promptfoo for what it is good at — single-turn prompt and guard
regression at the QA gate — and put multi-turn simulation in Pipecat evals, where the tool-call and
timing assertions actually exist. `deepeval` (Apache-2.0, 18.2k★) is the best off-the-shelf
conversational metric library if we want one: `role_adherence` is precisely "the agent stayed a front
desk and never became a clinician", `conversational_g_eval` is the shape for a custom naturalness
rubric, its judge prompts are published as plain text files, and its `ConversationSimulator` accepts
any `DeepEvalBaseLLM` so it can run on Gemini.

## 8. How it maps onto SpaTalk

No implementation here — this is the change list a plan would be written from, smallest first. Each
item names the file and the interface it touches.

### 8.1 `runtime/spatalk/brain/flow.py` — the state machine becomes a record

**(a) `next_step()` reports instead of drives.** It is already a pure readiness function over
`Slots` (line 94). Add a sibling that returns the *missing-field set* for the open flow, each entry
carrying `datum_name`, a one-line `description` and, where the field is closed, its `choices` —
Parlant's `MissingToolData` shape. `next_step()` stays for `_finalize` and for `draft_from`'s
preconditions; what it stops doing is choosing a question.

**(b) `Pending` keeps the record and loses the question.** `Pending` (line 51) currently encodes both
"this is unresolved" and "ask this fixed sentence". Split those: the `Match` from `resolve.py` (which
already returns `kind: exact|confirm|which|kind|none` with `candidates`) becomes *visible to the
model* as tool-result data, and the model words the confirmation. `Pending` remains as the record of
what is unresolved, so `_after_slot`, the pairing check and the miss counters are untouched.

**(c) A digression stack replaces the single `Pending`.** Borrow LangGraph's reducer shape and Rasa's
pop semantics: a `tuple[Flow, ...]` on `Slots` with push/pop, an `INTERRUPT` marker on the pushed
frame, and — following RavenClaw rather than Rasa — resume by *completion criterion* (a filled slot
is skipped) rather than by re-asking. `next_step` already skips filled slots, so this is mostly
bookkeeping. About thirty lines.

**(d) The forced tool becomes a narrowed tool set plus a self-releasing force.** `step_tools()`
(line 213) keeps doing exactly what it does — it is the same mechanism as Flows' per-node `functions`
and Bolna's `ToolScope.NODE`. What changes is that the step's slot tool is no longer the *only* way
to spend a turn (see 8.3) and, if we ever force `tool_choice`, the force drops once the tool has been
called this step visit (Bolna's `_get_tool_choice_for_node`).

**(e) `apply()` returns a rejection the model can read.** Today an un-offered tool is
`Applied(ignored=True)` and the driver decides what to do. Give the ignored path a *message* —
OpenAI's `reject_content(message=...)`, LangChain's reject feedback, LiveKit's `ToolError` — so the
refusal lands in the model's context as the tool result and the model cannot proceed believing it
filed something. That also removes the need for `IGNORED_TOOL_RETRIES` as a loop guard, because the
model is told why.

**(f) An attempt counter drives escalation and terminates in a filed-but-unconfirmed item.** The
`misses` dict (line 76) is already the counter. Add the fourth rung LiveKit's ladder lacks: after
confirm → spell → offer alternates, file the item with the field marked unconfirmed (a boolean
column, never a note) so a human resolves it. This closes open item 2 of
`docs/reports/tasks/voice-regression-V1.md` ("a mis-transcribed first name is now stored") without
choosing between a wrong name and a dropped call. Escalate on *our* turn state — a rejected
confirmation increments the counter — not on whether the model re-calls a tool, which is the hole
LiveKit documents in its own ladder.

**(g) Replace the bare re-ask with the two strategies that measure better.** `step_question`'s
`ask_service_again` / `ask_practitioner_again` keys are AskRephrase (48.6%); the fixed question
re-fired at a fragment is Reprompt (49.2%). Add a `_terse_options` shape — read the caller the closed
list we already hold, which is TerseYouCanSay at 56.5% — and let the digression stack make MoveOn
(64.4%) available: answer the side question, then come back. Cap the list at three, as
`pattern_clarification` does and as our own "never name more than three in one breath" rule already
says. New `scripts.yaml` keys, so non-negotiable 3 is untouched.

`draft_from` (line 613), `ITEM_TYPE`, `_finalize` and every closed-value rule stay exactly as they
are. Nothing in this list widens `ItemDraft`.

### 8.2 `runtime/spatalk/brain/prompt.py` — the brief becomes a readiness report

`step_message()` (currently in `flow.py`, line 628) is the thing to rewrite, and `build_system_prompt`
mostly stays. Today the brief says "put their answer in `<tool>`. Do not ask a question yourself; one
short acknowledgement at most." It becomes Parlant's two sections: what is known, and what is missing
with its legal choices — and it *invites* the question instead of forbidding it. Three prompt lines to
add, each borrowed verbatim from a project that ships it:

- LiveKit's `_BASE_INSTRUCTIONS`: "Always explicitly invoke a tool when applicable. Do not simulate
  tool usage, no real action is taken unless the tool is explicitly called."
- OpenAI's chat-supervisor filler clause: filler phrases "must NOT indicate whether you can or cannot
  fulfill an action; they should be neutral and not imply any outcome."
- Vapi's anti-autocorrect rule for the name and number steps: never modify, autocorrect or guess;
  treat it as an exact string.

And one line to delete: the instruction not to ask a question, which is the prompt half of the
symptom the founder reported. Keep the static prefix byte-stable (`steps.py` already appends the
brief after `STEP_MARKER` at the end of the system message) — though note from §6.1 that at
~5,900 tokens we are already past the measured ~4,050-token implicit-cache ceiling, so prefix
stability is now worth less than total token count.

### 8.3 `runtime/spatalk/brain/tools.py` — two new tools, no new fields, nothing widened

**(a) Add an always-live `answer_question` (or `describe_service`) tool.** This is the single change
that fixes "what was the facial one again?". It is `global_functions` in Flows, `ToolScope.GLOBAL` in
Bolna, `KnowledgeAnswerCommand` in Rasa, and the junior's "respond to requests to repeat or clarify
information" allowlist entry in the chat-supervisor pattern. It belongs in `always_tools()` beside
`escalate` and `end_conversation`. **It takes no free-text argument and writes nothing** — its only
effect is to push the digression stack and hand the turn to the model, so non-negotiable 2 is
untouched. Without it, the model's only way to spend a turn at the SERVICE step is to claim a service.

**(b) Add a named escape hatch per slot step**, LiveKit's `decline_name_capture(reason)` shape: a
closed-enum `reason`, no free text, and a completion the runtime reads as "not captured" rather than
as a capture. Without it, a caller who will not give a number leaves the model with only tools that
assert something.

**(c) Keep `change_answer` and give it the slot's current value.** The 2026-09-10 fix made
`change_answer` on an empty slot `ignored`; with (e) above it becomes an informative rejection
instead.

**(d) Split `choose_service` and `choose_practitioner` into hypothesis and confirmation.** Today one
tool both proposes and decides, which is why "facial" became a firm choice. Register the confirm tool
only once a hypothesis exists — and prefer `GetDtmfTask`'s strongest form, where only one of the two
is in the schema at a time, so the model *cannot* skip confirmation. The tool-result string carries
the directive, not the caller-facing sentence: "Prompt the user for confirmation, do not call
`confirm_*` directly." The read-back string itself is built in code (`resolve.spoken_digits` already
does this correctly for phone numbers, in groups, where Pipecat's own `expand_phone_numbers` would
flatten it).

**(e) `TOOL_NAMES`, the closed enums and the three transient string arguments do not change.** No
tool gains a notes parameter. `file_request` and `send_link` keep taking nothing. The
`ONLY_WHAT_THEY_SAID` suffix stays, and the Retell `smart_matching` anti-pattern is the reason it
stays. If a `decline_*` tool takes a `reason`, it is an enum like `escalate`'s, never a string.

### 8.4 `runtime/spatalk/voice/pipeline.py` and its neighbours

**(a) Capture `TurnMetricsData` in `observers.py`.** Five fields (`processor`, `model`, `is_complete`,
`probability`, `e2e_processing_time_ms`). We currently have no data on how often Smart Turn returns
INCOMPLETE or how often the 1.5 s fallback fires, and every turn-taking decision below is guesswork
until we do. Free, and it is the prerequisite for settling `TURN_END_FALLBACK_SECS`, which the
2026-09-10 report correctly refused to change from a desk.

**(b) Read per-token STT confidence off `TranscriptionFrame.result`.** No library change needed.
Two immediate uses: a low-confidence name goes to confirmation instead of straight to `give_name`
(the "payment"/"Peyman" failure); and a high-confidence, low-content fragment ("Um", "Well") does not
count as an answer to the open question. Deepgram's own guidance — "low confidence on an entity word
is a stronger signal to escalate than low confidence on a filler word" — is the rule.

**(c) Set `text_aggregation_mode=TextAggregationMode.TOKEN` on `SonioxTTSService`.** Pipecat's own
docstring prices SENTENCE at 200–300 ms a sentence, and Soniox streams mid-sentence. CA$0. A/B on one
call, because prosody is the risk.

**(d) Add `VADUserTurnStartStrategy(enable_interruptions=False)` ahead of the existing
`MinWordsUserTurnStartStrategy(min_words=3)`.** Every start strategy takes `enable_interruptions`, and
`MinWords` applies its threshold only while the bot is speaking. The effect would be an instant
turn-start on VAD when the bot is silent, with barge-in still gated by word count. **Reasoned from
the source, not run — treat as a hypothesis for a call test**, alongside the echo argument in
`docs/reports/tasks/voice-regression-V1.md` symptom 1 for why a VAD-driven *barge-in* is still wrong.

**(e) Pre-render the fixed scripts to audio.** §6.4: the largest single cost item here, −CA$0.0024 to
−CA$0.0038/min, plus 100–200 ms off the disclosure. Do it at bundle-build time keyed on the rendered
text, in the tenant bundle, played through `TTSSpeakFrame`'s existing path or `SoundfileMixer`. No
Redis. The key must exclude secrets and must never cover a line containing caller data — by
construction `scripts.yaml` interpolates tenant config only, so the fixed set is safe and the
rendered-with-fills set is not.

**(f) `handlers.py`: stop appending `next_question()` to every tool result.** This is the "one thing
to stop doing". Today `_make_handler` speaks `spoken + next_question()` with `run_llm=False`; that is
what queued the same eight words seven times. Under the new design the runtime speaks only the *fixed
outcome and confirmation* lines and hands the turn back with `run_llm=True` plus the readiness
report, letting the model word the next question. `next_question()` stays as the fallback for a silent
model turn and for the moments where wording is law.

**(g) `processors.py`: keep the guard, restructure its coverage.** `OutputGuardProcessor` is
load-bearing and gets *more* important, not less, when the model writes the questions. Three changes
worth planning: follow NeMo's `@override _bot_say` and make one private egress function the only path
to TTS, with `guard()` inside it and a guard-owned reentrancy flag rather than a `skip_guard`
parameter; extend the lexicon to reject outcome-*implying stalls* per the chat-supervisor clause; and
add receipt-or-retract — an utterance asserting an outcome must name an item id the ledger issued this
conversation. Then **relax the trailing-question suppression**, which was the right fix for a runtime
that asked its own question on top and becomes wrong the moment the model owns the question. `guard()`,
`render_script`, the rules gate and `asked_already()` all stay.

**(h) `FlowManager` is now typed `llm: LLMService | LLMSwitcher`**, which retires the 2026-09-05 risk
note about it not composing with `LLMRouter` — but it still needs a call to confirm, and `LLMSwitcher`
context carry-over across a switch is UNVERIFIED.

### 8.5 Evaluation, and the gate on the whole thing

Add `runtime/scenarios/` Pipecat eval YAML beside the promptfoo suite: the `!include`d τ²
`persona_preamble`, one simulated scenario per flow, `runs: 3` with pass^k reported at k=1..3,
`measure: function_calls` with `calls: []` on every refusal and Tier C scenario, and the eight-metric
interaction panel computed offline from the event stream. Assert *intent*, LiveKit-style, never the
exact wording of a tenant script, so a `scripts.yaml` edit does not break the suite. Judge and
persona on local Ollama, so the one paid Gemini run stays with promptfoo.

Then the gate, which is Anthropic's and is the right one: "consider adding complexity only when it
demonstrably improves outcomes." Run both architectures through the suite before the state machine
comes out, with cases for the failure every project in this survey actually has — a paraphrased
outcome claim, a neutral stall that leaks an outcome, a digression that loses the open request, and a
duplicate file after a retry.

### 8.6 What must not change

`draft_from` as the only constructor of an `ItemDraft`. Tier C never importing `Completed`. `guard()`
on every model utterance, pre-send and synchronous. Outcome, disclosure, clinical, complaint, payment,
callback and goodbye wording from `scripts.yaml`. The nine closed fields and the ledger's
null-and-log rule. `file_request` and `send_link` absent until the required slots are filled.
`BusinessCalendar` for every due time. `make_stt` / `make_tts` / `make_llm` as the only vendor names.
Every test in `tests/test_structural_honesty.py`, `test_renderer.py`, `test_guard.py`,
`test_driver.py` and `test_voice_processors.py`.

## 9. Sources

All URLs accessed **2026-09-11** unless stated. Items marked (local) are files in this repo or its
virtualenv.

**Pipecat and Flows**
- https://github.com/pipecat-ai/pipecat · https://github.com/pipecat-ai/pipecat-flows (archived)
- https://raw.githubusercontent.com/pipecat-ai/pipecat/main/CHANGELOG.md (1.9.0, 2026-09-10)
- https://raw.githubusercontent.com/pipecat-ai/pipecat-flows/main/{README,CHANGELOG}.md
- https://docs.pipecat.ai/guides/features/pipecat-flows · https://docs.pipecat.ai/api-reference/pipecat-flows/flow-manager
- https://docs.pipecat.ai/pipecat/evals/overview · https://docs.pipecat.ai/pipecat/learn/function-calling
- https://docs.pipecat.ai/pipecat/fundamentals/metrics.md · .../stt-latency-tuning.md · .../api-reference/server/utilities/observers/user-bot-latency-observer.md
- https://docs.pipecat.ai/api-reference/server/utilities/turn-management/user-turn-strategies
- https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview
- https://docs.pipecat.ai/api-reference/server/utilities/service-switchers/llm-switcher.md
- https://docs.pipecat.ai/api-reference/server/services/tts/tts-cache.md (third-party: https://github.com/omChauhanDev/pipecat-tts-cache, BSD-2, 19★; https://github.com/pipecat-ai/pipecat/issues/2629)
- https://github.com/pipecat-ai/pipecat/issues/3925 (global tool fires twice; open)
- https://github.com/pipecat-ai/pipecat-examples/tree/main/speculative-user-aggregator
- https://github.com/pipecat-ai/smart-turn · https://huggingface.co/pipecat-ai/smart-turn-v3
- https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/ · https://www.daily.co/blog/improved-accuracy-in-smart-turn-v3-1/
- (local) `runtime/.venv/Lib/site-packages/pipecat/flows/{types,manager,actions,adapters}.py`; `pipecat/evals/{scenario,judge,persona}.py`; `pipecat/audio/turn/smart_turn/`; `pipecat/turns/`
- (local) `runtime/spatalk/{brain/{flow,prompt,tools,resolve,guard,driver},voice/{pipeline,handlers,processors,steps,observers}}.py`; `docs/reports/tasks/{voice-regression-V1,cost-gap-C1}.md`; `docs/research/{rates.json,research-3-deterministic-flows.md}`; `docs/superpowers/specs/{2026-09-01-ai-front-desk-architecture-design,2026-09-05-slot-engine-design}.md`

**Dialogue management**
- Rasa: https://rasa.com/docs/learn/concepts/dialogue-understanding/ · /docs/reference/primitives/flows/ · /flow-steps/ · /patterns/ · /docs/reference/config/components/llm-command-generators/ · /docs/reference/config/policies/flow-policy/ · /docs/reference/primitives/contextual-response-rephraser/ · https://rasa.com/developer-terms · https://github.com/RasaHQ/rasa (Apache-2.0, no CALM) · PyPI `rasa-pro` 3.19.3 wheel (read; `license: null`)
- Parlant: https://github.com/emcie-co/parlant · https://parlant.io/docs/concepts/customization/{guidelines,journeys,canned-responses} · /docs/engine-internals/journeys · https://arxiv.org/abs/2503.03669 (ARQs)
- NeMo Guardrails: https://github.com/NVIDIA-NeMo/Guardrails · `nemoguardrails/colang/v2_x/library/guardrails.co` · `docs/configure-rails/colang/colang-2/language-reference/flow-control.mdx` · `qa/latency_report_openai.tsv` (2023-11-02)
- Dialogflow CX: https://docs.cloud.google.com/dialogflow/cx/docs/concept/playbook · /playbook/instruction · /playbook/example · /playbook/tool · /concept/handler · /concept/generative-deterministic · /dialogflow/docs/editions
- OpenAI: https://github.com/openai/openai-agents-python · https://openai.github.io/openai-agents-python/{handoffs,guardrails}/ · .../ref/tool_guardrails/ · https://github.com/openai/openai-realtime-agents (`src/app/agentConfigs/chatSupervisor/index.ts`, `chatSupervisorDemo/supervisorAgent.ts`)
- Anthropic: https://www.anthropic.com/engineering/building-effective-agents (2024-12-19) · https://platform.claude.com/docs/en/about-claude/use-case-guides/customer-support-chat · /docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations · /docs/en/docs/build-with-claude/prompt-caching · /docs/en/about-claude/pricing · https://github.com/anthropics/claude-cookbooks
- LangGraph: https://docs.langchain.com/oss/python/langgraph/{overview,interrupts,fault-tolerance} · /langchain/human-in-the-loop · https://raw.githubusercontent.com/langchain-ai/langgraph/0.2.37/docs/docs/tutorials/customer-support/customer-support.ipynb · PyPI `langgraph-api` 0.14.0 (Elastic-2.0)
- LiveKit: https://github.com/livekit/agents (tag `livekit-agents@1.8.1`) · `livekit-agents/livekit/agents/beta/workflows/phone_number.py`, `voice/{agent,agent_activity,turn}.py`, `llm/utils.py` · https://docs.livekit.io/agents/logic/{workflows,supervisor-pattern,turns/turn-detector}/ · /agents/build/audio/ · /agents/multimodality/audio.md · /agents/start/testing/ · /reference/agents/turn-handling-options/ · https://github.com/livekit/agents/pull/6990 · .../tests/test_workflow_readback.py · https://livekit.com/blog/async-tools-voice-agents · https://huggingface.co/livekit/turn-detector/blob/main/LICENSE
- Bolna: https://github.com/bolna-ai/bolna · `bolna/enums.py`, `bolna/agent_types/{graph_agent,extraction_agent}.py`
- Vocode: https://github.com/vocodedev/vocode-core (last push 2024-11-15) · PyPI `vocode` 0.1.113 (2024-06-17)
- TEN: https://github.com/TEN-framework/ten-framework · https://raw.githubusercontent.com/TEN-framework/ten-framework/main/LICENSE (Apache-2.0 + Agora conditions)
- Ultravox: https://github.com/fixie-ai/ultravox · https://huggingface.co/fixie-ai/ultravox-v0_5-llama-3_3-70b · https://www.ultravox.ai/pricing · https://www.ultravox.ai/blog/introducing-ultravox-v0-7-the-world-s-smartest-speech-understanding-model
- Vapi: https://github.com/VapiAI/docs/blob/main/fern/assistants/email-address-reading.mdx · .../fern/static/vapi-prompt-reference.md · https://docs.vapi.ai/workflows/overview · https://vapi.ai/blog/speech-latency
- Retell: https://docs.retellai.com/api-references/create-agent · /build/agent-handbook.md · /build/conversation-flow/extract-dv-node · https://github.com/RetellAI/retell-python-sdk (`src/retell/types/agent_create_params.py`)
- RavenClaw: https://www.isca-archive.org/eurospeech_2003/bohus03_eurospeech.pdf · **recovery-strategy rates: https://aclanthology.org/2005.sigdial-1.14.pdf** (Bohus & Rudnicky, "Sorry, I Didn't Catch That!", SIGdial 2005) · QUD stack: https://semprag.org/index.php/sp/article/view/sp.5.6
- Dialogflow CX parameters and reprompt handlers: https://docs.cloud.google.com/dialogflow/cx/docs/concept/parameter
- Deepgram keyterm ("tretinoin" 0.712 → 0.965): https://developers.deepgram.com/docs/keyterm
- LiveKit prebuilt tasks: https://docs.livekit.io/agents/prebuilt/tasks/get-name/ · https://docs.livekit.io/agents/logic/tasks/ · `beta/workflows/{name,email_address,phone_number,address,credit_card,dob,dtmf_inputs,warm_transfer,task_group,utils}.py`
- AWS NATO decoder: https://github.com/aws-solutions-library-samples/sample-ai-assisted-call-center-agent-training/blob/main/src/agent/tools/verify_spelling.py (MIT-0)

**Turn-taking, barge-in, full duplex**
- https://github.com/livekit/eot-bench · https://huggingface.co/datasets/livekit/eot-bench-data
- https://krisp.ai/blog/voice-ai-turn-taking-interruption-prediction/ · https://krisp.ai/blog/viva-2-0-ai-infrastructure-for-voice-ai-agents/
- https://arxiv.org/abs/2205.15060 (Duplex Conversation, KDD 2022 ADS)
- VAP: https://www.isca-archive.org/interspeech_2022/ekstedt22_interspeech.html · https://arxiv.org/abs/2205.09812 · https://arxiv.org/abs/2401.04868 (real-time) · https://arxiv.org/abs/2503.06241 (IROS 2025 field trial) · https://arxiv.org/abs/2305.17971 (VAP as an eval metric) · https://github.com/{ErikEkstedt/VoiceActivityProjection,ErikEkstedt/TurnGPT,inokoj/VAP-Realtime,MaAI-Kyoto/MaAI} · https://huggingface.co/api/models?author=maai-kyoto
- Backchannels: https://aclanthology.org/2025.naacl-long.367/ · https://arxiv.org/abs/2410.15929 · https://github.com/Linyx1125/MM-F2F · https://arxiv.org/abs/2505.12654 · https://arxiv.org/abs/2607.23204
- Full duplex: https://github.com/kyutai-labs/moshi · https://huggingface.co/kyutai/moshika-rl-seamless (CC BY-NC 4.0) · https://github.com/kyutai-labs/unmute · https://github.com/SesameAILabs/csm · https://github.com/NVIDIA/personaplex · https://docs.livekit.io/agents/models/realtime/plugins/personaplex/ · https://github.com/OpenBMB/MiniCPM-V · https://github.com/QwenLM/Qwen3-Omni · https://github.com/stepfun-ai/Step-Audio2 · https://kyutai.org/stt/ · https://arxiv.org/abs/2606.07547 · https://arxiv.org/abs/2604.21406
- GPU pricing: https://www.runpod.io/pricing · https://lambda.ai/pricing · https://instances.vantage.sh/aws/ec2/g6e.xlarge

**Cost and providers**
- https://ai.google.dev/gemini-api/docs/pricing · /docs/caching · /docs/models/gemini-3.5-flash-lite · https://ai.google.dev/api/caching · https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview.md.txt
- https://developers.openai.com/api/docs/pricing · /api/docs/guides/prompt-caching
- https://soniox.com/pricing · https://soniox.com/docs/stt/concepts/confidence-scores · /docs/stt/concepts/context · https://soniox.com/docs/integrations/pipecat/stt · https://soniox.com/blog/soniox-tts-v2
- https://deepgram.com/pricing · https://developers.deepgram.com/docs/{confidence.md,keywords,numerals} · https://deepgram.com/learn/introducing-flux-conversational-speech-recognition
- https://elevenlabs.io/pricing/api · https://cartesia.ai/pricing · https://docs.rime.ai/api-reference/spell
- https://github.com/aurelio-labs/semantic-router · https://github.com/lm-sys/RouteLLM (last push 2024-08-10) · https://github.com/zilliztech/GPTCache (last push 2025-07-11)

**Evaluation**
- https://github.com/sierra-research/tau2-bench · `src/tau2/metrics/agent_metrics.py` · `src/tau2/user/user_simulator.py` · `data/tau2/user_simulator/simulation_guidelines_voice.md` · `docs/interaction-metrics.md` · `docs/voice-personas.md` · https://arxiv.org/abs/2506.07982 · https://github.com/sierra-research/tau-bench · https://arxiv.org/abs/2406.12045
- https://github.com/MatthewCYM/VoiceBench · https://arxiv.org/abs/2410.17196
- https://github.com/DanielLin94144/Full-Duplex-Bench (**CC BY-NC 4.0**) · https://arxiv.org/abs/{2503.04721,2507.23159,2510.07838,2604.04847}
- https://github.com/confident-ai/deepeval · https://deepeval.com/docs/{metrics-role-adherence,conversation-simulator}
- https://www.promptfoo.dev/docs/providers/simulated-user/ · /docs/red-team/strategies/multi-turn/ · https://github.com/promptfoo/promptfoo/issues/5174
- https://github.com/coval-ai/benchmarks · https://www.coval.ai/products · https://docs.pipecat.ai/pipecat/evals/platforms/coval
- https://hamming.ai/ · https://hamming.ai/resources/testing-livekit-voice-agents-complete-guide
- https://docs.bland.ai/llms.txt · /tutorials/{scenarios,standards,testbed,evals}.md
- https://github.com/gabrielmittag/NISQA · https://arxiv.org/abs/2104.09494 · https://github.com/sarulab-speech/UTMOS22

**Prior evidence carried forward from `research-3-deterministic-flows.md`**
- IFScale https://arxiv.org/abs/2507.11538 · Lost in the Middle https://arxiv.org/abs/2307.03172 · Lost in Multi-Turn https://arxiv.org/abs/2505.06120 · name matching https://www.ml6.eu/en/blog/why-voice-ai-fails-at-name-matching-and-how-we-achieved-96-accuracy

### Marked UNVERIFIED in this memo

Soniox audio-tag vocabulary and whether `[warm]` is honoured (three doc URLs 404'd); Soniox `context`
in streaming and its price; Flash-Lite implicit-cache minimum token count; `LLMSwitcher` context
carry-over across a switch; `speculation_timeout` default (docs 3.0 vs source 5.0); Gemini Flash-Lite
TTFT (the benchmark has Flash, not Flash-Lite); the claim that Pipecat pre-warms Soniox TTS streams
(absent from the CHANGELOG); Pipecat 1.8.1 → 1.9.0 breakage against our `PipelineWorker`/`LLMContext`
usage; promptfoo's simulated-user model override (a negative from one docs page); semantic-router
latency; Colang 2.0 latency; VAP backbone parameter count; ultraVAD parameter count and licence;
Ultravox v0.7 weights licence and its "~150 ms TTFT" claim; Cartesia `<spell>` grouping (login-walled);
Cartesia STT per-minute pricing; Google Cloud TTS pricing; Bolna's graph authoring schema; TEN's
dialogue model and whether the TEN VAD / Turn Detection repos carry a cleaner licence; Coval's pricing
tiers; Hamming's "95–96% agreement with human evaluators"; Anthropic customer-support *architecture*
guide (not found); UTMOS22's predicted outputs; MOSNet (no authoritative repo located). The
`VADUserTurnStartStrategy` recommendation in §8.4(d) is reasoned from source and has not been run.
Krahmer et al. 1999 (the explicit/implicit confirmation lineage) was not read. Rasa Developer Edition
usage caps (terms page 404s). Retell's `boosted_keywords` limit and the text its handbook toggles
inject (deliberately unpublished). AssemblyAI's keyterm price at source (only Vapi's $0.04/hr
figure). Lighter semantic-cache alternatives and any published false-positive rate. LiveKit model
routing (no example found). Whether Pipecat checks that `say(text=, audio=)` agree.

One arithmetic note for a reader comparing against the research transcripts: parts of the underlying
cost research assumed 7 model turns a minute and FX 1.37. Every figure in §6 of this memo is
recomputed at our own measured 3 turns a minute and FX 1.3896 from `docs/research/rates.json` and
`docs/reports/tasks/cost-gap-C1.md`, so the per-minute numbers here are the ones to quote.
