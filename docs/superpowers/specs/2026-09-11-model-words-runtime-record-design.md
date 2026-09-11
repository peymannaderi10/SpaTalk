# Model Words, Runtime Record: a decision memo

> Status: **synthesis of two research surveys, written 2026-09-11 for the founder's decision. No code follows from this memo until the founder chooses among the decisions in §7.** It supersedes the reading of the slot-engine spec (`2026-09-05-slot-engine-design.md`) that made every caller-facing question a tenant script, and it keeps everything else in that spec.

Sources: `docs/research/2026-09-11-human-receptionist-oss-survey.md` (open-source projects and frameworks, 1,538 lines) and `docs/research/2026-09-11-human-receptionist-literature.md` (papers and industrial research 1997–2026, 1,873 lines). Section numbers below cite them as OSS §n and LIT §n.

## 1. What is going on

The founder's words after the 2026-09-11 01:40 call: "it seems like we're moving towards an answering machine instead of a conscious human style receptionist with reason."

On 2026-09-05 the slot engine moved three things into the runtime at once: **the record** (which slots exist, what values are legal, when a request may be filed), **the transitions** (which slot is open next), and **the words** (one fixed question per step, spoken verbatim, the model forbidden to ask anything). The first two fixed the reliability failures of that week. The third is the answering machine. On the 01:40 call the model, offered only the service step's tools and told not to ask questions, had no way to answer "what was the facial one again?" and put the words into `choose_service`; the resolver matched the generic `facial` entry as exact and moved on (transcript in the conversation record, log analysis in the session of 2026-09-11).

Both surveys, independently, converge on the same shape and on the same diagnosis (OSS §1, LIT §7):

> **The runtime owns the record and the transitions. The model owns the words and the repairs.**

The evidence says the runtime must keep the transitions too. Genie Worksheets (ACL 2025, n=62) lifted goal completion from 21.8% to 82.8% by taking the policy away from GPT-4 with function calling and leaving it parsing and wording; τ-bench loses 22.4 points when the domain policy leaves the prompt; CoDial (2026) gains 22–24 points from putting the flow in code with the same model (LIT §1.2). So the earlier hypothesis "the model decides the next question" is rejected, and the slot engine's core was right. What has to change is narrower and cheaper than a rewrite: the words, the side-question path, and the repair strategy.

## 2. The design in one table

| Concern | Today (slot engine) | After this memo | Evidence |
|---|---|---|---|
| Which slot is open | runtime `next_step()` | unchanged | LIT R1 |
| Legal values, closed fields, `draft_from` | runtime | unchanged | LIT R2, CLAUDE.md 2 |
| Outcome, disclosure, clinical, complaint, payment, goodbye sentences | `scripts.yaml`, verbatim | unchanged | CLAUDE.md 3 |
| The question the caller hears | `scripts.yaml`, verbatim, appended to every tool result | **model-worded** from a readiness report; the script is the fallback for a silent model turn and for the "trouble" mode | LIT R1, E2E NLG; OSS §8.2, §8.4(f) |
| A side question mid-step | impossible; forced into the step tool | **always-live `answer_question` tool**: no arguments, writes nothing, pushes a digression frame, hands the turn to the model | OSS §8.3(a), Flows `global_functions`; LIT R6 |
| Returning after the side question | n/a | runtime pops the frame and tells the model "you were about to ask which treatment"; filled slots are skipped, not re-asked | LIT R6, Grosz & Sidner; OSS §8.1(c) |
| A resolver result | verdict (`exact` writes the slot) | **candidates plus confidence**, visible to the model as tool-result data; `exact` still writes when lexical and ASR confidence agree; anything else is offered, in the model's words | LIT R2; OSS §8.1(b), §8.3(d) |
| A miss | the same fixed question again | **ladder**: grounded offer ("did you mean the MesoJet?") → read the closed list, at most three → move on and come back; the same script key never fires twice in a row on an unchanged record | LIT R3, R5, Dingemanse; OSS §8.1(g), Bohus & Rudnicky 64.4% vs 49.2% |
| An un-offered or premature tool | silently ignored, retry counter | **rejection the model can read** as the tool result, naming what is missing and the legal choices | OSS §8.1(e), Parlant `ToolInsights` |
| A name or number the STT was unsure of | stored as heard | confirmation driven by **per-token STT confidence** already on `TranscriptionFrame.result`; a low-confidence entity word confirms, a high-confidence filler ("Um") is not an answer | OSS §8.4(b); LIT R7 |
| When trouble mounts | n/a | **trouble score** from `misses`, ignored tools, repeats, barge-in-and-repeat; above threshold the runtime speaks scripts verbatim and confirms every slot, and the call escalates to Flash for the remainder | LIT R9 (Litman & Pan, the only deployed comparison), R11 |
| Persona | warm tags everywhere | warmth stays on booking; complaint and payment paths drop tags and small talk; reuse the caller's own word for a treatment | LIT R10 |
| Order of the opening | returning? → offers → what | **reason for the call first**, then returning and offers | LIT R8, Schegloff |

Nothing in `ItemDraft`, `draft_from`, `guard()`, the renderer, the rules gate, Tier C, `BusinessCalendar` or the provider factories changes (OSS §8.6).

## 3. The guard gets more important, not less

When the model words the questions, `OutputGuardProcessor` is the only thing between a "confidently phrased" model and a false claim, which is the one place the literature warns the hypothesis is dangerous (LIT §8: ReAct-TOD agents scored higher on satisfaction and lower on success). Three changes go in with the first phase, before any question is model-worded (OSS §8.4(g)):

1. One private egress function is the only path to TTS, with `guard()` inside it and a guard-owned re-entrancy flag; no `skip_guard` parameter anywhere.
2. The lexicon rejects outcome-implying stalls ("let me book that for you") as well as outcome claims.
3. Receipt-or-retract: an utterance asserting an outcome must name an item the ledger issued in this conversation, or it is replaced by the script.

Then the trailing-question suppression from `voice-regression-V1` is relaxed, because it was right for a runtime that asked its own question on top and is wrong once the model owns the question.

## 4. Turn-taking and latency, separately

The founder's ear hears three things as one: talk-over, slow replies, and canned words. The surveys separate them. Gaps at or over 700 ms are heard as reluctance (Levinson & Torreira); a field experiment moving 2.14 s to 1.15 s raised perceived smoothness significantly; fillers do not help at 1.5 s (LIT R4). SpaTalk's 1.31 s median is deployed state of the art and outside the human range. Work items, none of which touch the dialogue design:

- Capture `TurnMetricsData` in `observers.py` (OSS §8.4(a)). We have no data on how often Smart Turn returns incomplete or how often the 1.5 s fallback fires, and the V1 report correctly refused to tune that from a desk.
- Re-score Smart Turn during the silence and cap the fallback rather than paying a flat 1.5 s.
- `text_aggregation_mode=TOKEN` on the Soniox TTS service, A/B on one call (prosody is the risk).
- `VADUserTurnStartStrategy(enable_interruptions=False)` ahead of the three-word barge-in gate: instant turn start when the bot is silent, barge-in still gated. Reasoned from source, not run; a call test.
- SLOs: p50 ≤ 600 ms, p95 ≤ 1,000 ms perceived gap.

## 5. Cost

All figures CA$ per call minute on the corrected meter (`cost-gap-C1`): all-in 0.0355, model 0.0044, TTS 0.0094, floor 0.0208, price for 65% margin 0.0994.

| Change | Δ per minute | Note |
|---|---|---|
| `answer_question` and model-worded questions | ≈ 0 | same one model call per turn; a few hundred more output tokens |
| A dedicated small classifier call (yes/no fast path) | +0.0007 | latency lever, not a margin lever (LIT §5.3) |
| One extra Flash-Lite call every turn at full prompt | +0.0056 | 64.3% → 58.6% margin at 0.0994; avoid |
| Every turn on 3.5 Flash | +0.0218 | margin to 42%; do it only on the trouble score |
| Gemini explicit context cache on the static bundle | −0.002 to −0.004 | needs the volatile step brief out of the system message (cost-gap-C1) |
| **Pre-render fixed scripts to audio at bundle build** | **−0.0024 to −0.0038** | largest single win in either survey; fixed lines are 25–40% of spoken characters; also removes the TTS handshake from the disclosure (OSS §6.4, §8.4(e)) |

Conclusion of both surveys: cost is not the constraint, reliability is. Spend on structure and caching; escalate the model on structural signals, never on its self-reported confidence (LIT R11).

## 6. Evaluation gate

Anthropic's rule, adopted: add complexity only when it demonstrably improves outcomes. Before the fixed questions come out (OSS §8.5, LIT §6.6):

1. Rung 0, free: log repeats, re-prompts, repairs, ignored tools and barge-in-and-repeat as first-class events on every call. These predicted satisfaction in deployed systems (LIT §6.3) and are the trouble score's inputs.
2. Pipecat 1.9 simulations in `runtime/scenarios/` with the τ²-bench MIT voice persona guidelines, one scenario per flow, `runs: 3`, pass^k at k=1..3, function-call assertions with `calls: []` on every refusal, a local Ollama judge. Assert intent, never a script's exact wording.
3. Run both architectures through the same suite, with the four failures every surveyed project actually has: a paraphrased outcome claim, a neutral stall that leaks an outcome, a digression that loses the open request, a duplicate file after a retry.
4. Founder call rounds are smoke tests: a stable naturalness verdict needs more than 30 listeners (Wester et al.).

## 7. Decisions for the founder

1. **Adopt "runtime owns record and transitions, model owns words and repairs"** as the target, replacing slot-engine invariant 4 ("every question is a tenant script") with "every outcome sentence is a tenant script; every question realises the act the runtime named." Recommended: yes.
2. **Phase order.** Recommended: (A) guard hardening + `answer_question` + readable rejections + stop appending `next_question()` to every tool result, with rung 0 logging, because this alone fixes the 01:40 call; (B) candidates-not-verdicts, the repair ladder, the digression stack, STT confidence; (C) trouble score with script-verbatim mode and Flash escalation; (D) turn-taking items and pre-rendered scripts; (E) simulations and the comparison gate. A and B are about the size of the slot engine itself; C to E are each a day or two.
3. **Opening order**: reason for the call before "have you been in before?" Recommended: yes; it is a flow-table change.
4. **Pre-rendered script audio** at bundle build: recommended yes in phase D; it is the largest cost item and needs a tenant-bundle format decision (audio files keyed on rendered text, never covering a line with caller data).
5. **Model**: stay on Flash-Lite; Flash only via the trouble score. Recommended: yes.
6. **Whether the interim fix for the 01:40 call ships before the demo** on the current engine (answer path, question-shaped utterances refused as answers, generic category entries resolve to a kind, no re-ask on a fragment). It is phase A's first half and is not wasted work.

## 8. What the evidence does not settle (LIT §9)

Whether naturalness pays in task success at all, as opposed to satisfaction; where the trouble-score threshold sits for this caller population; whether Smart Turn re-scoring closes enough of the gap without endpoint anticipation; whether Flash-Lite's multi-turn unreliability is tolerable once the runtime holds the record. Each is a measurement, not a debate, and rung 0 makes all of them measurable on our own calls.
