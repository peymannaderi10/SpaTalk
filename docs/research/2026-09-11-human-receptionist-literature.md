# Literature survey: a human-style receptionist that still keeps the ledger

Date: 2026-09-11. Scope: academic and industrial **research** literature, roughly 2018–2026, with
the canonical older work where it is still the best evidence. A sibling survey covers open-source
projects; this one deliberately does not duplicate it.

Question under test, in the founder's words: *"a more normal human interaction like experience with
an ai receptionist"* while *"keeping our costs low and margin great."* Hypothesis under test:
**"the model leads the conversation and the runtime holds the record"** — the LLM is the dialogue
manager (own words, handles digressions and clarifications, decides the next question) and code
enforces only invariants (resolvers return candidates not verdicts, a readiness check refuses to
file until required fields exist and says what is missing, the guard, the outcome scripts, closed
item fields).

Every citation below was checked against a primary source (arXiv abstract page, ACL Anthology, ISCA
archive, Crossref, PLOS, a publisher page, or the vendor's own documentation) on **2026-09-11**.
Anything that could not be verified is marked **UNVERIFIED** in place. Evidence grades used
throughout: *deployed field experiment* > *controlled user study* > *benchmark* > *corpus study* >
*vendor claim with data* > *position paper / blog without data*.

---

## Executive summary

1. **Policy in code, language in the model.** Genie Worksheets (ACL 2025, n=62 users) lifted goal
   completion from **21.8% to 82.8%** by taking the policy away from GPT-4-Turbo-with-function-calling
   and leaving it only two jobs: parse the user, and *generate the wording*. CoDial (2026) reproduces
   the effect within one model: the same GPT-4o-mini scores **58.5 vs 36.6 F1** on STAR with
   structured policy code versus free-form generated logic. Structure buys more than a model tier does.
2. **Never let the model hold the record, and never let a resolver commit on a guess.** Laban et al.
   (2025) measure a **39% average drop** from single- to multi-turn across 15 models, decomposed as
   −16% aptitude and **+112% unreliability**, with the named mechanism *"LLMs often make assumptions in
   early turns and prematurely attempt to generate final solutions… when LLMs take a wrong turn in a
   conversation, they get lost and do not recover."* That is the 2026-09-05 failure verbatim.
3. **Repair with the most specific move you can afford, and never twice the same way.** Dingemanse et
   al. (PLOS ONE 2015; 12 languages, 2,053 cases) show humans prefer a *restricted offer* ("Did you
   mean the MesoJet?") over a *restricted request* over an *open request*, and repair roughly **once
   every 1.4 minutes** — normal, not broken. PARADISE (ACL 1997) prices the alternative: its fitted
   model is `0.40·task-success − 0.78·repair-utterances`, explaining **92% of satisfaction variance**.
   A verbatim re-ask costs about twice what a task success earns.
4. **Shorten the gap; do not paper over it.** Human turn transitions cluster at a **0 ms mode / +208 ms
   mean** (Stivers et al., PNAS 2009), and gaps **≥700 ms are heard as reluctance** (Levinson &
   Torreira 2015). A deployed field experiment (Inoue et al., IROS 2025) cut response time
   **2.14 s → 1.15 s** and moved "smooth conversation" **4.67 → 6.13 (p=.007)** with behavioural
   metrics flat. SpaTalk's 1.31 s median sits inside that interval; fillers measurably do **not** help
   at 1.5 s (Maslych et al., CUI 2025).
5. **Be human in the mechanics, not in the persona.** Word entrainment on the caller's own vocabulary
   predicts perceived naturalness *and* correlates with task success (Nenkova et al., ACL 2008), while
   AI "relational talk" untied to the caller's goal measurably **reduces** satisfaction through
   perceived awkwardness across four experiments (Dharmaputri et al., 2026), and anthropomorphism
   *hurts* with angry customers (Crolic et al., J. Marketing 2022).
6. **Where the hypothesis is wrong:** the clause *"decides the next question."* Three independent
   measurements say the model must not own that decision — Genie's 21.8% baseline, τ-bench's
   **−22.4-point** drop on airline when the domain policy is removed from the prompt, and CoDial's
   +22 to +24 points from putting the flow in code. Handing the next-step decision to a Flash-Lite-class
   model is the one part of the hypothesis the literature contradicts outright.
7. **Where the hypothesis is unproven:** that naturalness pays. The only study that measures both axes
   at once (Elizabeth et al., ReAct-TOD 2024/25) found LLM-led agents *"severely underperform… on
   success rate in simulation"* while *"humans report higher subjective satisfaction… thanks to its
   natural and confidently phrased responses."* Satisfaction and task success dissociate, and
   "confidently phrased" is precisely SpaTalk's structural-honesty hazard.
8. **The refined hypothesis that the evidence does support:** *the runtime decides which slot is open
   and what may be written; the model decides how the turn sounds, when to answer a side question
   first, and which words to use.* AnyTOD's symbolic program *recommends* the next action and the LM
   realises it; DiactTOD controls at the **dialogue-act** level, not the sentence level; the E2E NLG
   Challenge (62 systems, human ratings) found generated wording wins on naturalness while authored
   wording wins on semantic accuracy. Keep outcome sentences scripted; let questions be worded.
9. **Cost is not the constraint; reliability is.** CA$0.064/min of headroom is **14.5×** the whole LLM
   line, and Gemini's published context-cache discount (**$0.30 → $0.03/M input**) roughly pays for a
   Flash-Lite → Flash upgrade. But the literature says a tier upgrade buys the ~16% aptitude component
   and almost none of the +112% unreliability component, so spend on caching, on structure, and on a
   Flash *escalation* triggered by structural signals — never on the model's self-reported confidence.
10. **Measure it the cheap way or not at all.** Report **pass^k**, not a mean (τ-bench's gpt-4o: 61.2%
    pass^1 → ~25% pass^8); define breakdown as *"a human had to rescue this call"* (MultConDB, NAACL
    2024 Industry, deployed healthcare phone agent, F1 69.27); log repeats and re-prompts as
    first-class metrics; and accept that **>30 listeners** are needed for a stable MOS naturalness
    verdict (Wester et al., Interspeech 2015), so a 20-call founder round is a smoke test, not evidence.

---

## 1. Task-oriented dialogue with LLMs: who holds the policy?

The question SpaTalk is asking — should the model decide the next question, or the runtime? — is
the most-measured question in this literature, and the answer is consistent across a decade of
papers: **the record and the policy belong in code; the words belong in the model.** What is new
in 2024–2026 is that the failure mode of giving the model the policy has been characterised
precisely enough to design against, and the failure mode of taking the language away from the
model has been measured too.

### 1.1 The LLM is a weak state tracker and a strong speaker

**Hudeček & Dušek, "Are Large Language Models All You Need for Task-Oriented Dialogue?", SIGDIAL
2023, pp. 216–228.** Instruction-tuned LLMs were evaluated on the standard TOD benchmarks. Verbatim
from the abstract: *"in explicit belief state tracking, LLMs underperform compared to specialized
task-specific models. Nevertheless, they show some ability to guide the dialogue to a successful
ending through their generated responses if they are provided with correct slot values."* The
zero-shot MultiWOZ 2.2 JGA floor they measure is stark — **0.02 (Alpaca-LoRA-7B), 0.05
(Tk-Instruct-11B), 0.01 (OPT-IML-30B), 0.13 (ChatGPT)** against **0.60** supervised — and handing an
11B model the *oracle* belief state instead of making it track lifts SGD few-shot success
**0.19 → 0.46**. **Evidence: benchmark.** *Implication:* this is the single paper that licenses the
hypothesis in its refined form and forbids it in its naive form. The model may guide the dialogue —
*if it is handed a correct slot record*. `Slots` must stay authoritative and must be shown to the
model every turn. A version of "the model leads" in which the model also remembers what has been
collected is directly contradicted here.

**Li, Chen, Ross, Huber, Moon, Lin, Dong, Sagar, Yan & Crook, "Large Language Models as Zero-shot
Dialogue State Tracker through Function Calling" (FnCTOD), ACL 2024, pp. 8688–8704.** Recasting DST
as function calling — domain schemas converted to function specifications in the system prompt,
function calls emitted alongside the response — lifts zero-shot DST enough that *"various 7B or
13B parameter models … surpass the previous state-of-the-art (SOTA) achieved by ChatGPT"*, and
improves ChatGPT itself *"by 5.6% average joint goal accuracy (JGA)"*, with GPT-3.5 and GPT-4
boosted 4.8 and 14.0. **Evidence: benchmark.** *Implication:* the tool-call interface SpaTalk
already uses (`choose_service(said=…)`, `give_name(first_name=…)`) is the evidence-backed way to get
state out of a small model, and the 7B/13B result is the strongest single datum that a
Flash-Lite-class model is not disqualified *as an extractor*. Keep the schema compact and per-step;
that is what FnCTOD does.

**Dey, Sun, Tur & Hakkani-Tür, "Know Your Mistakes: Towards Preventing Overreliance on
Task-Oriented Conversational AI Through Accountability Modeling", ACL 2025 Main.** An
"accountability head" — a binary classifier over which slots were actually mentioned — detects DST
errors, which the decoder then self-corrects: JGA rises *"from 67.13 to 70.51"*, state of the art on
MultiWOZ. The second result matters more here: *"error correction through user confirmations
(friction turn) achieves a similar performance gain."* **Evidence: benchmark across multiple
backbones.** *Implication:* two rules. First, the ceiling is low — best-in-class joint goal accuracy
is about 70%, so roughly three dialogues in ten carry a wrong slot somewhere; a receptionist that
files items must confirm, not trust. Second, a confirmation turn is *as good as* an internal
self-correction, so the cheap mechanism (ask) is the right one. SpaTalk's `confirm_match` /
`confirm_phone` are the literature's own answer, and the readiness check in the hypothesis should be
allowed to **demand a confirmation turn**, not merely report a missing field.

### 1.2 The hybrids, and the one number that should decide this

**Joshi, Liu, Chen, Weigle & Lam, "Controllable and Reliable Knowledge-Intensive Task-Oriented
Conversational Agents with Declarative Genie Worksheets", ACL 2025 (arXiv:2407.05674).** Genie is a
declarative spec executed by *"an algorithmic runtime system that implements the developer-supplied
policy, limiting LLMs to (1) parse user input using a succinct conversational history, and (2)
generate responses according to supplied context."* In a user study with **62 participants** across
Yelp restaurant reservation, university ticket submission and course enrolment: *"Genie agents with
GPT-4 Turbo outperformed the GPT-4 Turbo agents with function calling, improving goal completion
rates from 21.8% to 82.8%."* **Evidence: controlled user study (n=62) plus benchmark — the strongest
hybrid evidence in this survey.** *Implication:* 21.8% is what "the model leads and holds its own
record" measures at, with a frontier model, on tasks no harder than booking a medspa appointment.
But read the other half of Genie's design: the runtime owns the policy and the LLM **generates the
responses**. Genie is not a script reader. This is precisely "policy in code, language in the model",
and it is the shape SpaTalk should converge on — which means the slot engine was right about the
order of the questions and wrong about speaking them verbatim.

**Zhao, Cao, Rastogi et al., "AnyTOD: A Programmable Task-Oriented Dialog System", EMNLP 2023.**
Neuro-symbolic: *"a neural LM keeps track of events occurring during a conversation and a symbolic
program implementing the dialog policy is executed to recommend next actions."* SOTA on STAR, ABCD
and SGD with strong zero-shot transfer. **Evidence: benchmark.** *Implication:* note the verb — the
program *recommends*; the LM realises. A `next_step()` that returns a recommendation the model may
phrase, reorder within a turn, or defer for one turn to answer a question is faithful to this
architecture; a `step_question()` whose output is spoken byte-for-byte is not.

**Zhang, Peng, Li, Zhou & Meng, "SGP-TOD: Building Task Bots Effortlessly via Schema-Guided LLM
Prompting", Findings of EMNLP 2023, pp. 13348–13369.** Three components — the LLM, a *DST Prompter*,
and a *Policy Prompter*, with policy supplied as schema rules — reach zero-shot MultiWOZ 2.0
**Inform 83.88 / Success 69.87 / Combined 85.97** on a 2023-era GPT-3.5, against **42.4 Combined**
for few-shot ChatGPT, and match a fine-tuned model on STAR next-action prediction (F1 50.84 vs
49.82). New functionality is added *"by merely adding supplementary schema rules."* **Evidence:
benchmark.** *Implication:* express the booking policy as data (the step table, already in
`flow.py`) and hand the model the *current rule* rather than the whole rulebook. `step_message` is a
Policy Prompter; the gain comes from the policy being a schema, not from the question being unspoken.

**Shayanfar, Luo, Bhambhoria, Dahan & Zhu, "CoDial: Interpretable Task-Oriented Dialogue Systems
Through Dialogue Flow Alignment", arXiv:2506.02264 (v3, 2026).** The controlled experiment this
survey most needed: the *same* GPT-4o-mini agent, with structured Colang guardrail code versus
free-form generated logic, scores **58.5 vs 36.6 F1 on STAR (+21.9)** and **60.1 vs 36.1 accuracy
(+24.0)**; with the structure in place a mini-tier agent reaches MultiWOZ Inform 76.6 / Success 54.6.
**Evidence: benchmark.** *Implication:* the recoverable delta from code-side structure is larger than
the delta a model-tier upgrade buys, and it compounds with the tier rather than competing with it.

**Wu, Gung, Shu & Zhang, "DiactTOD: Learning Generalizable Latent Dialogue Acts for Controllable
Task-Oriented Dialogue Systems", SIGDIAL 2023.** Dialogue acts in a latent space, predicted and
*controlled* to steer generation, SOTA on MultiWOZ zero-shot/few-shot/full. **Evidence: benchmark.**
*Implication:* the control point that preserves naturalness is the **act**, not the sentence. "Ask
for the first name" is an act; "Could I get your first name?" is one realisation of it. Constrain
the act per step; let the realisation vary.

**Google Cloud, "Generative versus deterministic" (Dialogflow CX / Conversational Agents docs).**
Three modes — fully generative playbooks, deterministic flows where *"LLMs [are used] only for
understanding user intent"*, and a hybrid where flows carry optional generators — with the hybrid
advised where response wording must be governed. **Evidence: vendor guidance, no data.**
*Implication:* corroboration only, but useful: the largest commercial vendor in this space sells the
hybrid and keeps *understanding* generative while keeping *wording* deterministic on high-stakes
turns. SpaTalk's split (scripts for outcomes, model for everything else) matches.

**Robino, "Conversation Routines: A Prompt Engineering Framework for Task-Oriented Dialog Systems",
arXiv:2501.11613 (Jan 2025).** Structured prose sections in the prompt — roles, core functions,
conversational flow, behaviour rules, error handling — with two proof-of-concept agents. **Evidence:
position paper with demos; no benchmark, no user study.** *Implication:* the best-articulated version
of the architecture SpaTalk had before 2026-09-05 and abandoned for cause. Its evidence base is two
demos, against Genie's 62-participant study.

### 1.3 Why the model cannot be trusted with the record: four 2024–2026 results

**Laban, Hayashi, Zhou & Neville, "LLMs Get Lost In Multi-Turn Conversation", arXiv:2505.06120
(May 2025).** 200,000+ simulated conversations, six generation tasks, sharded under-specified
instructions delivered turn by turn. *"All the top open- and closed-weight LLMs we test exhibit
significantly lower performance in multi-turn conversations than single-turn, with an average drop of
39%"*, decomposed into **−16% aptitude and +112% unreliability**; *"more performant models (Claude
3.7 Sonnet, Gemini 2.5, GPT-4.1) get equally lost… compared to smaller models (Llama3.1-8B-Instruct,
Phi-4), with average degradations of 30-40%."* The mechanism is named exactly: *"LLMs often make
assumptions in early turns and prematurely attempt to generate final solutions, on which they overly
rely… when LLMs take a wrong turn in a conversation, they get lost and do not recover."* Reasoning
tokens do not help; ~30% unreliability survives temperature 0. **Evidence: large-scale simulation
benchmark across 15 model families.** *Implication:* a textbook description of the 2026-09-10
failure. The caller asked "what was the facial one again?"; the model made an assumption, committed
it to `choose_service`, and did not revisit it. The rule that follows is not "trust the model less"
but **"make premature commitment structurally impossible"**: resolvers return candidates plus a
confidence, never a verdict; a slot is written only on an explicit confirmation or an unambiguous
exact match; and `change_answer` must work on a slot that holds nothing, because recovery from a
wrong turn is exactly what models do not do unaided.

**He, Zhang, Wang et al. (Meta), "Multi-IF: Benchmarking LLMs on Multi-Turn and Multilingual
Instructions Following", arXiv:2410.15553 (Oct 2024).** Instruction adherence degrades monotonically
with turn count — *"even o1-preview drops from 88% to 71% accuracy between the first and third
turns"* — a pattern the authors call instruction forgetting, with worse degradation in non-English.
**Evidence: benchmark.** *Implication:* any invariant expressed as a standing prompt instruction
decays across a three-minute call. Invariants must be enforced by the tool list and the guard, per
turn, not by a sentence in the system prompt.

**Jiang, Wang, Luo et al., "FollowBench: A Multi-level Fine-grained Constraints Following Benchmark
for Large Language Models", ACL 2024, pp. 4667–4688.** Constraints are added one at a time to the
same instruction across five types (content, situation, style, format, example); 13 LLMs evaluated;
the headline is the weakness of instruction following as constraint count rises. **Evidence:
benchmark.** *Implication:* the prompt budget is a constraint budget. Every new prose rule in
`build_system_prompt` costs adherence to the existing ones. Prefer deleting a rule and enforcing it
in code.

**Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni & Liang, "Lost in the Middle: How Language Models
Use Long Contexts", TACL 12:157–173, 2024.** Performance is highest when relevant information sits
at the beginning or the end of the context and degrades substantially in the middle. **Evidence:
benchmark.** *Implication:* validates the slot engine's original diagnosis (fifteen booking bullets
mid-prompt in a ~5,400-token prompt) and dictates where the per-turn brief goes: **last**. It also
explains the 5-of-13 prompt-cache misses in the V1 regression report — the cost of a volatile suffix
— and says pay it.

**Dongre, Hsieh, Lai, Yoon, Bui & Hakkani-Tür, "When Attention Closes: How LLMs Lose the Thread in
Multi-Turn Interaction", arXiv:2605.12922 (May 2026).** Introduces a Goal Accessibility Ratio
measuring attention flow from generated tokens back to goal-defining tokens; forcing attention
closure in Mistral *"reduced fact retention from near-perfect performance to 11% on a 20-fact
task"*, while linear probes on the residual stream predicted recall at AUC up to 0.99 — the goal is
still *represented* but no longer *attended*. **Evidence: mechanistic study with causal ablation.**
*Implication:* re-assert the open goal in the live turn rather than relying on it being "in context".
A short, late, literal restatement of Known/Open each turn is the cheapest known intervention, and it
should name the open question in words, not just a step enum.

### 1.4 The evidence that cuts the other way

**Elizabeth, Veyret, Couceiro, Dušek & Rojas-Barahona, "Exploring ReAct Prompting for Task-Oriented
Dialogue: Insights and Shortcomings", arXiv:2412.01262 (Dec 2024, rev. Mar 2025).** ReAct-style
LLM-driven TOD, evaluated in simulation *and with real users*: *"While ReAct-LLMs severely
underperform state-of-the-art approaches on success rate in simulation, this difference becomes less
pronounced in human evaluation. Moreover, compared to the baseline, humans report higher subjective
satisfaction with ReAct-LLM despite its lower success rate, most likely thanks to its natural and
confidently phrased responses."* **Evidence: simulation benchmark plus human evaluation — the only
source found that measures both axes of the founder's tension in one study.** *Implication:* this is
the paper to hand the founder. His ear is not wrong: an LLM-led agent *is* more satisfying to talk
to even when it completes fewer tasks. It also names the hazard in the same clause — "confidently
phrased" — which for SpaTalk is the structural-honesty risk the `guard()` exists to cover. The
synthesis is not to pick a side: **buy the satisfaction from the phrasing and the success rate from
the runtime**, and keep the guard tight, because the phrasing that wins is the confident kind.

**Dušek, Novikova & Rieser, "Evaluating the State-of-the-Art of End-to-End Natural Language
Generation: The E2E NLG Challenge", Computer Speech & Language 2020 (arXiv:1901.07931); "Findings of
the E2E NLG Challenge", INLG 2018.** 62 systems from 17 institutions, including template and
grammar-based entries: *"seq2seq systems generally score high in terms of word-overlap metrics and
human evaluations of naturalness"*, but *"vanilla seq2seq models often fail to correctly express a
given meaning representation if they lack a strong semantic control mechanism applied during
decoding"*, and *"seq2seq models can be outperformed by hand-engineered systems in terms of overall
quality, as well as complexity, length and diversity of outputs."* **Evidence: shared task with
human ratings at scale.** *Implication:* the clean division of labour. Generated wording wins on
*naturalness*; authored wording wins on *semantic accuracy*. Therefore questions and acknowledgements
are generated (naturalness is their whole point) and outcome sentences stay authored (semantic
accuracy is theirs). CLAUDE.md non-negotiable 3 survives this literature unscathed; slot-engine
invariant 4 does not.

**Litman & Pan, "Designing and Evaluating an Adaptive Spoken Dialogue System", User Modeling and
User-Adapted Interaction 12:111–137, 2002 (and "Empirically Evaluating an Adaptable Spoken Dialogue
System", UM 1999).** TOOT could vary initiative (system / mixed / user) and confirmation (explicit /
implicit / none). The adaptive version starts user-initiative with no confirmations and switches to
system-directed with explicit confirmations when a learned rule detects the user is having
recognition trouble; it **significantly increased task completion for novice users** and reduced
misrecognised turns and total system turns. **Evidence: controlled system comparison with real
users; small n by modern standards.** *Implication: the single most actionable rule in this section.*
SpaTalk should not choose once between "model leads" and "runtime leads" — it should start every call
model-led and **tighten to runtime-led on evidence**: two resolver misses on a slot, a
barge-in-and-repeat, a rules-gate near-miss, an ignored tool call. That trigger set is already
computable (`slots.misses`, `ignored_tools`, `asked_already`).

**Horvitz, "Principles of Mixed-Initiative User Interfaces", CHI 1999, pp. 159–166; Allen, Guinn &
Horvitz, "Mixed-initiative interaction", IEEE Intelligent Systems 14:14–23, 1999.** The founding
statements: model uncertainty about intent explicitly, weigh the cost of acting wrongly against the
cost of asking, minimise the cost of poor guesses, and let the user invoke or terminate the
automation efficiently. **Evidence: position papers, highly influential.** *Implication:* the
resolver thresholds are a mixed-initiative decision, not a tuning constant — store on high
confidence, offer a candidate on medium, ask on low — and the asymmetry should be explicit: a wrongly
stored `service_id` costs a wasted callback, an extra confirmation costs two seconds.

---

## 2. Clarification, repair and grounding: how humans get back on track

The concrete failure of 2026-09-05 — a caller's side question forced into a slot tool, then an open
re-ask of a question he had already heard — is a *repair* failure, and repair is the best-described
mechanism in all of conversation science. Three findings transfer directly.

### 2.1 Prefer the most specific repair you can afford

**Dingemanse, Roberts, Baranova, Blythe, Drew, Floyd et al., "Universal Principles in the Repair of
Communication Problems", PLoS ONE 10(9):e0136100, 2015.** 12 languages from 8 families, **2,053
repair initiations in 48.5 hours** of conversation — a repair roughly **once every 1.4 minutes** —
with three formats covering a mean 92% (σ 4.5%) of cases: the **open request** ("Huh?"), the
**restricted request** ("Who?"), and the **restricted offer** ("she had a boy?"). The central claim:
*"people choose the most specific repair initiator possible, and the choice is affected by the same
kinds of factors in the same way"*, tied to the principle of least collaborative effort. **Evidence:
large cross-linguistic corpus study — the strongest evidence in this survey for any single
conversational rule.** *Implication, as a ranked ladder:* on a miss, try a **restricted offer** first
("Did you mean the MesoJet one?"), fall back to a **restricted request** ("Which treatment did you
have in mind?"), and never use an **open request** ("Sorry?"). The V1 fix moved "the station one"
from a *baseless* restricted offer down to a restricted request, which is correct as far as it goes;
the better move is a *grounded* restricted offer built from what the caller has heard this call — he
had just been read the offers list, so "the $50 credit one, or the MesoJet?" was available and is
what a receptionist would say. Note also the base rate: **one repair every 1.4 minutes is normal
human conversation.** A three-minute call with two repairs is not broken; a three-minute call with
seven identical re-asks is.

**Schegloff, Jefferson & Sacks, "The Preference for Self-Correction in the Organization of Repair in
Conversation", Language 53(2):361–382, 1977.** The foundational statement that repair is organised by
a preference for *self*-correction: other-initiated repair is delayed, mitigated and withheld where
the speaker can be given room to fix the trouble themselves. **Evidence: canonical
conversation-analytic study.** *Implication:* when the model's understanding is shaky, giving the
caller room ("the MesoJet, was it?") outperforms taking the turn with a system question. It also
argues against firing a fresh fixed question on every fragment: an "Um" or "Well" is the caller
holding the floor to self-repair, and the correct behaviour is to wait, not to re-ask. Fragments
re-triggering the step question is a repair-preference violation, not just a UX wart.

**Skantze, "Exploring human error recovery strategies: Implications for spoken dialogue systems",
Speech Communication 45(3):325–341, 2005.** Human–human route-direction dialogues with one side's
speech corrupted by a recogniser. The finding: when facing recognition trouble, *"a common strategy
is to ask task-related questions that confirm their hypothesis about the situation instead of
signalling non-understanding."* **Evidence: controlled lab study of human behaviour, modest n.**
*Implication:* SpaTalk should have no "I didn't catch that" state at all. Every non-understanding
should be realised as a task-related question that displays the system's current hypothesis — which
is also the shape that keeps the conversation moving and stops the caller repeating himself. This is
the strongest single argument for letting the model *word* the recovery turn: the recovery question
has to be built from the hypothesis, and the hypothesis lives in the conversation.

### 2.2 Error handling belongs in the runtime, not in the flow

**Bohus & Rudnicky, "Sorry, I didn't catch that! An investigation of non-understanding errors and
recovery strategies", 6th SIGdial Workshop on Discourse and Dialogue, 2005, pp. 128–143.** An
empirical comparison of ten non-understanding recovery strategies in a deployed room-reservation
system, with an analysis of how each strategy shapes the user's next turn. **Evidence:
deployed-system corpus study. The PDF would not parse for automated extraction, so the per-strategy
recovery rates are UNVERIFIED here; existence, venue, pages and subject are verified.**
*Implication:* treat "what do we say on a miss?" as a measurable policy with more than two options,
and log which one fired and what the caller did next. SpaTalk currently has exactly one option per
step (`ask_*_again`) and no such log.

**Bohus & Rudnicky, "Constructing accurate beliefs in spoken dialog systems", IEEE ASRU 2005,
pp. 272–277; and "The RavenClaw dialog management framework: Architecture and systems", Computer
Speech & Language 23(3):332–361, 2009.** RavenClaw's central architectural claim is the separation of
a domain-independent dialogue *engine* — which owns error handling, grounding, confirmation and
turn-taking — from a domain-specific task tree authored per application. **Evidence: architecture
paper plus deployed systems.** *Implication:* the direct precedent for "the runtime holds the
record". The lesson SpaTalk has not yet taken is that grounding and confirmation are *engine*
concerns applied uniformly, not per-step scripts written once per slot. One confirmation policy
parameterised by confidence beats nine hand-written `confirm_*` keys.

**Komatani & Kawahara, "Flexible mixed-initiative dialogue management using concept-level confidence
measures of speech recognizer output", COLING 2000, pp. 467–473.** Per-*concept* confidence, rather
than per-utterance confidence, drives whether each recognised concept is accepted, confirmed or
rejected — mixed initiative without the cost of confirming everything. **Evidence: system
evaluation.** *Implication:* the resolver already produces a per-slot lexical score; the missing
input is *recogniser* confidence beside it. A name heard at low ASR confidence should be read back
even on an exact match — which is the open question left by the "payment"/"Peyman" incident — while a
service named at high confidence on an exact match should never be confirmed.

### 2.3 When to ask at all

**Rao & Daumé III, "Learning to Ask Good Questions: Ranking Clarification Questions using Neural
Expected Value of Perfect Information", ACL 2018, pp. 2737–2746.** Ranks candidate clarification
questions by expected value of perfect information — how much the likely answer would change the
system's eventual response. **Evidence: benchmark on StackExchange data, not dialogue.**
*Implication:* the decision rule for a clarification is not "is the slot empty?" but "would the
answer change what gets filed?" A preferred window is worth one question; a practitioner the caller
has already twice declined to name is not.

**Aliannejadi, Zamani, Crestani & Croft, "Asking Clarifying Questions in Open-Domain
Information-Seeking Conversations", SIGIR 2019, pp. 475–484.** Establishes the task and the Qulac
dataset and shows that asking a good clarifying question improves retrieval substantially over not
asking. **Evidence: benchmark with crowdsourced answers.** *Implication:* asking is usually worth it
— the default should be to clarify rather than guess.

**Zou, Sun, Long, Aliannejadi & Kanoulas, "Asking Clarifying Questions: To benefit or to disturb
users in Web search?", Information Processing & Management 60(2):103176, 2023.** A laboratory user
study (**89 participants**) over a sequence of tasks with clarifying questions of varying quality:
always showing every clarifying question is risky and low-quality ones measurably disturb users,
while showing only high-quality ones *"receives better gains with less effort"*; the authors train a
model to predict which to ask. **Evidence: controlled lab user study, n=89.** *Implication:* the
counterweight to Aliannejadi. A clarification whose candidate is weak is worse than no clarification
— which is exactly the "Did you mean Free virtual consultation?" failure, and exactly why the
`shares_a_word` guard in `resolve.py` is the right *kind* of fix. Gate the offer on evidence quality,
and prefer a task question over a bad candidate.

**Zheng, Morgan, Jiang, Rose & Sap, "Useless but Safe? Benchmarking Utility Recovery with User
Intent Clarification in Multi-Turn Conversations", arXiv:2604.27093 (Apr 2026).** CarryOnBench: 398
seed queries, 5,970 simulated conversations, 14 models. Initial-turn need satisfaction 10.5–37.6%;
with clarification, 13 of 14 models approached or exceeded the upfront-disclosure baseline. Three
named failure modes: **utility lock-in** (the model ignores the clarification), **unsafe recovery**,
and **repetitive recovery** (recycling a prior response). **Evidence: simulated benchmark; the
domain is safety-refusal recovery, so transfer is partial.** *Implication:* "repetitive recovery" and
"utility lock-in" are the two behaviours SpaTalk observed on 2026-09-10 under different names, and
they are general properties of models in clarification loops rather than a SpaTalk bug. Both need a
runtime detector: a repeat detector on the assistant side (exists, `asked_already`) and a "did the
record move after the clarification?" check on the slot side.

### 2.4 Returning to the open question after a digression

**Grosz & Sidner, "Attention, Intentions, and the Structure of Discourse", Computational Linguistics
12(3):175–204, 1986.** The canonical model: discourse has a linguistic structure, an intentional
structure of purposes, and an **attentional state** — a stack of focus spaces pushed when a
sub-discourse begins and popped when its purpose is satisfied, which is what makes a digression
recoverable and an interruption interpretable. **Evidence: foundational theory, no experiment.**
*Implication:* the mechanism SpaTalk needs for "what was the facial one again?" is a push/pop, not a
slot write. A side question opens a sub-segment; when it closes, the runtime should hand the model
back the *same* open purpose **plus the fact that it was interrupted** — "you were about to tell me
which treatment" — rather than either re-asking verbatim or losing the thread. The V1 "suppress the
repeat and let the model carry the turn" fix is a one-bit approximation; the full version is a
two-element stack (open step, open side question).

**Clark & Brennan, "Grounding in communication", in *Perspectives on Socially Shared Cognition*, APA
1991, pp. 127–149; Traum & Allen, "A 'speech acts' approach to grounding in conversation", ICSLP
1992, pp. 137–140; Traum, "Towards a Computational Theory of Grounding in Natural Language
Conversation", tech. report 1991.** Grounding is incremental and collaborative: participants work to
a *grounding criterion* sufficient for current purposes, using the least collaborative effort, which
is why acknowledgement tokens and candidate understandings do so much work. **Evidence: theory, with
a computational formalisation in Traum & Allen.** *Implication:* the grounding criterion should be
**per field, set by consequence**. A phone number a human will dial needs explicit read-back; a
preferred time-of-day the team will renegotiate anyway needs none. SpaTalk confirms by *step*,
uniformly; it should confirm by *cost of being wrong*.

### 2.5 What a receptionist call actually looks like

**Schegloff, "Sequencing in Conversational Openings", American Anthropologist 70(6):1075–1095, 1968;
Schegloff & Sacks, "Opening up Closings", Semiotica 8(4):289–327, 1973; Whalen & Zimmerman,
"Sequential and Institutional Contexts in Calls for Help", Social Psychology Quarterly 50(2):172ff,
1987.** Telephone openings run a fixed sequence — summons/answer, identification, greeting — and in
*institutional* calls identification and greeting are compressed so that the caller's first
substantive turn is the "reason for the call"; closings are not simply stopped but *opened up*,
canonically with a pre-closing offer ("anything else?") that either closes the call or admits a new
topic. **Evidence: canonical conversation-analytic studies of real recorded calls, including
emergency service calls.** *Implication:* SpaTalk's greeting (identification + "what can I help you
with today?") and its pre-closing ("Is there anything else I can help with?") are the structurally
correct devices, worth knowing before anyone "improves" them. The rule this literature adds: **the
reason-for-the-call belongs in the caller's first turn**, so a system that opens a flow with "Have
you been in to see us before?" before the caller has stated their business has inverted the
institutional sequence. Ask the qualifying questions *after* the request is on the table.

**A gap, stated plainly.** I could not verify any study on **phonetic confirmation of proper names
and digit strings over a telephone channel** — spelling alphabets, read-back formats, three-three-four
grouping, or when to spell versus repeat. The confidence-driven confirmation literature (Komatani &
Kawahara; Bohus & Rudnicky) covers *whether* to confirm but not the *format* for names on a noisy
line. The "payment"/"Peyman" incident therefore sits in a genuine evidence gap, and the decision —
read the name back at the name step, or accept occasional wrong names — has to be made on cost, not
on citation.

---

## 3. Turn-taking, prosody and latency

### 3.1 End-of-turn and turn-shift prediction

**Ekstedt & Skantze, "TurnGPT: a Transformer-based Language Model for Predicting Turn-taking in
Spoken Dialog", Findings of EMNLP 2020, pp. 2981–2990.** TurnGPT incrementally scores turn-shift
probability after each word, using dialogue context and *pragmatic* completeness rather than
silence. **Evidence: benchmark (no headline metric on the landing page).** *Implication:* a
text-side completeness signal is complementary to Smart Turn's waveform signal. Score "is this a
syntactically and pragmatically complete request?" on the partial transcript and use it to
*shorten* the fallback, never to end the turn on its own.

**Ekstedt & Skantze, "Voice Activity Projection: Self-supervised Learning of Turn-taking Events",
Interspeech 2022, pp. 5190–5194.** VAP trains on unlabelled stereo audio to predict *both*
speakers' future voice activity in bins covering the next 0–200, 200–600, 600–1200 and 1200–2000 ms,
and evaluates four zero-shot tasks including turn-shift and backchannel prediction. **Evidence:
benchmark.** *Implication:* the bin structure is the right telemetry shape. Log, per turn, the
predicted-versus-actual gap in those four buckets; that turns "feels slow" into a distribution.

**Inoue, Jiang, Ekstedt, Kawahara & Skantze, "Real-time and Continuous Turn-taking Prediction Using
Voice Activity Projection", IWSDS 2024 (arXiv:2401.04868).** A CPC plus self- and cross-attention
VAP that runs continuously in real time on CPU; shrinking the input context to **1 second** leaves
prediction accuracy essentially unaffected. **Evidence: benchmark plus system demo.**
*Implication:* a continuous turn-taking predictor is affordable inside the Pipecat process — 1 s of
rolling audio, CPU only — so SpaTalk need not choose between one-shot classification and a hard
timeout.

**Inoue, Jiang, Ekstedt, Kawahara & Skantze, "Multilingual Turn-taking Prediction Using Voice
Activity Projection", LREC-COLING 2024, pp. 11873–11883.** Monolingual VAP does *not* transfer
across languages; a jointly trained English/Mandarin/Japanese model matches monolingual performance
on all three, and the paper includes a pitch-sensitivity analysis. **Evidence: benchmark.**
*Implication:* turn-taking models are language- and prosody-specific. Mississauga callers include
heavy-accent and code-switching speakers; log the end-of-turn score alongside a language or accent
tag, because a model tuned on one population will mis-endpoint another.

**Inoue, Okafuji, Baba, Ohira, Hyodo & Kawahara, "A Noise-Robust Turn-Taking System for Real-World
Dialogue Robots: A Field Experiment", IROS 2025 (arXiv:2503.06241).** The most relevant paper in
this section to the founder's complaint. Deployed in a shopping mall over two days, comparing
cloud-ASR endpointing against a noise-robust VAP hybrid: response time fell from an **average of
2.14 s to 1.15 s** (VAP-only: **0.71 s**). With 71 users per condition for timing and 15 per
condition for ratings, the faster condition scored significantly better on 7-point scales — smooth
conversation **4.67 to 6.13 (p=.007)**, ease of use **5.73 to 6.67 (p=.048)**, expectations met
**5.47 to 6.53 (p=.045)** — with **no significant differences** in interaction time, rephrasing,
collisions or abandonment. **Evidence: deployed field experiment with statistics — the strongest
causal evidence in this section.** *Implication:* SpaTalk's 1.31 s median sits between their two
conditions. Cutting roughly a second produces a large, significant jump in *perceived smoothness*
while behavioural metrics stay flat — so the founder's complaint is real and measurable by
subjective rating, and the fix will **not** show up in call-completion stats. Target the VAP-only
figure: **a median perceived gap of 0.75 s or less**.

**Udupa, Watanabe, Schwarz & Cernocky, "Endpoint Anticipation for Low-Latency Spoken Dialogue",
Interspeech 2026 (arXiv:2606.13450).** Replaces reactive endpoint *detection* with proactive
*forecasting*: end-of-turn anticipated **up to 2.56 s in advance**, speculatively launching the LLM
and TTS on partial context, for a reported **505 ms average latency reduction at 28.4% extra
speculative computation** (about 15% under stricter gating), leaving roughly 690 ms residual.
**Evidence: benchmark.** *Implication:* the cheapest available win. SpaTalk's model TTFB is 0.84 s
median; speculatively firing Gemini on the partial transcript when turn-shift probability crosses a
threshold, then discarding on mismatch, hides most of it. 28.4% more Flash-Lite calls is small
against CA$0.035/min — and a discarded speculative turn must never reach a channel, which the guard
already enforces.

**Inoue et al., "Prompt-Guided Turn-Taking Prediction", SIGDIAL 2025.** Extends VAP with
natural-language prompts so turn-taking behaviour is steerable by conversational intent rather than
fixed by acoustics. **Evidence: benchmark; the quantitative results could not be extracted from the
PDF — UNVERIFIED.** *Implication:* endpointing aggressiveness should be a per-state parameter. A
caller reciting a phone number needs a longer tolerance than one answering "yes".

**Pipecat / Daily, "Smart Turn v3" (blog, 11 Sep 2025) and "Smart Turn v2" (18 Jul 2025); model
card `pipecat-ai/smart-turn-v3`.** v3 is a Whisper-Tiny encoder plus a shallow linear head, int8
QAT, **8M parameters / 8 MB ONNX**, BSD-2, 23 languages. Inference **12.6 ms** on an AWS c7a.2xlarge
CPU, 3.3 ms on an L40S. Accuracy **English 94.31%**, Turkish 97.10%, Chinese 88.57%; v2 reported
*"around 99% accuracy"* on a cleaned English human set. The v3 post states *"A VAD model like
Silero should be used in conjunction with Smart Turn."* **Evidence: vendor blog with benchmark
numbers, no peer review. Neither write-up publishes guidance on the `stop_secs` fallback or the
latency cost of a false "not finished" — UNVERIFIED.** *Implication:* at roughly 94% English
accuracy about 1 turn in 17 is misclassified, consistent with SpaTalk's observed ~15% fallback rate
being dominated by model misses rather than genuinely trailing speech. Do not pay the full 1.5 s on
those turns: the model costs about 13 ms, so re-score during the silence (say at 300 / 500 / 800 ms)
and cap the fallback rather than taking one shot plus a flat timeout. This is the desk-safe version
of the V1 report's open item 1.

### 3.2 Backchannels and fillers

**Leviathan & Matias, "Google Duplex: An AI System for Accomplishing Real-World Tasks Over the
Phone", Google AI Blog, 8 May 2018.** Duplex deliberately inserts disfluencies: *"These are added
when combining widely differing sound units in the concatenative TTS or adding synthetic waits,
which allows the system to signal in a natural way that it is still processing,"* and *"In user
studies, we found that conversations using these disfluencies sound more familiar and natural."* On
timing: *"after people say something simple, e.g., 'hello?', they expect an instant response, and
are more sensitive to latency,"* achieving *"less than 100ms of response latency in these
situations"* by switching to faster low-confidence recognition — and *"in some situations, we found
it was actually helpful to introduce more latency to make the conversation feel more natural."*
**Evidence: blog; the user studies are referenced but never reported.** *Implication:* make latency
**state-dependent** — greeting-adjacent and yes/no turns get an aggressive endpoint and a
pre-rendered opener; complex turns may keep more. And note the risk: *simulated* hesitation is
exactly the behaviour that drew the 2018 backlash, and it is a different thing from a genuine
"one sec" while a tool runs.

**Maslych et al., "Mitigating Response Delays in Free-Form Conversations with LLM-powered
Intelligent Virtual Agents", CUI 2025 (arXiv:2507.22352).** 54 participants, within-subjects Latin
square, latency at **1.5 / 4.0 / 6.5 s** crossed with None / artificial wait indicator / natural
conversational filler. Natural fillers *"significantly improved participants' ratings on (Q1)
Response Time at Medium (4.0s) and High (6.5s) latency levels (p<0.01, p<0.0001, respectively)"*;
artificial indicators did not help at all; and fillers improved *only* perceived response time, not
humanlikeness, competence or engagement. **Evidence: controlled lab user study (n=54), VR-embodied,
not telephone.** *Implication — the honest one:* **no significant filler benefit at 1.5 s**, which
is SpaTalk's regime. Fillers are the wrong fix for a 1.31 s gap; they are insurance for the p95 tail
and for tool-call turns past about 2.5 s. Gate the filler processor on *predicted* response time
exceeding roughly 2.0 s rather than firing on every turn. This also settles the V1 report's note
about `scripts.fillers` being empty: populating it is not the naturalness fix.

**Figueroa, de Korte, Ochs & Skantze, "Mhm... Yeah? Okay! Evaluating the Naturalness and
Communicative Function of Synthesized Feedback Responses in Spoken Dialogue", SIGDIAL 2024,
pp. 544–553.** Transplants the prosody of human feedback responses from US-English *telephone*
conversations onto a target voice, via TTS and via signal processing. TTS feedback was rated more
natural with no significant appropriateness difference — but **did not reliably convey the original
communicative function**. **Evidence: lab perceptual study.** *Implication:* a backchannel's meaning
lives in its prosody, and a text token handed to TTS will not reproduce it. Ship backchannels as a
small set of pre-synthesised clips chosen per function (continuer "mm-hm", acknowledgement "okay",
holding "one sec"), with the wording in tenant `scripts` — consistent with non-negotiable 3.

**Lin, Zheng, Zeng & Shi, "Predicting Turn-Taking and Backchannel in Human-Machine Conversations
Using Linguistic, Acoustic, and Visual Signals", ACL 2025, pp. 15310–15322.** Tri-modal model on the
MM-F2F corpus (773 videos, about 210 h, 51K turn-taking and 22K backchannel labels): turn-taking F1
**0.811**, backchannel F1 **0.906**, versus TurnGPT text-only turn F1 0.745. The ablation matters
for a phone product: **audio-only beats text-only for backchannel (0.805 vs 0.707)** while text-only
beats audio-only for turn-taking (0.747 vs 0.737), and text plus audio reaches 0.783 / 0.894 — video
adds almost nothing. **Evidence: benchmark; explicitly no naturalness user study.** *Implication:*
*where* to place a backchannel is predictable from audio at about 0.89 F1 with no visual channel, so
a phone-only system can do it — but it is a separate model from end-of-turn detection, so do not
overload Smart Turn with it.

**Skantze, "Turn-taking in Conversational Systems and Human-Robot Interaction: A Review", Computer
Speech & Language 67:101178, 2021.** The standard review of turn-taking cues (verbal, prosodic,
breathing, gaze, gesture), end-of-turn detection and interruption handling. **Evidence: review.**
*Implication:* use it as the checklist of what SpaTalk currently ignores — final lengthening and
pitch contour are the cheapest prosodic features to add to an endpoint decision.

### 3.3 Barge-in and interruption handling

This is the thinnest area for peer-reviewed, *measured* thresholds in the window; the useful numbers
are currently in vendor engineering write-ups.

**LiveKit, "Solving unwanted interruptions with Adaptive Interruption Handling", 19 Mar 2026.** An
audio-encoder plus CNN classifier on the user stream, run in the first few hundred ms of detected
speech, using onset shape, duration, pitch and rhythm to separate genuine barge-in from backchannels
and noise. Reported: *"86% precision and 100% recall (at 500 ms overlap speech)"*, *"Rejects 51% of
VAD-based barge-ins"*, faster than plain VAD in **64%** of cases, inference *"in 30 ms or less"*, and
a **median 216 ms** of audio needed to trigger an interruption. **Evidence: vendor blog with data;
no peer review, no independent replication.** *Implication:* this is the direct replacement for
SpaTalk's three-transcribed-word gate, which is why overlap runs 0.23–0.59 s. Two metrics follow:
**overlap duration from speech onset to TTS flush (target under 250 ms)** and **false-interruption
rate** (bot stops where the utterance turned out to be a backchannel or noise). The standing caveat
holds: the system's own audio can re-trigger VAD, so echo handling is a prerequisite before any
threshold is tuned — which is exactly why SpaTalk counts transcribed words downstream of
`scrub_echo` today.

**Strom & Seneff, "Intelligent barge-in in conversational systems", ICSLP 2000.** Pre-dates the
window but is the origin of the asymmetric-cost framing: accepting a spurious barge-in is relatively
cheap because it leads to a clarification sub-dialogue, whereas missing a real one is not.
**Evidence: early system paper.** *Implication:* bias toward recall, not precision — matching
LiveKit's operating point — and make the recovery graceful ("sorry, go ahead") from tenant scripts.

### 3.4 What the timing evidence actually says about a 1.0–1.5 s gap

**Stivers, Enfield, Brown, Englert, Hayashi, Heinemann, Hoymann, Rossano, de Ruiter, Yoon &
Levinson, "Universals and cultural variation in turn-taking in conversation", PNAS
106(26):10587–10592, 2009.** Ten languages, question–response pairs: a unimodal offset distribution
with a per-language mode between 0 and +200 ms and an **overall mode of 0 ms**, overall **mean
+208 ms**, medians from 0 ms (English, Japanese, Tzeltal, Yeli-Dnye) to +300 ms (Danish, Lao), with
Danish slowest at +469 ms and Japanese fastest at +7 ms. **Evidence: large observational corpus
study — the field's canonical baseline.** *Implication:* SpaTalk's 1.31 s median is roughly **6× the
human conversational mean** and about **2.8× the slowest language's average**. That is the number to
put in front of the founder: the gap is outside the entire cross-linguistic human range, not
marginally slow.

**Levinson & Torreira, "Timing in turn-taking and its implications for processing models of
language", Frontiers in Psychology 6:731, 2015.** Modal floor-transfer offsets fall **between 100
and 200 ms**, with typical gaps of 100–300 ms, against a language-production latency of roughly
600 ms for single-word naming and *"a second or more"* for multiword utterances — hence humans must
*predict* turn ends rather than react to them. Crucially, the paper reports the interpretive
consequences: *"gaps of 700 ms or more are associated with dispreferred actions,"* *"gaps longer than
the norm (>300 ms) decrease the likelihood of an unqualified acceptance,"* and *"gaps of 600 ms or
longer generate inferences of this unwelcome kind."* **Evidence: review synthesising corpus and
psycholinguistic data.** *Implication — be precise about this:* the evidence does not merely say
1.31 s "feels slow". It says a gap in that range is a **pragmatic signal that the listener is
reluctant, uncertain, or about to decline**. On a medspa line where callers ask "can you fit me in
Friday?", every reply arrives pre-coloured as hesitation. That is a mechanism for "it isn't as human
sounding as it was before" that has nothing to do with wording. **Set the target at the inference
boundary: p50 at or under 600 ms perceived gap, p95 at or under 1000 ms**, and log perceived gap as a
first-class per-turn metric with those two thresholds as SLOs.

Two qualifications. The IROS 2025 field experiment is the only *deployed* test here, and it shows the
subjective gain from cutting about a second is large and significant while behavioural metrics do not
move — so do not expect the fix to appear in call-completion rates. And the CUI 2025 study found no
filler benefit at 1.5 s, so the gap must be shortened rather than papered over. Widely circulated
"300 ms rule" figures from vendor blogs restate the human 200 ms baseline as a product target;
**no primary study establishing a 300 ms or 500 ms user-tolerance threshold for telephone voice
agents was found — treat those numbers as UNVERIFIED folklore.**

### 3.5 Full-duplex spoken LMs as a horizon

**Nguyen, Kharitonov, Copet, Adi, Hsu, Elkahky, Tomasello, Algayres, Sagot, Mohamed & Dupoux,
"Generative Spoken Dialogue Language Modeling" (dGSLM), TACL 11:250–266, 2023.** The first textless
model to generate two-channel naturalistic dialogue: dual-tower transformer over discovered speech
units, 2,000 h of two-channel Fisher audio, no text or labels, producing speech, laughter and
paralinguistics on both channels simultaneously with *"more naturalistic and fluid turn taking
compared to a text-based cascaded model."* **Evidence: benchmark.** *What it buys:* proof that
turn-taking dynamics are learnable from duplex audio. *What it costs:* no semantic control, no
instruction following, no tool calls. Unusable as a receptionist; valuable as a source of metrics.

**Defossez, Mazare, Orsini, Royer, Perez, Jegou, Grave & Zeghidour, "Moshi: a speech-text foundation
model for real-time dialogue", 2024 (arXiv:2410.00037).** Models its own and the user's stream in
parallel so explicit speaker turns disappear, with an "Inner Monologue" time-aligned text prefix:
*"the first real-time full-duplex spoken large language model, with a theoretical latency of 160ms,
200ms in practice"*. The repo specifies a 7B temporal transformer and *"a GPU with a significant
amount of memory (24GB)"*. **Evidence: benchmark plus released system.** *What it buys:* the 1.31 s
problem disappears by construction, and barge-in gating with it. *What it costs:* a dedicated 24 GB
GPU per concurrent call, no tool-calling architecture, no surface to attach `guard()` to, and no way
to keep outcome wording in tenant scripts. **Deployability at about CA$0.035/min: no.** (Arithmetic
ours, not cited: a 24 GB-class cloud GPU at roughly US$0.7–1.1/hr is about US$0.012–0.018 per
*wall-clock* minute for one session at 100% utilisation, and a clinic line idles most of the day, so
the effective cost per answered minute is several multiples of that before PSTN.) *Implication:*
park the architecture, lift the evaluation discipline.

**Lin, Lian, Li, Wang, Anumanchipalli, Liu & Lee, "Full-Duplex-Bench: A Benchmark to Evaluate
Full-duplex Spoken Dialogue Models on Turn-taking Capabilities", ASRU 2025 (arXiv:2503.04721).**
Automatic metrics across pause handling, backchannelling, turn-taking and interruption, over dGSLM,
Moshi, Freeze-Omni and Gemini Live. Smooth turn-taking (take-over rate / latency): **dGSLM 0.975 /
0.352 s; Moshi 0.941 / 0.265 s; Freeze-Omni 0.336 / 0.953 s; Gemini Live 0.655 / 1.301 s.**
Backchannel frequency is near zero for every model except dGSLM (0.015) and Gemini Live (0.012).
Interruption handling (GPT-4o-scored relevance / latency): Moshi 0.765 / 0.257 s versus Freeze-Omni
3.615 / 1.409 s and Gemini Live 3.376 / 1.183 s. **Evidence: benchmark, single-turn, automatic
metrics.** *Implication — the most useful single anchor in this survey:* **Gemini Live's measured
turn-taking latency of 1.301 s is indistinguishable from SpaTalk's 1.31 s median.** SpaTalk is not
behind the deployed state of the art; it is *at* it, and the deployed state of the art is outside the
human range. The benchmark also exposes the real trade: the fast full-duplex models score **0.765**
on interruption *relevance* while the slower cascaded ones score 3.4–3.6. Speed and content quality
are currently traded off, which is the strongest argument for keeping the cascade and buying speed
through anticipation (3.1) rather than through architecture. Adopt Full-Duplex-Bench's four axes as
the scenario-suite structure and its take-over-rate plus latency pair as the reported metric.

Related 2025–2026 benchmarks exist — FD-Bench (Interspeech 2025, arXiv:2507.19040) and
Full-Duplex-Bench-v2 (arXiv:2510.07838) — located but not verified in detail; their specific numbers
are **UNVERIFIED** here. Full-Duplex-Bench-**v3** (arXiv:2604.04847) is discussed in 6.3 with a
different metric set, and its latency figures are not comparable with v1's.

---

## 4. Human-likeness, trust and disclosure

### 4.1 The disclosure penalty is real, and it is a competence inference

**Luo, Tong, Fang & Qu, "Frontiers: Machines vs. Humans: The Impact of Artificial Intelligence
Chatbot Disclosure on Customer Purchases", Marketing Science 38(6):937–947, 2019.** A randomised
field experiment on more than 6,200 customers receiving structured outbound sales calls from either
chatbots or human workers. Verified from the published abstract: undisclosed chatbots were *"as
effective as proficient workers and four times more effective than inexperienced workers"*, but *"a
disclosure of chatbot identity before the machine-customer conversation reduces purchase rates by
more than 79.7%."* The mechanism is an inference, not a capability gap: *"when customers know the
conversational partner is not a human, they are curt and purchase less because they perceive the
disclosed bot as less knowledgeable and less empathetic"*, an effect *"driven by a subjective human
perception against machines, despite the objective competence of AI chatbots."* Disclosure also
*"substantially decreases call length."* Named mitigators: late disclosure timing, and prior AI
experience. **Evidence: field experiment.** *Implication:* the up-front disclosure script costs
engagement and SpaTalk cannot trade it away, so the only lever is the second half of the sentence —
Ava must immediately demonstrate knowledge and empathy, because that is exactly what callers deduct
on hearing "AI". Late disclosure is not available to SpaTalk and should not be proposed.
**UNVERIFIED:** the condition-level figures widely quoted from this paper (23.7% / 25.1% / 4.8% /
11.0% / 23.2%) appear only in secondary vendor commentary — do not print them.

**Schilke & Reimann, "The transparency dilemma: How AI disclosure erodes trust", Organizational
Behavior and Human Decision Processes 188:104405, 2025.** Thirteen experiments: actors who disclose
AI use are trusted less, mediated by **reduced perceived legitimacy**, holding *"regardless of
whether disclosure is voluntary or mandatory"* and *"above and beyond algorithm aversion"*; a
within-paper meta-analysis finds the penalty *"attenuated but not eliminated"* among evaluators with
favourable technology attitudes and perceptions of high AI accuracy. **Evidence: 13 lab
experiments.** *Implication:* SpaTalk cannot reword its way out. Accuracy signals and
returning-caller familiarity are the documented attenuators.

Two boundary conditions cut in SpaTalk's favour. **Mozafari, Weiger & Hammerschmidt, "Trust me, I'm
a bot – repercussions of chatbot disclosure in different service frontline settings", Journal of
Service Management 33(2):221–245, 2022** find disclosure harms retention via reduced trust **only
for high-criticality services** — and that when the bot *fails* to resolve the issue, disclosure has
no negative effect and can even improve retention. **Evidence: two lab experiments.**
*Implication:* SpaTalk's refuse-and-hand-off path is the condition under which disclosure is free.
An honest "I can't do that, a person will" is a retention asset. **Longoni, Bonezzi & Morewedge,
"Resistance to Medical Artificial Intelligence", Journal of Consumer Research 46(4):629–650, 2019**
show resistance to medical AI driven by **uniqueness neglect**, eliminated when AI *"only supports
rather than replaces a decision made by a human healthcare provider."* **Evidence: multi-study
lab.** *Implication:* frame Ava structurally as support for the clinic's staff, not as the
decision-maker — which is already the ledger architecture, and should be said out loud in the
disclosure script.

### 4.2 More human-like is not monotonically better

**Crolic, Thomaz, Hadi & Stephen, "Blame the Bot: Anthropomorphism and Anger in Customer-Chatbot
Interactions", Journal of Marketing, 2022.** Five studies including a large real-world telecoms
dataset: when customers arrive **angry**, chatbot **anthropomorphism lowers** satisfaction, firm
evaluation and purchase intention, via expectancy violation from inflated pre-encounter expectations
of efficacy; no such effect for non-angry customers. **Evidence: field data plus four experiments;
volume, issue and pages not verified.** *Implication:* the complaint path should *reduce* persona
warmth and escalate fast. Human-likeness is a liability on exactly the calls the founder most wants
handled gracefully.

**Dharmaputri, Nagpal, Nyilasy & Lei, "Socially Fluent, Socially Awkward: Artificial Intelligence
Relational Talk Backfires in Commercial Interactions", arXiv:2604.12206 (Apr 2026).** The closest
paper to the founder's actual question. Across four experiments: *"a negative main effect of AI
relational talk on satisfaction, mediated by expectancy violation and perceived interaction
awkwardness"*, attenuated when the relational talk is **goal-relevant**; the authors explicitly
challenge *"the assumption that increased social fluency will improve satisfaction."* **Evidence:
four lab experiments; preprint, not peer reviewed.** *Implication:* the design rule. Ava may
acknowledge, mirror and remember — all goal-relevant — but small talk, pleasantries and personality
flourishes untied to the caller's task measurably backfire. **Schanke, Burtch & Ray, "Estimating the
Impact of 'Humanizing' Customer Service Chatbots", Information Systems Research 32(3):736–751,
2021** is the counterweight: randomising humour, communication delays and social presence in a
retailer's chatbot **raised conversion**, but pushed consumers into a fairness and negotiating
mindset. **Evidence: field experiment.** *Implication:* humanisation pays where there is something
to negotiate; a clinic front desk has no price to haggle, so take the acknowledgement and drop the
charm.

### 4.3 Voice: no simple uncanny valley, but atypicality is punished

**Mori, "The Uncanny Valley" (1970), trans. MacDorman & Kageki, IEEE Robotics & Automation Magazine
19(2):98–100, 2012** is the origin. For voice alone the picture is more forgiving than folklore
suggests. **Kuhne, Fischer & Zhou, "The Human Takes It All: Humanlike Synthesized Voices Are
Perceived as Less Eerie and More Likable", Frontiers in Neurorobotics 14:593732, 2020** rated three
voice classes with 95 participants and found results *"contrary to that predicted by the uncanny
valley effect"*: higher perceived human-likeness predicted **lower** eeriness (beta = -0.64, -0.66)
and higher likability. **Evidence: lab ratings study, n=95.** **Diel & Lewis, "Deviation from typical
organic voices best explains a vocal uncanny valley", Computers in Human Behavior Reports 14:100430,
2024** recover a vocal uncanny valley only once deliberately distorted or naturally atypical voices
enter the stimulus set: **deviation from typical organic voices** best explains uncanniness, with
perceived organicness moderating. **Evidence: lab study; participant count UNVERIFIED.**
*Implication:* pushing Ava's TTS toward more human is safe and helps. What to fear is not
human-likeness but **artefacts** — clipped prosody, mid-word cut-offs, mismatched affect. Latency and
barge-in glitches are the real uncanny-valley risk, so spend the budget there rather than on a more
"characterful" voice.

**Alipour, Hartmann & Alimardani, "Would You Rely on an Eerie Agent? A Systematic Review of the
Impact of the Uncanny Valley Effect on Trust in Human-Agent Interaction", arXiv:2505.05543 (2025).**
PRISMA review of 53 empirical studies: *"most studies rely on static images or hypothetical
scenarios with limited real-time interaction, and the majority use subjective trust measures."*
**Evidence: systematic review, preprint.** *Implication:* treat all of 4.3 as suggestive for a live
phone call; SpaTalk's own A/B on call completion is stronger evidence than this literature.

The norm-setting event is **Google Duplex (May 2018)**: the launch post states *"transparency is a
key part of that"* while describing deliberately added *"speech disfluencies"* and *"more latency to
make the conversation feel more natural"*; after backlash Google committed to *"designing this
feature with disclosure built-in"* and to ensuring *"the system is appropriately identified"*, with
the proposed opener *"I'm the Google assistant and I'm calling for a client."* **Evidence: primary
blog post plus contemporaneous reporting.** *Implication:* the industry precedent is
disclosure-at-open, which SpaTalk already meets. The reputational risk is deliberately *simulating*
humanity after having disclosed.

### 4.4 What measurably raises satisfaction: not repeating yourself

**Walker, Litman, Kamm & Abella, "PARADISE: A Framework for Evaluating Spoken Dialogue Agents",
ACL-EACL 1997, pp. 271–280** gives the quantified answer. Their fitted performance model is
**Performance = .40 x N(kappa) - .78 x N(c2)**, where kappa is task success and **c2 is the number of
repair utterances**, together accounting for **92% of the variance in user satisfaction** (kappa
p much less than .0003; repairs p much less than .0001). Raw utterance count was dropped as redundant
with repairs (r = 0.91). **Evidence: framework plus a fitted model on a dialogue corpus.**
*Implication:* repairs are weighted roughly **twice** task success, with the opposite sign. Every
re-ask of something already in the transcript is a repair utterance. Log a `repair` event per
re-prompt and treat repairs-per-call as a first-class SLO beside hand-off accuracy. **Walker, Kamm &
Litman (2000)** add that perceived task completion, mean recognition score and number of help
requests are the significant satisfaction predictors (**citation details UNVERIFIED**). **Litman &
Pan (2002)** — see 1.4 — show that changing strategy on detected trouble beats repeating the prompt.

**Nenkova, Gravano & Hirschberg, "High Frequency Word Entrainment in Spoken Dialogue", ACL-08 Short
Papers, pp. 169–172, 2008.** High-frequency word entrainment is *predictive of perceived
naturalness* and *significantly correlated with task success*. **Evidence: corpus study.**
*Implication:* entrain on the caller's own words — if they say "Botox", Ava says "Botox", not
"neuromodulator injectables". This is the cheapest naturalness win available and needs no persona
change; it also requires the model to word the turn, because a fixed script cannot entrain.
Practitioner guidance (Cohen, Giangola & Balogh, *Voice User Interface Design*, 2004) supports
tapered and escalating prompts — never the same wording twice. **Evidence: practitioner text, no
measured effect sizes.**

**Evidence gap worth stating.** A 2026 vendor-authored review of the voice-AI patient-engagement
literature reports *"No peer-reviewed studies measure the impact of voice-based AI agents on inbound
patient appointment booking rates"*, with vendor claims of 21–47% lift resting on *"short measurement
windows, no control groups, and no peer-reviewed validation."* **Evidence: vendor-authored review —
a pointer, not an authority.** *Implication:* no external benchmark exists for SpaTalk's core
business metric. Its own instrumented ledger is the evidence base.

### 4.5 Disclosure law and norms: what SpaTalk must do versus should do

- **Canada — no statutory AI-disclosure duty as of 2026-09-11.** AIDA died with Bill C-27 at the
  **prorogation of Parliament on 5 January 2025**. The refreshed federal strategy **"AI for All"
  (4 June 2026)** explicitly rejects standalone AI legislation, relying on privacy reform, a "Canada
  Trusted AI Certification" programme and existing law; **Bill C-36** was introduced **15 June 2026**.
  The applicable norm is the **ISED Voluntary Code of Conduct (September 2023)**, which commits
  signatories to ensure *"systems that could be mistaken for humans are clearly and prominently
  identified as AI systems."* **Evidence: legal texts plus law-firm analysis.** *Implication:* Ava's
  disclosure script is **good practice and voluntary-code alignment, not legal compliance** — say so
  in the runbook rather than implying a statutory duty.
- **Ontario — PHIPA is the real exposure.** A cosmetic-only spa falls under PIPEDA, but a medspa
  operating under a physician or NP medical director that keeps treatment records is likely a **health
  information custodian** under PHIPA, which requires a **written agreement with service providers
  (s. 10(4))**. **Evidence: legal analysis; whether Skincentrix is a custodian is UNVERIFIED and
  needs counsel.** *Implication:* the health-context boolean and transcript retention need a
  PHIPA-grade data-processing agreement, not just a PIPEDA one.
- **PIPEDA and transcripts.** OPC guidance *Recording of Customer Telephone Calls* (last modified
  6 March 2018) requires organisations to *"inform the customer that they are recording a call,
  clearly state the purpose of the recording and ask for their consent"*, limit use to the stated
  purpose, offer an **alternative channel** if the caller objects, honour **access requests**, and
  limit retention. **Evidence: regulator guidance.** *Implication:* recording-off-by-default does not
  exempt transcripts — they are personal information. The disclosure script must name transcription
  and purpose, and the runbook needs an alternative channel and an access procedure.
- **CRTC — likely out of scope.** The Unsolicited Telecommunications Rules govern **outbound**
  solicitation, with ADAD messages required to disclose caller identity, callback number and purpose;
  inbound calls a clinic receives are not addressed. **Evidence: CRTC page content verified only via
  search snippets — direct fetch returned 403, so PARTIALLY VERIFIED.** *Implication:* no ADAD
  obligation for Ava today; it attaches the moment SpaTalk places outbound reminder or callback calls.
- **Comparison points.** **EU AI Act Art. 50(1)** requires that persons be *"informed that they are
  interacting with an AI system"* unless obvious, with Art. 50(5) requiring it *"at the latest at the
  time of the first interaction"*; it **applies from 2 August 2026**, and the Commission says the
  "obvious" exception *"should be interpreted in a restrictive manner"*. SpaTalk already satisfies it.
  **California SB 1001** (B.O.T. Act, eff. 1 July 2019) defines a bot as an *"automated online
  account"* on a *"public-facing Internet Web site, Web application, or digital application"* —
  **telephone voice calls are outside its scope**, a useful correction to a common claim. **Utah's
  AIPA** (SB 149, eff. 1 May 2024, amended by SB 226 / SB 332 eff. 7 May 2025) is the closest
  analogue to a medspa: disclosure on a consumer's clear request, **proactive** disclosure for a
  *"high-risk AI interaction"* (sensitive health data plus personalised advice), with a safe harbour
  for clear disclosure *"at both the outset of any consumer interaction and throughout the
  interaction"*. **Evidence: legal texts, regulator FAQ, law-firm analysis.** *Implication:*
  SpaTalk's up-front-plus-on-request disclosure already matches the strictest regime anywhere it
  might sell. Treat disclosure as a fixed product property and compete on the competence signal.

### 4.6 The engineering answer

The literature supports a narrow, testable position: **become more human in the mechanics, not in the
persona.** Memory across the call, entrainment on the caller's vocabulary, never re-asking, never
repeating a prompt verbatim, and low-artefact audio are all measurably tied to naturalness and
satisfaction (PARADISE's -.78 repair weight; Nenkova et al.; Litman & Pan). Relational warmth, small
talk, humour and simulated hesitation are measurably neutral-to-harmful once the caller knows it is
an AI (Dharmaputri et al. 2026; Crolic et al. 2022), and actively harmful on angry and
high-criticality calls. The disclosure penalty (Luo et al. 2019; Schilke & Reimann 2025) is best
countered by visible competence and by the honest hand-off structure that Longoni et al. and
Mozafari et al. both identify as the condition under which AI disclosure stops costing anything.

---

## 5. Cost-aware architectures: is a Lite-tier model enough?

### 5.1 The headline gap is real, but it is not a parameter-count gap

The one benchmark that measures exactly SpaTalk's job — a policy-bound agent talking to a live user
through tools — is **τ-bench (Yao, Shinn, Razavi & Narasimhan, arXiv:2406.12045, 2024)**. Its pass^1
table is blunt about tiers: `gpt-4o` 61.2% retail / 35.2% airline, against `gemini-1.5-flash`
17.4 / 26.0, `claude-3-haiku` 19.0 / 14.4, `gpt-3.5-turbo` 20.0 / 10.8. On retail that is a
**3.5× gap**, the strongest single argument against a Lite-tier dialogue manager. Three details
complicate it. First, `gemini-1.5-flash` (26.0) *beat* `gemini-1.5-pro` (14.0) on airline — tier
ordering inverts, which is itself a variance signal. Second, `gpt-4o`'s own **pass^8 on retail falls
to roughly 25%** from 61.2%: the frontier is unreliable at k=8, not merely better. Third and most
decisive: **deleting the domain policy from the prompt cost `gpt-4o` 22.4 points on airline** (and
4.4 on retail). Policy adherence, not fluency, is what the hard domain measures. **Evidence:
benchmark.**

**τ²-bench (Barres, Dong, Ray, Si & Narasimhan, arXiv:2506.07982, 2025)** adds the dual-control case,
which is what a phone receptionist actually is — the caller acts on the world too. `gpt-4.1` scores
74% retail, 56% airline, **34% telecom**; moving from no-user operation to guiding a user costs
**18 points for `gpt-4.1` and 25 points for `o4-mini`**. The authors locate the bottleneck in
communication and coordination, not reasoning. **Evidence: benchmark.** *(The per-tier mini/flash
cells live in a figure that could not be transcribed — **UNVERIFIED**; do not quote mini-tier
τ²-bench numbers. A secondary aggregator reported Gemini 2.5 Flash-Lite at 72.8 telecom / 73.1
retail / 58.0 airline; this could not be confirmed against any primary source — **do not cite it**.)*

**Laban et al. (2025)** — see 1.3 — is the paper that should change SpaTalk's prior: **39% average
drop**, decomposed as **−16% aptitude and +112% unreliability**, with frontier and small models
degrading alike (30–40%). **MultiChallenge (Findings of ACL 2025, arXiv:2501.17399)** agrees from
another angle: every frontier model scores under 50% on realistic multi-turn conversation, best
41.4%. **Evidence: benchmarks.**

For dialogue state specifically, Hudeček & Dušek set the floor (JGA 0.01–0.13 zero-shot against 0.60
supervised) and FnCTOD shows the framing matters more than the size (7B–13B with function calling
beating the prior ChatGPT SOTA) — both detailed in 1.1.

> **Implication.** Buy the tier upgrade as an experiment, not as a fix. The literature predicts a 4×
> model spend recovers the aptitude component (about 16%) and almost none of the unreliability
> component (about 112%) — which is the component the ledger exists to absorb. **Metric to adopt:
> pass^k, not pass^1.** Run the top 20 Skincentrix scenarios at k=5 and report the all-five-succeed
> rate; a single green run is not evidence.

### 5.2 Routing and cascades: strong, and cheaper than the headroom

**FrugalGPT (Chen, Zaharia & Zou, arXiv:2305.05176, 2023)** matched GPT-4 at **98.3% cost reduction**
on HEADLINES (US$33.1 to US$0.6) and **73.3%** on OVERRULING *with +1% accuracy*, using a cascade of
three models and a DistilBERT scorer. **RouteLLM (Ong et al., arXiv:2406.18665, 2024; ICLR 2025)**
formalises the operating point via CPT(x%): **3.66× cost reduction at 95% of GPT-4 quality on
MT-Bench**, but only **1.41×** (MMLU, 92%) and **1.49×** (GSM8K, 87%) — savings collapse as the task
gets less chatty and more correctness-bound. **Hybrid LLM (Ding et al., ICLR 2024)** reports up to
**40% fewer large-model calls at no quality drop**. The 2026 routing survey (Moslem & Kelleher,
arXiv:2603.04445) collects the best claims — MixLLM at 97.25% of GPT-4 quality for 24.18% of cost —
plus the warning that matters most here: verbalised self-reported uncertainty *"consistently
exhibit[s] low alignment between reported uncertainty and prediction correctness"*; probe-based
confidence beats self-reports. **Evidence: benchmarks plus a survey.**
*(The widely repeated RouteLLM claim of "85% cost reduction at 95% of GPT-4" does not appear in the
paper and is omitted.)*

> **Implication.** A two-tier router is the right shape, and SpaTalk's headroom makes it optional
> rather than urgent: **CA$0.099 − CA$0.035 = CA$0.064/min of headroom, about 14.5× the entire
> CA$0.0044 LLM line.** At published Gemini prices, Flash-Lite to Flash is **5× on input
> (US$0.30 to US$1.50/M) and 3.6× on output (US$2.50 to US$9.00/M)** — call it 4×, taking the LLM
> line to about CA$0.018/min and all-in to about CA$0.049/min, roughly **21% of headroom**.
> **Routing rule: never route on the model's own stated confidence.** Route on observable structure —
> a `guard()` rejection, a tool-argument validation failure, a repeated question, a turn count past
> N — and escalate the *whole remaining call*, not one turn, since Laban et al. show damage
> accumulates.

### 5.3 Small-classifier fast paths: a latency lever, not a margin lever

**OrchestraLLM (Lee, Cheng & Ostendorf, NAACL 2024, pp. 1434–1445)** is the closest published
analogue: an untrained kNN router over frozen MPNet embeddings picks a fine-tuned T5 small model or
ChatGPT per turn. On MultiWOZ 2.4 it scores **52.68 JGA — beating both the small model (46.06) and
ChatGPT (49.68)** while sending **62% of turns to the small model** and cutting compute 62% (oracle
ceiling 65.39). **Evidence: benchmark; no latency measurement.** Closed-set classification is where
small encoders simply win: a `bert-base` sentence encoder reaches **95.8% on CLINC150 / 97.0% on
MTOP** with **out-of-scope AUROC 0.977** (Zhang et al., arXiv:2410.13649, 2024), and **SetFit
(Tunstall et al., arXiv:2209.11055, 2022)** beats GPT-3 on RAFT (**71.3 vs 62.7**) at 19–123× less
compute. But deferral must be *learned*: **Gupta et al. (ICLR 2024, arXiv:2404.10136)** show
sequence-level confidence has a length bias and that a post-hoc token-level deferral rule lifts
area-under-deferral-curve on a FLAN-T5 Base-to-Large cascade from **0.627 to 0.722 (MNLI)**;
**Phillips et al. (arXiv:2603.21172, 2026)** show entropy alone is insufficient for safe abstention.

> **Implication.** Model SpaTalk's closed enums (`service_id`, `concern`, `practitioner`, `urgency`)
> as classification with a held-out accuracy number, not as prompting. But size the prize honestly:
> OrchestraLLM's 62% offload is 0.62 × CA$0.0044, about **CA$0.0027/min, under 8% of all-in cost**.
> Build the fast path for latency and honesty, never for margin — and ship a **risk-coverage curve**
> as a committed test artefact rather than a softmax threshold.

### 5.4 Caching and speculation: the levers that actually pay here

Vendor numbers are unusually favourable. **Google** publishes Gemini Flash-Lite context caching at
**US$0.03/M against US$0.30/M input — a 90% discount** — with storage at US$1.00/M tokens/hour (a
10k-token tenant prompt held through a five-minute call costs about US$0.0008). Implicit caching is
on by default for 2.5-and-later models with a **4,096-token minimum** on the Flash tiers.
**FLAG: Flash-Lite is not listed in the caching document even though its cached price is published —
verify Flash-Lite implicit-cache eligibility empirically before relying on the discount.**
**Anthropic** prices cache reads at **0.1× base input** and writes at 1.25× (5-minute TTL) or 2×
(1-hour), with a minimum cacheable prefix of 512–4,096 tokens by model. **OpenAI** discounts cached
input *"up to 90%"*, with a 1,024-token minimum prefix and a 30-minute reuse window. None of the
three publishes a latency figure. **Evidence: vendor claims.**

On latency, **speculative decoding (Leviathan, Kalman & Matias, ICML 2023, arXiv:2211.17192)** gives
**2–3× decoding speedup with an identical output distribution**, and **SGLang (arXiv:2312.07104)**
reports up to 6.4× throughput with multi-turn chat among the evaluated workloads. Most directly
relevant, **Udupa et al. (Interspeech 2026)** measure **505 ms average latency reduction for a 28.4%
increase in speculative computation** (see 3.1), and **Okafuji, Inoue & Ohira (ICMI Companion 2026,
arXiv:2607.23204)** cut initial response latency from **2.45 s (median 2.19) to 1.15 s (median
0.92)** using a **30M-parameter ModernBERT** intent detector (94.31% accuracy) to trigger a
`gpt-4o-mini` preface while `gpt-4o` composes the real answer — with **no significant subjective
difference** across four questionnaire items and a 7.97% breakdown rate. **Evidence: lab studies.**

> **Implication.** **Cache the tenant bundle first — it is the highest-return change in this
> section.** A 90% discount on the fixed prefix roughly pays for the entire Flash-Lite to Flash
> upgrade, making the tier question nearly cost-neutral. Structure every prompt as
> `[static tenant bundle + scripts + tool schemas] -> [conversation] -> [volatile step brief]`, never
> interleaved, and keep the prefix over 4,096 tokens so it is cache-eligible. Note the tension with
> "Lost in the Middle" (1.3): the volatile brief must be last, which costs a cache miss on every step
> change — the V1 report measured 5 of 13 turns missing the cache at no measurable TTFB cost, so pay
> it. **505 ms is the measured size of the speculation prize**, worth taking only because `guard()`
> already guarantees a discarded speculative turn cannot reach a channel.

### 5.5 Does policy-in-code recover a weak model? Yes, by roughly a tier's worth

This is the decisive evidence for SpaTalk's architecture, and it is quantitative. **CoDial
(arXiv:2506.02264, 2026)** runs the controlled experiment — same GPT-4o-mini, structured Colang
guardrail code versus free-form generated logic: **58.5 vs 36.6 F1 on STAR (+21.9)** and **60.1 vs
36.1 accuracy (+24.0)**. **Hudeček & Dušek** measure the state half: handing an 11B model the oracle
belief state lifts SGD few-shot success **0.19 to 0.46 (+27 points)**, and ChatGPT gains 0.31 to
0.47 zero-shot and 0.44 to 0.68 few-shot. **SGP-TOD** gets a 2023-era GPT-3.5 to MultiWOZ 2.0
**Combined 85.97** against **42.4** for few-shot ChatGPT, purely from a belief instruction plus a
dialogue-policy prompter. And τ-bench's −22.4-point policy ablation is the same finding read
backwards. **Evidence: four independent benchmarks pointing the same way.**

The counterweight is a warning, not a rebuttal: **Elizabeth et al. (2024/2025)** find free-form
ReAct TOD agents *"severely underperform state-of-the-art approaches on success rate in simulation"*
while users rate them **higher** on subjective satisfaction, because the wording is natural and
confidently phrased. Fluency and task success dissociate.

> **Implication — the answer to the open question.** A Lite-tier model **is** sufficient as the
> wording-and-next-utterance generator provided the runtime owns state, policy and outcome claims; it
> is **not** sufficient as the thing that decides what is true. The measured recoverable delta from
> code-side structure (+22 to +27 points) is **larger than the roughly 16% aptitude delta a tier
> upgrade buys**, and structure compounds with scale rather than competing with it. Concretely: keep
> Flash-Lite as the default, spend the headroom on prompt caching plus a Flash *escalation* triggered
> by structural signals, and never treat caller satisfaction or response fluency as a success metric —
> the ReAct result says those can rise while task success falls, which is precisely the failure the
> non-negotiables exist to make impossible.

---

## 6. Evaluating naturalness and task success cheaply

### 6.1 Simulated users: cheap, scalable, and systematically too easy

**τ-bench**'s two design choices matter more to SpaTalk than its scores. Success is scored by
**comparing final database state to an annotated goal state**, not by judging the transcript — a
deterministic, free check. And **pass^k** — the probability that *all k* independent attempts at the
same task succeed — collapses as k grows whenever failures are uncorrelated, which is exactly what an
average hides (gpt-4o: under 50% of tasks, **pass^8 under 25% in retail**). **Evidence: benchmark.**
*Implication:* score every scenario by asserting the expected ledger rows exist, and report pass^8
across 8 repeats of the same scripted call.

**τ²-bench** extends this to dual control and deliberately **constrains its user simulator by tools
and observable state** to raise fidelity. **Evidence: benchmark.** *Implication:* constrain SpaTalk's
simulated caller to a fixed fact sheet (real name, service wanted, availability) and forbid it from
inventing facts; an unconstrained simulator will helpfully supply whatever the agent asks for.

The most important recent result is **"Mind the Sim2Real Gap in User Simulation for Agentic Tasks"
(Zhou et al., arXiv:2603.11245, 2026)**: the first full τ-bench protocol run with real people —
**451 participants, 165 tasks, 31 simulators** — introducing a User-Sim Index. Simulated users were
excessively cooperative and stylistically uniform, lacked realistic frustration and ambiguity, and
gave **uniformly more positive feedback** than humans across eight quality dimensions, creating an
"easy mode" that inflates agent success above the human baseline. **Evidence: preprint, but with the
largest human comparison set in this area.** *Implication:* treat every simulated-caller number as a
**ceiling**, never an estimate. Gate releases on it not falling, not on it being high.

Three corroborating results quantify the same gap. **RealUserSim (Zhu et al., arXiv:2605.20204,
2026)** grounds simulators in 14,000+ real conversations and reports unguided LLM simulation matching
real-user style only **6–8%** of the time, rising to **45.3%** when grounded, with task success
dropping **3.2–3.5%** under realistic simulators. **Persona Policies (Chopra et al.,
arXiv:2605.12894, 2026)** notes simulators *"inherit the behavior of their underlying models:
cooperative and homogeneous"*, and its evolved personas were rated human **80.4%** of the time versus
roughly half that for baselines. **"Simulated Customers Never Walk Away" (Chen, arXiv:2606.20708,
2026)** measures a disengagement deficit against **793 verified real payment outcomes**: simulators
match eventual buyers almost exactly but shift non-buyers toward purchase, cutting expressed
resistance from **25.1% to 13.5%**. **Evidence: three preprints.** *Implication:* write two persona
banks — a cooperative one for regression, and a difficult one (vague, impatient, interrupting,
withholding a phone number, volunteering health detail) for the numbers you actually act on.
**ChatChecker (Mayr, Schimpf & Bohne, arXiv:2507.16792, 2025)** operationalises this as a testing
framework with non-cooperative personas and improves breakdown detection by putting an **error
taxonomy in the prompt**. *Implication:* adopt its shape directly — a fixed persona list plus a
SpaTalk-specific error taxonomy (claimed-an-action, free-text-on-item, wrong-script, invented-price).

### 6.2 LLM-as-a-judge: usable for naturalness, only with the guardrails

**Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", NeurIPS 2023 Datasets &
Benchmarks** is the foundational measurement: strong LLM judges reach *"over 80% agreement"* with
human preferences, and the paper names the three canonical failure modes — **position, verbosity and
self-enhancement bias** — plus limited reasoning. **Evidence: benchmark.** *(The frequently quoted
"85% GPT-4 vs 81% human-human" split is **UNVERIFIED**; only "over 80%" was confirmed from the
primary abstract.)* *Implication:* a judge is fit for "did this sound like a receptionist?" It is not
fit for "did the agent file the item" — that is a ledger assertion.

Position bias is severe and cheap to exploit: **Wang et al., "Large Language Models are not Fair
Evaluators", ACL 2024** showed **Vicuna-13B beating ChatGPT on 66 of 80 queries** purely by
reordering the two responses. *Implication:* never score one arm alone; always run A-vs-B and B-vs-A
and count only agreeing verdicts. Verbosity bias is measurable and correctable: **Dubois et al.,
"Length-Controlled AlpacaEval", COLM 2024** raised Spearman correlation with Chatbot Arena from
**0.94 to 0.98** with length control. *Implication:* a chattier model wins a naive naturalness judge;
log response length per turn as a covariate and check the winner is not just longer.
Self-enhancement is real and mechanistic: **Panickssery, Bowman & Feng, "LLM Evaluators Recognize and
Favor Their Own Generations", NeurIPS 2024** found a linear correlation between self-recognition
ability and self-preference strength, and **Yang et al. (arXiv:2604.22891, 2026)** across 20 models
found stronger models are not less biased, reducing self-preference **31.5%** via structured
multi-dimensional evaluation. *Implication:* never judge Gemini output with Gemini; use a different
family. **Ye et al., "Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge", ICLR 2025**
catalogues **12 bias types** and finds no model clean across all of them.

On mitigations: **Prometheus 2 (Kim et al., EMNLP 2024)** shows a fine-tuned open judge taking a
**user-defined rubric** in both direct-assessment and pairwise modes *(its reported agreement figures
are **UNVERIFIED**, from a secondary summary)*. **Soumik (arXiv:2604.23178, 2026)** tested nine
debiasing strategies across five judges and 975 pairs: chain-of-thought plus a calibrated rubric plus
position swap gave the largest gains (**+11.5 pp** for one judge, p<0.0001), while **position swap
alone actively hurt on adversarial data (−3 to −13 pp)** — individual mitigations are not additive.
**Evidence: preprint, independent author — weak.** *Implication:* use one bundle — rubric
decomposition, swapped-order pairwise, a reference answer, a judge from a different family — and
validate the bundle against roughly 50 founder-labelled calls before trusting it.

### 6.3 Cheap loggable signals that predicted satisfaction in deployed voice systems

**PARADISE (Walker, Litman, Kamm & Abella, ACL-EACL 1997)** is the historical baseline and is
detailed in 4.4; its shape is one satisfaction target, a task-success term, and cost terms.
**Walker, Passonneau & Boland, "Quantitative and Qualitative Evaluation of DARPA Communicator Spoken
Dialogue Systems", ACL 2001, pp. 515–522** applied it across deployed systems *(the figure that
standard metrics accounted for 37% of variance is **UNVERIFIED** — the PDF would not parse; venue,
authors and pages are verified)*. *Implication:* expect any such model to leave most variance
unexplained; use it to rank arms, not to predict a rating.

The single most actionable artefact is the **LEGO / Interaction Quality corpus (Schmitt, Ultes &
Minker, LREC 2012)**: 347 calls / 9,083 system-user exchanges (LEGOv2: 548 / 13,836) from CMU Let's
Go, annotated turn by turn on a **5-point Interaction Quality scale by three raters**, alongside
**53 automatically logged interaction parameters** — ASR recognition status, ASR confidence, success
rates, **barge-ins, timeouts, rejections, help requests**, and system and user dialogue acts.
**Evidence: deployed-system corpus.** *Implication:* **this is SpaTalk's log schema.** Everything in
that list is free to record per turn and none of it needs a model. **Ultes, Schmitt & Minker, "On
Quality Ratings for Spoken Dialogue Systems – Experts vs. Users", NAACL 2013** asks whether expert
ratings track user satisfaction *(numbers **UNVERIFIED**)*. *Implication:* founder-rated call quality
is an expert proxy, not a user rating; label it as such.

**Choi, Ahmadvand & Agichtein, "Offline and Online Satisfaction Prediction in Open-Domain
Conversational Systems", CIKM 2019** predict satisfaction in a deployed system using conversation
history, utterance content **and behavioural signals**. **Evidence: deployed study.** *Implication:*
behavioural signals carry independent information; do not build a transcript-only quality model.
**Khatri et al., "Advancing the State of the Art in Open Domain Dialog Systems through the Alexa
Prize" (2018)** reports deployed socialbots at an **average user rating of 3.61, median duration
2 min 18 s, average 14.6 turns**. *Implication:* publish SpaTalk's per-arm medians for duration and
turns next to outcome; a naturalness win that doubles call length is a cost regression. *(Claims that
a simple metric combination correlates 0.66 with Alexa ratings, or RMSE about 1.3 for rating
prediction, are **UNVERIFIED**.)*

On the voice layer: **Liesenfeld, Lopez & Dingemanse, "The timing bottleneck: Why timing and overlap
are mission-critical for conversational user interfaces, speech recognition and dialogue systems",
SIGDIAL 2023** evaluated five commercial ASR systems and found word error rates on natural
conversational data remain very poor across six languages, with **overlapping speech a key failure**
that propagates into intent recognition. **Evidence: benchmark.** *Implication:* log ASR confidence
and overlap/barge-in events per turn — a naturalness regression is often an ASR regression.
**Full-Duplex-Bench-v3 (Lin, Chen, Chen & Lee, arXiv:2604.04847, 2026)** benchmarks voice agents on
real annotated disfluency with exactly the metrics SpaTalk can log — Pass@1, interruption-avoidance
%, latency, turn-take rate — reporting GPT-Realtime at 0.600 Pass@1 / 13.5% interruption, Gemini Live
3.1 at 4.25 s latency / 78.0% turn-take, and a cascaded Whisper-to-GPT-4o-to-TTS baseline at 10.12 s.
**Evidence: benchmark. Note: these latency numbers use a different definition from v1's (3.5) and are
not comparable with it.** *Implication:* adopt those four as the voice dashboard.

**Important honesty flag.** The widely repeated claims that "each second of latency cuts satisfaction
15–20%", or that satisfaction collapses past 1 s, appear **only in vendor marketing blogs**. No
peer-reviewed or deployed study supporting a specific latency-to-satisfaction elasticity was found.
**UNVERIFIED — do not cite.** The defensible statements are the ones in 3.4 (pragmatic inference at
600–700 ms) and 3.1 (a deployed experiment where cutting about a second moved subjective smoothness
significantly).

### 6.4 Human A/B with short calls: be honest about the power

**Wester, Valentini-Botinhao & Henter, "Are we using enough listeners? No! — an empirically-supported
critique of Interspeech 2014 TTS evaluations", Interspeech 2015, pp. 3476–3480** is decisive,
verified verbatim: tallying Interspeech 2014 subjective evaluations showed *"in more than 60% of
papers conclusions are based on listening tests with less than 20 listeners"*, and their Blizzard
2013 analysis showed that **for a MOS test measuring naturalness a stable level of significance is
only reached when more than 30 listeners are used**. **Evidence: meta-analysis.** *Implication:* the
founder alone, or even 10–30 calls by one listener, cannot support a MOS naturalness claim. Stop
reporting "it sounds less human" as a measurement.

**Kirkland, Mehta, Lameris, Henter, Szekely & Gustafson, "Stuck in the MOS pit: A critical analysis
of MOS test methodology in TTS evaluation", SSW 2023, pp. 41–47** surveyed Interspeech and SSW
2021–2022 and found most authors do not report scale labels, increments or participant instructions,
that implementations diverge, and that it is often unclear whether listeners rated **naturalness or
overall quality** — with their own experiments confirming that scale increment and instruction
framing materially change the MOS obtained. **Evidence: meta-analysis.** *Implication:* if SpaTalk
records MOS at all, fix and write down the scale, the increment and the exact instruction ("rate how
human this sounded", not "rate quality"), or runs will not be comparable across weeks.

**Design guidance and arithmetic (ours, not a citation).** Because between-listener variance
dominates MOS, a **within-subjects, order-counterbalanced forced-choice A/B** is the right design at
SpaTalk's scale: the same caller intent, both arms, arm identity blinded, presentation order
randomised. For a paired forced-choice preference (sign test, two-sided alpha 0.05, 80% power) the
binomial sample sizes are roughly: **10 paired calls** detects only a near-total 90/10 preference,
**20** detects 80/20, and **47** is needed for 70/30. *Implication:* at n of 10–30 calls SpaTalk can
only detect a large, obvious difference. Treat the founder's calling round as a **smoke test for
catastrophe** and put the release decision on rungs 0–4 below.

### 6.5 Automatic detection of conversational failure

The **Dialogue Breakdown Detection Challenge (Higashinaka, Funakoshi, Kobayashi & Inaba, LREC 2016)**
established the task — detect the system utterance that makes a dialogue unable to continue — with
per-utterance labels and a standard metric suite. **Evidence: benchmark.** *Implication:* add a
per-turn breakdown label to the transcript schema; it is the join key between logs and quality.

The closest published work to SpaTalk's exact situation is **MultConDB (Miah, Schnaithmann,
Raghuvanshi & Son, NAACL 2024 Industry Track, arXiv:2404.08156)**: real-time multimodal breakdown
detection on a **deployed healthcare phone agent** doing insurance benefit-verification calls —
**1,689 calls, about 178,059 turns, about 105 turns per call** — where **breakdown was defined as
"human intervention required"**: the agent deviated from standard operating procedure, the user
showed frustration, or the agent made a call-critical error. Combining audio with downstream NLP
inferences reached **F1 69.27** (P 65.96 / R 72.94) against Text-LSTM 49.44, end-to-end LLM 57.61 and
a multimodal transformer 59.12, holding at **F1 71.22** on a later month's calls. **Evidence:
deployed study — the single best-matched source in this survey.** *Implication:* steal the label
definition verbatim. "Did a human have to rescue this call?" is SpaTalk's ground truth, it is already
in the ledger (escalations, un-actioned items), it needs no annotation budget, and "deviated from
SOP" maps exactly onto the structural-honesty and fixed-script guarantees.

**Sandbank et al., "Detecting Egregious Conversations between Customers and Virtual Agents", NAACL
2018** used logs from two different commercial virtual-agent systems and found that adding customer
behavioural cues, agent-response patterns and interaction characteristics to text features **improved
detection F1 by around 20%**, and that these patterns generalised across systems. **Evidence:
deployed study.** *Implication:* repetition and re-prompt counts are the cheapest members of that
feature family. Log "agent said a near-duplicate of its previous utterance", "caller repeated
themselves" and "same slot asked twice". These need no model and are the best automatic proxy for
the founder's "it feels worse".

### 6.6 A proposed evaluation ladder, cheapest first

**Rung 0 — turn-level log schema. Zero cost, do this first.** Per turn: ASR confidence, recognition
status, barge-in, timeout, rejection, re-prompt, near-duplicate agent utterance, caller repetition,
same-slot-asked-twice, tool error, `guard()` refusal, perceived gap. Per call: turns, duration,
outcome, item filed, escalation, repairs. *Evidence: the LEGO corpus's 53 parameters are exactly this
list; PARADISE is the model for combining them; Sandbank et al. show behavioural features add about
20% F1 over text alone.* This is the only rung that turns "it isn't as human sounding" into a number.

**Rung 1 — deterministic ledger assertions on scripted scenarios.** Replace string checks with
end-state checks: assert the exact expected ledger rows, item type, urgency and script used. No
judge, no model cost. *Evidence: τ-bench scores by comparing final database state to an annotated
goal state.* This is the rung that protects the structural-honesty non-negotiables.

**Rung 2 — pass^k instead of a mean.** Run each scenario 8 times; report the fraction of scenarios
where all 8 runs passed. *Evidence: gpt-4o at under 50% mean but pass^8 under 25% on τ-bench retail.*
This is the rung that catches the flakiness a "model leads" change will introduce.

**Rung 3 — multi-turn simulated caller, two persona banks.** Cooperative for regression, difficult
for decisions, both constrained to a fixed fact sheet. Report simulated success as a **ceiling** and
gate on non-regression. *Evidence: τ²-bench's constrained simulator; the Sim2Real gap's 451-participant
finding; RealUserSim's 6–8% style match; Persona Policies; ChatChecker's error taxonomy.*

**Rung 4 — automatic breakdown detection on real calls.** Label every real call "did a human have to
rescue this?" from data already in the ledger, plus a rules-only repetition detector. Track the rate
per release. *Evidence: MultConDB's deployed definition and F1 69.27/71.22; DBDC for the per-turn
label schema.* Free ground truth, no annotation budget.

**Rung 5 — LLM judge for naturalness only, as a bundle.** Pairwise old-versus-new transcripts, order
swapped with only agreeing verdicts counted, a rubric decomposed into named criteria, a reference
answer, a judge from a different model family, and response length logged as a covariate. Validate
against about 50 founder-labelled calls before trusting it. *Evidence: "over 80%" human agreement;
66-of-80 flips from reordering; 0.94 to 0.98 from length control; self-recognition drives
self-preference; 12 catalogued biases; CoT plus rubric plus swap as the bundle that survived
correction while swap alone hurt adversarially.*

**Rung 6 — founder A/B calling round, as a smoke test only.** Same caller intent, both arms, arm
identity blinded, order counterbalanced, forced-choice preference rather than a MOS number; if MOS is
recorded, fix and document the scale, increment and exact instruction. *Evidence: more than 30
listeners needed for stable MOS significance, and over 60% of published TTS evaluations were
underpowered; scale and framing materially change MOS.* **Honest power (our arithmetic): about 10
paired calls detects only a 90/10 preference, 20 detects 80/20, 47 is needed for 70/30.** A 20-call
round can tell you the new version is not catastrophically worse. It cannot tell you it is better.

---

## 7. Ranked design rules for "model leads, runtime holds the record"

Ranked by strength of evidence times size of the expected effect on SpaTalk specifically. Each rule
names the evidence and what would have to change in the code.

**R1. The runtime decides which slot is open; the model decides how the turn sounds.**
Evidence: Genie Worksheets, 21.8% to 82.8% goal completion with the policy in a runtime and the LLM
limited to parsing and *generating responses* (n=62); CoDial, +21.9 F1 within one model from
structured policy code; τ-bench, −22.4 points when the policy leaves the prompt; E2E NLG, generated
wording wins naturalness while authored wording wins semantic accuracy.
Change: keep `next_step`, `step_tools` and `draft_from` exactly as they are; retire slot-engine
invariant 4's "every question the caller hears is a tenant script" and replace it with "every
*outcome sentence* the caller hears is a tenant script, and every question realises the act the
runtime named." `step_question` becomes a *fallback* wording the model may rephrase, not a
`TTSSpeakFrame` that pre-empts the model.

**R2. Resolvers return candidates and a confidence; nothing is written on a guess.**
Evidence: Laban et al., +112% unreliability and *"when LLMs take a wrong turn… they get lost and do
not recover"*; Know Your Mistakes, best-in-class JGA about 70% and a user confirmation as good as
self-correction; Zou et al., low-quality clarifications measurably disturb users; Horvitz's
cost-of-poor-guess principle.
Change: `resolve.py` already returns a kind and a score, and `shares_a_word` is the right shape.
The remaining work is (a) feed ASR confidence in beside the lexical score (Komatani & Kawahara), and
(b) make the *offer* wording model-generated from the candidate set rather than a fixed
`confirm_match` template, so a two-candidate case reads like a receptionist.

**R3. Repair with the most specific move available, and never the same move twice.**
Evidence: Dingemanse et al. — restricted offer beats restricted request beats open request, 12
languages, 2,053 cases; PARADISE — repairs weighted −.78 against task success +.40, 92% of
satisfaction variance; Schegloff/Jefferson/Sacks — preference for self-correction; CarryOnBench's
"repetitive recovery" as a general model failure.
Change: a three-rung ladder in the runtime — grounded candidate offer, then a targeted request, never
an open one — plus a hard rule that the same script key never fires twice in a row with an unchanged
record (V1's `asked_already`, generalised), and a logged `repair` event each time it does.

**R4. Shorten the gap before doing anything about wording.**
Evidence: Stivers et al., human mode 0 ms / mean +208 ms; Levinson & Torreira, gaps at or over
600–700 ms are heard as reluctance; Inoue et al. (IROS 2025 field experiment), 2.14 s to 1.15 s moved
smoothness 4.67 to 6.13 (p=.007) with behavioural metrics flat; Maslych et al., fillers do *not* help
at 1.5 s; Full-Duplex-Bench, Gemini Live measured at 1.301 s — SpaTalk is at the deployed state of
the art and the state of the art is outside the human range.
Change: SLOs of p50 at or under 600 ms and p95 at or under 1000 ms on perceived gap; re-score Smart
Turn during the silence (about 13 ms per call) and cap the fallback instead of paying a flat 1.5 s;
evaluate endpoint anticipation (505 ms for 28.4% extra speculative compute) with the guard as the
safety net for discarded speculations.

**R5. Never re-ask what the record already holds, and display the hypothesis instead of signalling
non-understanding.**
Evidence: Skantze 2005 — humans *"ask task-related questions that confirm their hypothesis about the
situation instead of signalling non-understanding"*; PARADISE's repair weight; Sandbank et al. —
behavioural cues including repetition add about 20% F1 to failure detection.
Change: delete every "sorry, I didn't catch that" shape from the script set. A miss becomes a
task-related question built from the current hypothesis, which necessarily means the model words it.

**R6. A side question pushes a sub-segment; closing it pops back to the open purpose, explicitly.**
Evidence: Grosz & Sidner's attentional state as a stack of focus spaces; Laban et al. on
non-recovery; Dongre et al. — goal tokens become attention-inaccessible, so the goal must be
re-asserted in the live turn, not assumed to be "in context".
Change: `Slots` grows a two-element stack (open step, open side question) and `step_message` says
*"you were about to ask which treatment"* rather than re-emitting the question. V1's repeat
suppression is the one-bit version of this.

**R7. Confirm by consequence, not by step.**
Evidence: Clark & Brennan's grounding criterion and least collaborative effort; Komatani & Kawahara's
concept-level confidence; Know Your Mistakes on friction turns.
Change: one confirmation policy parameterised by (cost of being wrong × uncertainty), replacing the
nine hand-written `confirm_*` behaviours. A phone number gets read back; a part-of-day does not.

**R8. Ask the qualifying questions after the reason for the call is on the table.**
Evidence: Schegloff 1968 and Whalen & Zimmerman 1987 on institutional call openings — identification
and greeting compress so the caller's first substantive turn is the reason for the call; Schegloff &
Sacks 1973 on pre-closings.
Change: `start_request(kind)` must precede `Step.RETURNING` in every path, including the rules-gate
path that opens the clinical flow; a flow that asks "have you been in before?" before the caller has
said what they want has inverted the sequence.

**R9. Tighten from model-led to runtime-led on measured trouble, rather than choosing once.**
Evidence: Litman & Pan 2002 — adaptive initiative and confirmation, switched on detected recognition
trouble, significantly raised task completion for novices and cut misrecognised and total turns;
Horvitz 1999 and Allen/Guinn/Horvitz 1999.
Change: a per-call "trouble score" from signals SpaTalk already computes (`slots.misses`,
`ignored_tools`, `asked_already`, barge-in-and-repeat, rules-gate near-miss). Below threshold the
model words the turn and may reorder within it; above threshold the runtime speaks the script
verbatim and confirms every slot. This is the single design that satisfies both the founder's ear and
the ledger's guarantee, and it is the only rule here with a *deployed* comparison behind it.

**R10. Entrain on the caller's words; drop the charm.**
Evidence: Nenkova et al. — high-frequency word entrainment predicts perceived naturalness and
correlates with task success; Dharmaputri et al. 2026 — AI relational talk reduces satisfaction
through perceived awkwardness unless goal-relevant; Crolic et al. 2022 — anthropomorphism hurts with
angry customers.
Change: the prompt's "HOW YOU SOUND" block gains "use the caller's own word for a treatment, even if
the catalogue names it differently" and loses any licence for small talk; the complaint and payment
paths drop the persona warmth and the audio tags entirely.

**R11. Keep Flash-Lite, cache the bundle, escalate on structure — not on self-reported confidence.**
Evidence: CoDial and the oracle-belief-state result — structure recovers +22 to +27 points, more than
a tier upgrade's roughly 16% aptitude delta; Gemini's published 90% context-cache discount; the
routing survey's finding that verbalised self-confidence aligns poorly with correctness; CA$0.064/min
of headroom against a CA$0.0044 LLM line.
Change: order the prompt as static bundle, then history, then the volatile step brief; measure the
cache-hit rate; add a Flash escalation triggered by the same trouble score as R9, for the remainder
of the call.

**R12. Measure with ledger assertions, pass^k and "did a human have to rescue this call?"**
Evidence: τ-bench's goal-state scoring and pass^8 collapse; MultConDB's deployed definition of
breakdown as human intervention required (F1 69.27, 71.22 a month later); the Sim2Real gap's finding
that simulated users are systematically too cooperative; Wester et al. — more than 30 listeners for a
stable MOS verdict.
Change: the evaluation ladder in 6.6, in that order. Rung 0 is free and is the prerequisite for every
claim in this document being testable on SpaTalk's own calls.

---

## 8. Where the evidence contradicts or fails to support the hypothesis

**Contradicted outright: "the LLM … decides the next question."** Three independent measurements say
the next-step decision must not sit with the model. Genie Worksheets puts the same frontier model at
**21.8%** goal completion when it owns the flow and **82.8%** when a runtime does. CoDial measures
**+21.9 F1 / +24.0 accuracy** for the same GPT-4o-mini purely from moving the flow into code.
τ-bench loses **22.4 points** on its harder domain when the policy is removed from the prompt. Laban
et al. add the mechanism: models commit early and do not recover. A Flash-Lite-class model choosing
the next question on a booking call is the configuration these papers measure as the worst one. The
hypothesis survives only in the form "the model leads the *turn*; the runtime leads the *flow*."

**Contradicted in part: "resolvers returning candidates not verdicts" is sufficient.** It is
necessary and not sufficient. Zou et al. show a *bad* candidate is worse than no candidate (n=89),
which is the "Did you mean Free virtual consultation?" failure; and Know Your Mistakes shows that at
about 70% joint goal accuracy the system must add a friction turn, not merely defer the verdict. A
candidate ladder plus a confirmation policy is required, not a softer resolver.

**Unproven: that naturalness pays.** The only study measuring both axes at once (Elizabeth et al.)
found LLM-led agents *lower* on simulated success and *higher* on human satisfaction, attributing the
satisfaction to *"natural and confidently phrased responses"* — the same confidence the guard exists
to police. Dharmaputri et al. (2026) find relational fluency *reduces* satisfaction unless
goal-relevant. And a 2026 review reports **no peer-reviewed study measuring the effect of a voice AI
agent on inbound booking rates at all.** So "more human" is not a business case; it is a hypothesis
SpaTalk must test on its own ledger.

**Unproven: that the perceived problem is wording.** The timing evidence offers a competing
explanation with better support: at 1.31 s median, every reply lands in the range that human
listeners hear as reluctance or a dispreferred answer (Levinson & Torreira), and the one deployed
experiment in this area moved *subjective smoothness* by a full point and a half on a 7-point scale
purely by cutting about a second (Inoue et al., IROS 2025). Wording and timing are confounded in the
founder's report, and the cheaper of the two to test is timing.

**Unsupported by any source found: three numbers in circulation.** No primary study establishes a
300 ms or 500 ms user-tolerance threshold for telephone voice agents; no study supports a
"each second of latency costs 15–20% satisfaction" elasticity; and the widely quoted condition-level
percentages from Luo et al. 2019 appear only in secondary commentary. None of these should appear in
a SpaTalk design document.

---

## 9. Open questions the literature does not settle

1. **Phonetic confirmation of names and digits on a phone line.** No verified study on read-back
   format, spelling alphabets, or three-three-four grouping for names over telephony. The
   "payment"/"Peyman" decision — read the name back at the name step, or accept occasional wrong names
   — has to be made on cost. The nearest evidence is Komatani & Kawahara's concept-level confidence,
   which says *whether* to confirm but not *how*.
2. **Where exactly the `stop_secs` fallback should sit.** Smart Turn publishes accuracy (94.31%
   English) and inference cost (12.6 ms) but no guidance on the fallback timeout and no measurement
   of the latency cost of a false "not finished". The V1 report's open item stands: a live call, not a
   desk decision — though re-scoring during the silence is the mechanism the evidence supports.
3. **How much of the naturalness gain survives a disclosed AI.** Every entrainment and
   backchannel result comes from human-human or undisclosed-agent settings; every disclosure result
   says callers discount an agent they know is artificial. Nobody has crossed the two factors in a
   service phone call.
4. **Whether a small-model fast path helps or hurts on a real phone line.** No source measures a
   dialogue-act or intent classifier fast path end to end in a telephony receptionist. The nearest
   evidence is OrchestraLLM (text TOD, 62% offload, no latency figure) and the 2026 preface-generation
   work (voice latency, no intent routing).
5. **Whether Gemini Flash-Lite is eligible for implicit context caching.** Its cached-input price is
   published; it is absent from the caching document's eligibility list. This needs one empirical
   check, and it materially changes the tier decision.
6. **How to place a backchannel on a PSTN line without a stereo channel.** The backchannel-placement
   models are trained on two-channel or multimodal data; SpaTalk has a single mixed channel with echo.
   Nothing found addresses that constraint.
7. **Whether a simulated caller can detect a naturalness regression at all.** The Sim2Real work shows
   simulators are systematically too cooperative and stylistically uniform, which is precisely the
   dimension a naturalness test needs to vary. Simulated evaluation may be structurally unable to
   measure the thing the founder is complaining about.
8. **Whether repairs-per-call transfers from 1997 IVR to 2026 LLM voice.** PARADISE's −.78 repair
   coefficient is the most actionable number in this survey and it was fitted on a 1997 spoken
   dialogue corpus. Nobody has refitted it on an LLM-driven voice agent.

---

## 10. References

All URLs below were fetched or verified on **2026-09-11**. Where a publisher page returned HTTP 403
to automated fetching, the mirror actually read is named.

### Task-oriented dialogue, policy and control

- Hudeček, V. & Dušek, O. (2023). Are Large Language Models All You Need for Task-Oriented Dialogue?
  *SIGDIAL 2023*, 216–228. https://aclanthology.org/2023.sigdial-1.21/ · https://arxiv.org/abs/2304.06556
- Li, Z., Chen, Z. Z., Ross, M., Huber, P., Moon, S., Lin, Z., Dong, X. L., Sagar, A., Yan, X. &
  Crook, P. A. (2024). Large Language Models as Zero-shot Dialogue State Tracker through Function
  Calling (FnCTOD). *ACL 2024*, 8688–8704. https://aclanthology.org/2024.acl-long.471/ ·
  https://arxiv.org/abs/2402.10466
- Zhang, X., Peng, B., Li, K., Zhou, J. & Meng, H. (2023). SGP-TOD: Building Task Bots Effortlessly
  via Schema-Guided LLM Prompting. *Findings of EMNLP 2023*, 13348–13369.
  https://aclanthology.org/2023.findings-emnlp.891/ · https://arxiv.org/abs/2305.09067
- Zhao, J., Cao, R., Rastogi, A. et al. (2023). AnyTOD: A Programmable Task-Oriented Dialog System.
  *EMNLP 2023*. https://aclanthology.org/2023.emnlp-main.1006/ · https://arxiv.org/abs/2212.09939
- Wu, Q., Gung, J., Shu, R. & Zhang, Y. (2023). DiactTOD: Learning Generalizable Latent Dialogue Acts
  for Controllable Task-Oriented Dialogue Systems. *SIGDIAL 2023*.
  https://aclanthology.org/2023.sigdial-1.24/ · https://arxiv.org/abs/2308.00878
- Joshi, H., Liu, S., Chen, J., Weigle, R. & Lam, M. S. (2024/2025). Controllable and Reliable
  Knowledge-Intensive Task-Oriented Conversational Agents with Declarative Genie Worksheets.
  *ACL 2025*. https://arxiv.org/abs/2407.05674
- Shayanfar, R., Luo, C. F., Bhambhoria, R., Dahan, S. & Zhu, X. (2026). CoDial: Interpretable
  Task-Oriented Dialogue Systems Through Dialogue Flow Alignment. arXiv:2506.02264v3.
  https://arxiv.org/abs/2506.02264
- Dey, S., Sun, Y.-J., Tur, G. & Hakkani-Tür, D. (2025). Know Your Mistakes: Towards Preventing
  Overreliance on Task-Oriented Conversational AI Through Accountability Modeling. *ACL 2025 Main*.
  https://arxiv.org/abs/2501.10316
- Elizabeth, M., Veyret, M., Couceiro, M., Dušek, O. & Rojas-Barahona, L. M. (2024/2025). Exploring
  ReAct Prompting for Task-Oriented Dialogue: Insights and Shortcomings. arXiv:2412.01262.
  https://arxiv.org/abs/2412.01262
- Robino, G. (2025). Conversation Routines: A Prompt Engineering Framework for Task-Oriented Dialog
  Systems. arXiv:2501.11613. https://arxiv.org/abs/2501.11613
- Bohus, D. & Rudnicky, A. I. (2009). The RavenClaw dialog management framework: Architecture and
  systems. *Computer Speech & Language* 23(3), 332–361. DOI 10.1016/j.csl.2008.10.001
- Bohus, D. & Rudnicky, A. I. (2005). Error handling in the RavenClaw dialog management framework.
  *HLT/EMNLP 2005*, 225–232. DOI 10.3115/1220575.1220604
- Google Cloud. Generative versus deterministic (Dialogflow CX / Conversational Agents).
  https://docs.cloud.google.com/dialogflow/cx/docs/generative-deterministic

### Multi-turn degradation, instruction following, context

- Laban, P., Hayashi, H., Zhou, Y. & Neville, J. (2025). LLMs Get Lost In Multi-Turn Conversation.
  arXiv:2505.06120. https://arxiv.org/abs/2505.06120 · code https://github.com/microsoft/lost_in_conversation
- He, Y., Zhang, D., Wang, X. et al. (2024). Multi-IF: Benchmarking LLMs on Multi-Turn and
  Multilingual Instructions Following. arXiv:2410.15553. https://arxiv.org/pdf/2410.15553
- Jiang, Y., Wang, Y., Luo, X. et al. (2024). FollowBench: A Multi-level Fine-grained Constraints
  Following Benchmark for Large Language Models. *ACL 2024*, 4667–4688.
  https://aclanthology.org/2024.acl-long.257/ · https://arxiv.org/abs/2310.20410
- Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F. & Liang, P. (2024).
  Lost in the Middle: How Language Models Use Long Contexts. *TACL* 12, 157–173.
  DOI 10.1162/tacl_a_00638
- Dongre, V., Hsieh, J., Lai, V. D., Yoon, S., Bui, T. & Hakkani-Tür, D. (2026). When Attention
  Closes: How LLMs Lose the Thread in Multi-Turn Interaction. arXiv:2605.12922.
  https://arxiv.org/abs/2605.12922
- Sirdeshmukh, V. et al. (2025). MultiChallenge: A Realistic Multi-Turn Conversation Evaluation
  Benchmark Challenging to Frontier LLMs. *Findings of ACL 2025*.
  https://aclanthology.org/2025.findings-acl.958/ · https://arxiv.org/abs/2501.17399

### Clarification, repair and grounding

- Dingemanse, M., Roberts, S. G., Baranova, J., Blythe, J., Drew, P., Floyd, S. et al. (2015).
  Universal Principles in the Repair of Communication Problems. *PLoS ONE* 10(9), e0136100.
  https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0136100
- Schegloff, E. A., Jefferson, G. & Sacks, H. (1977). The Preference for Self-Correction in the
  Organization of Repair in Conversation. *Language* 53(2), 361–382. DOI 10.2307/413107
- Skantze, G. (2005). Exploring human error recovery strategies: Implications for spoken dialogue
  systems. *Speech Communication* 45(3), 325–341. DOI 10.1016/j.specom.2004.11.005 ·
  https://www.sciencedirect.com/science/article/abs/pii/S0167639304001256
- Bohus, D. & Rudnicky, A. I. (2005). Sorry, I didn't catch that! An investigation of
  non-understanding errors and recovery strategies. *6th SIGdial Workshop*, 128–143.
  https://aclanthology.org/2005.sigdial-1.14/ (PDF would not parse; per-strategy numbers UNVERIFIED)
- Bohus, D. & Rudnicky, A. I. (2005). Constructing accurate beliefs in spoken dialog systems.
  *IEEE ASRU 2005*, 272–277. DOI 10.1109/ASRU.2005.1566504
- Komatani, K. & Kawahara, T. (2000). Flexible mixed-initiative dialogue management using
  concept-level confidence measures of speech recognizer output. *COLING 2000*, 467–473.
  DOI 10.3115/990820.990888
- Rao, S. & Daumé III, H. (2018). Learning to Ask Good Questions: Ranking Clarification Questions
  using Neural Expected Value of Perfect Information. *ACL 2018*, 2737–2746.
  DOI 10.18653/v1/P18-1255
- Aliannejadi, M., Zamani, H., Crestani, F. & Croft, W. B. (2019). Asking Clarifying Questions in
  Open-Domain Information-Seeking Conversations. *SIGIR 2019*, 475–484. DOI 10.1145/3331184.3331265
- Zou, J., Sun, A., Long, C., Aliannejadi, M. & Kanoulas, E. (2023). Asking Clarifying Questions: To
  benefit or to disturb users in Web search? *Information Processing & Management* 60(2), 103176.
  DOI 10.1016/j.ipm.2022.103176
- Zheng, M., Morgan, M., Jiang, L., Rose, C. & Sap, M. (2026). Useless but Safe? Benchmarking Utility
  Recovery with User Intent Clarification in Multi-Turn Conversations. arXiv:2604.27093.
  https://arxiv.org/abs/2604.27093
- Grosz, B. J. & Sidner, C. L. (1986). Attention, Intentions, and the Structure of Discourse.
  *Computational Linguistics* 12(3), 175–204. https://aclanthology.org/J86-3001/
- Clark, H. H. & Brennan, S. E. (1991). Grounding in communication. In *Perspectives on Socially
  Shared Cognition*, 127–149. APA. DOI 10.1037/10096-006
- Traum, D. R. & Allen, J. F. (1992). A 'speech acts' approach to grounding in conversation.
  *ICSLP 1992*, 137–140. DOI 10.21437/ICSLP.1992-41
- Schegloff, E. A. (1968). Sequencing in Conversational Openings. *American Anthropologist* 70(6),
  1075–1095. DOI 10.1525/aa.1968.70.6.02a00030
- Schegloff, E. A. & Sacks, H. (1973). Opening up Closings. *Semiotica* 8(4), 289–327.
  DOI 10.1515/semi.1973.8.4.289
- Whalen, M. R. & Zimmerman, D. H. (1987). Sequential and Institutional Contexts in Calls for Help.
  *Social Psychology Quarterly* 50(2), 172ff. DOI 10.2307/2786750

### Mixed initiative and adaptation

- Horvitz, E. (1999). Principles of mixed-initiative user interfaces. *CHI 1999*, 159–166.
  DOI 10.1145/302979.303030
- Allen, J. E., Guinn, C. I. & Horvitz, E. (1999). Mixed-initiative interaction. *IEEE Intelligent
  Systems* 14(5), 14–23. DOI 10.1109/5254.796083
- Litman, D. J. & Pan, S. (2002). Designing and Evaluating an Adaptive Spoken Dialogue System.
  *User Modeling and User-Adapted Interaction* 12, 111–137. DOI 10.1023/A:1015036910358 ·
  https://people.cs.pitt.edu/~litman/umuai02.pdf

### Natural language generation

- Dušek, O., Novikova, J. & Rieser, V. (2018). Findings of the E2E NLG Challenge. *INLG 2018*.
  https://aclanthology.org/W18-6539/ · https://arxiv.org/abs/1810.01170
- Dušek, O., Novikova, J. & Rieser, V. (2020). Evaluating the State-of-the-Art of End-to-End Natural
  Language Generation: The E2E NLG Challenge. *Computer Speech & Language*.
  https://arxiv.org/abs/1901.07931

### Turn-taking, prosody, latency, full duplex

- Ekstedt, E. & Skantze, G. (2020). TurnGPT: a Transformer-based Language Model for Predicting
  Turn-taking in Spoken Dialog. *Findings of EMNLP 2020*, 2981–2990.
  https://aclanthology.org/2020.findings-emnlp.268/
- Ekstedt, E. & Skantze, G. (2022). Voice Activity Projection: Self-supervised Learning of
  Turn-taking Events. *Interspeech 2022*, 5190–5194. DOI 10.21437/Interspeech.2022-10955 ·
  https://www.isca-archive.org/interspeech_2022/ekstedt22_interspeech.html
- Inoue, K., Jiang, B., Ekstedt, E., Kawahara, T. & Skantze, G. (2024). Real-time and Continuous
  Turn-taking Prediction Using Voice Activity Projection. *IWSDS 2024*. arXiv:2401.04868.
  https://arxiv.org/abs/2401.04868
- Inoue, K., Jiang, B., Ekstedt, E., Kawahara, T. & Skantze, G. (2024). Multilingual Turn-taking
  Prediction Using Voice Activity Projection. *LREC-COLING 2024*, 11873–11883.
  https://aclanthology.org/2024.lrec-main.1036/
- Inoue, K., Okafuji, Y., Baba, J., Ohira, Y., Hyodo, K. & Kawahara, T. (2025). A Noise-Robust
  Turn-Taking System for Real-World Dialogue Robots: A Field Experiment. *IROS 2025*.
  arXiv:2503.06241. https://arxiv.org/html/2503.06241
- Inoue, K. et al. (2025). Prompt-Guided Turn-Taking Prediction. *SIGDIAL 2025*.
  https://aclanthology.org/2025.sigdial-1.9.pdf (numbers UNVERIFIED)
- Udupa, S., Watanabe, S., Schwarz, P. & Černocký, J. (2026). Endpoint Anticipation for Low-Latency
  Spoken Dialogue. *Interspeech 2026*. arXiv:2606.13450. https://arxiv.org/abs/2606.13450
- Daily / Pipecat (2025). Announcing Smart Turn v3, with CPU inference in just 12ms (11 Sep 2025).
  https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/ ; Smart Turn v2
  (18 Jul 2025) https://www.daily.co/blog/smart-turn-v2-faster-inference-and-13-new-languages-for-voice-ai/ ;
  model card https://huggingface.co/pipecat-ai/smart-turn-v3
- Leviathan, Y. & Matias, Y. (2018). Google Duplex: An AI System for Accomplishing Real-World Tasks
  Over the Phone. Google AI Blog, 8 May 2018.
  https://research.google/blog/google-duplex-an-ai-system-for-accomplishing-real-world-tasks-over-the-phone/
- Maslych, M. et al. (2025). Mitigating Response Delays in Free-Form Conversations with LLM-powered
  Intelligent Virtual Agents. *CUI 2025*. arXiv:2507.22352. https://arxiv.org/html/2507.22352v1
- Figueroa, C., de Korte, M., Ochs, M. & Skantze, G. (2024). Mhm... Yeah? Okay! Evaluating the
  Naturalness and Communicative Function of Synthesized Feedback Responses in Spoken Dialogue.
  *SIGDIAL 2024*, 544–553. https://aclanthology.org/2024.sigdial-1.46/
- Lin, Y., Zheng, Y., Zeng, Z. & Shi, S. (2025). Predicting Turn-Taking and Backchannel in
  Human-Machine Conversations Using Linguistic, Acoustic, and Visual Signals. *ACL 2025*,
  15310–15322. https://aclanthology.org/2025.acl-long.743/
- Skantze, G. (2021). Turn-taking in Conversational Systems and Human-Robot Interaction: A Review.
  *Computer Speech & Language* 67, 101178.
  https://www.sciencedirect.com/science/article/pii/S088523082030111X
- LiveKit (2026). Solving unwanted interruptions with Adaptive Interruption Handling (19 Mar 2026).
  https://livekit.com/blog/adaptive-interruption-handling
- Ström, N. & Seneff, S. (2000). Intelligent barge-in in conversational systems. *ICSLP 2000*.
  https://sls.csail.mit.edu/publications/2000/03082.pdf
- Stivers, T., Enfield, N. J., Brown, P., Englert, C., Hayashi, M., Heinemann, T., Hoymann, G.,
  Rossano, F., de Ruiter, J. P., Yoon, K.-E. & Levinson, S. C. (2009). Universals and cultural
  variation in turn-taking in conversation. *PNAS* 106(26), 10587–10592.
  DOI 10.1073/pnas.0903616106 · read via https://pmc.ncbi.nlm.nih.gov/articles/PMC2705608/
  (pnas.org returned 403)
- Levinson, S. C. & Torreira, F. (2015). Timing in turn-taking and its implications for processing
  models of language. *Frontiers in Psychology* 6, 731. DOI 10.3389/fpsyg.2015.00731 ·
  https://pmc.ncbi.nlm.nih.gov/articles/PMC4464110/
- Nguyen, T. A., Kharitonov, E., Copet, J., Adi, Y., Hsu, W.-N., Elkahky, A., Tomasello, P.,
  Algayres, R., Sagot, B., Mohamed, A. & Dupoux, E. (2023). Generative Spoken Dialogue Language
  Modeling (dGSLM). *TACL* 11, 250–266. https://aclanthology.org/2023.tacl-1.15/
- Défossez, A., Mazaré, L., Orsini, M., Royer, A., Pérez, P., Jégou, H., Grave, E. & Zeghidour, N.
  (2024). Moshi: a speech-text foundation model for real-time dialogue. arXiv:2410.00037.
  https://arxiv.org/abs/2410.00037 · https://github.com/kyutai-labs/moshi
- Lin, G.-T., Lian, J., Li, T., Wang, Q., Anumanchipalli, G., Liu, A. H. & Lee, H.-y. (2025).
  Full-Duplex-Bench: A Benchmark to Evaluate Full-duplex Spoken Dialogue Models on Turn-taking
  Capabilities. *ASRU 2025*. arXiv:2503.04721. https://arxiv.org/abs/2503.04721
- Lin, G.-T., Chen, C., Chen, Z. & Lee, H.-y. (2026). Full-Duplex-Bench-v3: Benchmarking Tool Use for
  Full-Duplex Voice Agents Under Real-World Disfluency. arXiv:2604.04847.
  https://arxiv.org/abs/2604.04847

### Human-likeness, trust, disclosure

- Luo, X., Tong, S., Fang, Z. & Qu, Z. (2019). Frontiers: Machines vs. Humans: The Impact of
  Artificial Intelligence Chatbot Disclosure on Customer Purchases. *Marketing Science* 38(6),
  937–947. DOI 10.1287/mksc.2019.1192 · abstract verified at
  https://econpapers.repec.org/RePEc:inm:ormksc:v:38:y:2019:i:6:p:937-947 (publisher page 403)
- Schilke, O. & Reimann, M. (2025). The transparency dilemma: How AI disclosure erodes trust.
  *Organizational Behavior and Human Decision Processes* 188, 104405. DOI 10.1016/j.obhdp.2025.104405 ·
  https://par.nsf.gov/biblio/10597787-transparency-dilemma-how-ai-disclosure-erodes-trust
- Mozafari, N., Weiger, W. H. & Hammerschmidt, M. (2022). Trust me, I'm a bot – repercussions of
  chatbot disclosure in different service frontline settings. *Journal of Service Management* 33(2),
  221–245. DOI 10.1108/JOSM-10-2020-0380
- Longoni, C., Bonezzi, A. & Morewedge, C. K. (2019). Resistance to Medical Artificial Intelligence.
  *Journal of Consumer Research* 46(4), 629–650.
  https://academic.oup.com/jcr/article-abstract/46/4/629/5485292
- Crolic, C., Thomaz, F., Hadi, R. & Stephen, A. T. (2022). Blame the Bot: Anthropomorphism and Anger
  in Customer–Chatbot Interactions. *Journal of Marketing*. DOI 10.1177/00222429211045687 ·
  https://www.ama.org/blame-the-bot-anthropomorphism-and-anger-in-customer-chatbot-interactions/
  (volume/issue/pages UNVERIFIED)
- Dharmaputri, S. K., Nagpal, A., Nyilasy, G. & Lei, J. (2026). Socially Fluent, Socially Awkward:
  Artificial Intelligence Relational Talk Backfires in Commercial Interactions. arXiv:2604.12206.
  https://arxiv.org/abs/2604.12206
- Schanke, S., Burtch, G. & Ray, G. (2021). Estimating the Impact of "Humanizing" Customer Service
  Chatbots. *Information Systems Research* 32(3), 736–751. DOI 10.1287/isre.2021.1015
- Mori, M. (1970/2012). The Uncanny Valley (trans. MacDorman & Kageki). *IEEE Robotics & Automation
  Magazine* 19(2), 98–100. https://web.ics.purdue.edu/~drkelly/MoriTheUncannyValley1970.pdf
- Kühne, K., Fischer, M. H. & Zhou, Y. (2020). The Human Takes It All: Humanlike Synthesized Voices
  Are Perceived as Less Eerie and More Likable. *Frontiers in Neurorobotics* 14, 593732.
  DOI 10.3389/fnbot.2020.593732
- Diel, A. & Lewis, M. (2024). Deviation from typical organic voices best explains a vocal uncanny
  valley. *Computers in Human Behavior Reports* 14, 100430. DOI 10.1016/j.chbr.2024.100430
  (participant count UNVERIFIED; publisher page 403)
- Alipour, A., Hartmann, T. & Alimardani, M. (2025). Would You Rely on an Eerie Agent? A Systematic
  Review of the Impact of the Uncanny Valley Effect on Trust in Human-Agent Interaction.
  arXiv:2505.05543. https://arxiv.org/abs/2505.05543
- Nenkova, A., Gravano, A. & Hirschberg, J. (2008). High Frequency Word Entrainment in Spoken
  Dialogue. *ACL-08: HLT, Short Papers*, 169–172. https://aclanthology.org/P08-2043/
- Cohen, M. H., Giangola, J. P. & Balogh, J. (2004). *Voice User Interface Design.* Addison-Wesley.
  https://www.oreilly.com/library/view/voice-user-interface/0321185765/ (practitioner text)

### Law and norms

- Innovation, Science and Economic Development Canada (September 2023). Voluntary Code of Conduct on
  the Responsible Development and Management of Advanced Generative AI Systems.
  https://ised-isde.canada.ca/site/ised/en/voluntary-code-conduct-responsible-development-and-management-advanced-generative-ai-systems
- Chow, E. & Jones, H. (2026). Canada's 2026 AI Strategy: What Businesses Need to Know. Aird & Berlis
  LLP, 17 July 2026.
  https://www.airdberlis.com/insights/publications/publication/canada-s-2026-ai-strategy--what-businesses-need-to-know
- Office of the Privacy Commissioner of Canada. Recording of Customer Telephone Calls (last modified
  6 March 2018). https://www.priv.gc.ca/en/privacy-topics/surveillance/02_05_d_14/
- CRTC. Key Unsolicited Telecommunications Rules.
  https://crtc.gc.ca/eng/phone/telemarketing/tobligations/rules-regles.htm (403 on direct fetch;
  content verified only via search snippets — PARTIALLY VERIFIED)
- Information and Privacy Commissioner of Ontario. Your health privacy rights in Ontario (PHIPA).
  https://www.ipc.on.ca/en/health-individuals/file-a-health-privacy-complaint/your-health-privacy-rights-in-ontario
  (whether Skincentrix is a health information custodian is UNVERIFIED and needs counsel)
- Regulation (EU) 2024/1689, Article 50 (Transparency obligations).
  https://artificialintelligenceact.eu/article/50/ · Commission FAQ
  https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act
- California SB 1001 (2018), the B.O.T. Act, Bus. & Prof. Code §§ 17940–17943, eff. 1 July 2019.
  https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=201720180SB1001
- Bacal, M. J., Haldin, J. W., Lisson, D. & Shelanski, H. (2025). Utah scales back reach of
  generative AI consumer protection law. Davis Polk, 4 April 2025.
  https://www.davispolk.com/insights/client-update/utah-scales-back-reach-generative-ai-consumer-protection-law

### Cost, routing, caching, small models

- Yao, S., Shinn, N., Razavi, P. & Narasimhan, K. (2024). τ-bench: A Benchmark for Tool-Agent-User
  Interaction in Real-World Domains. arXiv:2406.12045. https://arxiv.org/abs/2406.12045
- Barres, V., Dong, H., Ray, S., Si, X. & Narasimhan, K. (2025). τ²-Bench: Evaluating Conversational
  Agents in a Dual-Control Environment. arXiv:2506.07982. https://arxiv.org/abs/2506.07982
- Kapoor, S., Stroebl, B., Kirgis, P., Nadgir, N., Siegel, Z. S., Narayanan, A. et al. (2025).
  Holistic Agent Leaderboard: The Missing Infrastructure for AI Agent Evaluation. arXiv:2510.11977.
  https://arxiv.org/abs/2510.11977 · https://hal.cs.princeton.edu/reliability/
- Chen, L., Zaharia, M. & Zou, J. (2023). FrugalGPT. arXiv:2305.05176. https://arxiv.org/abs/2305.05176
- Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W. & Stoica, I.
  (2024). RouteLLM: Learning to Route LLMs with Preference Data. arXiv:2406.18665.
  https://arxiv.org/abs/2406.18665
- Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan, L. V. S. &
  Awadallah, A. (2024). Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing. *ICLR 2024*.
  https://arxiv.org/abs/2404.14618
- Moslem, Y. & Kelleher, J. D. (2026). Dynamic Model Routing and Cascading for Efficient LLM
  Inference: A Survey. arXiv:2603.04445. https://arxiv.org/abs/2603.04445
- Lee, C.-H., Cheng, H. & Ostendorf, M. (2024). OrchestraLLM: Efficient Orchestration of Language
  Models for Dialogue State Tracking. *NAACL 2024*, 1434–1445.
  https://aclanthology.org/2024.naacl-long.79/ · https://arxiv.org/abs/2311.09758
- Zhang, T., Norouzian, A., Mohan, A. & Ducatelle, F. (2024). A new approach for fine-tuning sentence
  transformers for intent classification and out-of-scope detection tasks. arXiv:2410.13649.
  https://arxiv.org/abs/2410.13649
- Tunstall, L., Reimers, N., Jo, U. E. S., Bates, L., Korat, D., Wasserblat, M. & Pereg, O. (2022).
  Efficient Few-Shot Learning Without Prompts (SetFit). arXiv:2209.11055.
  https://arxiv.org/abs/2209.11055
- Gupta, N., Narasimhan, H., Jitkrittum, W., Rawat, A. S., Menon, A. K. & Kumar, S. (2024). Language
  Model Cascades: Token-level Uncertainty and Beyond. *ICLR 2024*. https://arxiv.org/abs/2404.10136
- Phillips, E., Gustafsson, F. K., Wu, S., Thakur, A. & Clifton, D. A. (2026). Entropy Alone is
  Insufficient for Safe Selective Prediction in LLMs. arXiv:2603.21172.
  https://arxiv.org/abs/2603.21172
- Leviathan, Y., Kalman, M. & Matias, Y. (2023). Fast Inference from Transformers via Speculative
  Decoding. *ICML 2023*, PMLR 202:19274–19286. https://arxiv.org/abs/2211.17192
- Zheng, L., Yin, L., Xie, Z. et al. (2023/2024). SGLang: Efficient Execution of Structured Language
  Model Programs. arXiv:2312.07104. https://arxiv.org/abs/2312.07104
- Okafuji, Y., Inoue, K. & Ohira, Y. (2026). Low-Latency Turn-Taking via Context-Aware Preface
  Generation in a Real-World Dialogue Robot. *ICMI Companion 2026*. arXiv:2607.23204.
  https://arxiv.org/abs/2607.23204
- Google. Gemini API pricing; Context caching. https://ai.google.dev/gemini-api/docs/pricing ·
  https://ai.google.dev/gemini-api/docs/caching (vendor claims; Flash-Lite implicit-cache eligibility
  UNVERIFIED)
- Anthropic. Prompt caching. https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching
  (vendor claims)
- OpenAI. Prompt caching. https://developers.openai.com/api/docs/guides/prompt-caching (vendor claims)

### Evaluation

- Walker, M. A., Litman, D. J., Kamm, C. A. & Abella, A. (1997). PARADISE: A Framework for Evaluating
  Spoken Dialogue Agents. *ACL-EACL 1997*, 271–280. https://aclanthology.org/P97-1035/ ·
  model and coefficients read from https://arxiv.org/html/cmp-lg/9704004 (anthology PDF unparseable)
- Walker, M. A., Passonneau, R. & Boland, J. E. (2001). Quantitative and Qualitative Evaluation of
  DARPA Communicator Spoken Dialogue Systems. *ACL 2001*, 515–522.
  https://aclanthology.org/P01-1066/ (variance figures UNVERIFIED)
- Walker, M. A., Kamm, C. A. & Litman, D. J. (2000). Towards developing general models of usability
  with PARADISE. *Natural Language Engineering.* (volume/pages UNVERIFIED)
- Schmitt, A., Ultes, S. & Minker, W. (2012). A Parameterized and Annotated Spoken Dialog Corpus of
  the CMU Let's Go Bus Information System. *LREC 2012*. Corpus documentation:
  https://www.uni-bamberg.de/en/ds/ressources/lego-spoken-dialogue-corpus/
- Ultes, S., Schmitt, A. & Minker, W. (2013). On Quality Ratings for Spoken Dialogue Systems –
  Experts vs. Users. *NAACL 2013*. https://aclanthology.org/N13-1064/ (numbers UNVERIFIED)
- Choi, J. I., Ahmadvand, A. & Agichtein, E. (2019). Offline and Online Satisfaction Prediction in
  Open-Domain Conversational Systems. *CIKM 2019*. https://arxiv.org/abs/2006.01921
- Khatri, C., Hedayatnia, B., Venkatesh, A. et al. (2018). Advancing the State of the Art in Open
  Domain Dialog Systems through the Alexa Prize. https://arxiv.org/abs/1812.10757
- Liesenfeld, A., Lopez, A. & Dingemanse, M. (2023). The timing bottleneck: Why timing and overlap
  are mission-critical for conversational user interfaces, speech recognition and dialogue systems.
  *SIGDIAL 2023*. https://arxiv.org/abs/2307.15493
- Zheng, L., Chiang, W.-L., Sheng, Y. et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot
  Arena. *NeurIPS 2023 Datasets & Benchmarks*. https://arxiv.org/abs/2306.05685
- Wang, P., Li, L., Chen, L. et al. (2024). Large Language Models are not Fair Evaluators. *ACL 2024*.
  https://aclanthology.org/2024.acl-long.511/ · https://arxiv.org/abs/2305.17926
- Ye, J., Wang, Y., Huang, Y. et al. (2025). Justice or Prejudice? Quantifying Biases in
  LLM-as-a-Judge. *ICLR 2025*. https://arxiv.org/abs/2410.02736
- Panickssery, A., Bowman, S. & Feng, S. (2024). LLM Evaluators Recognize and Favor Their Own
  Generations. *NeurIPS 2024*.
  https://proceedings.neurips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html
- Dubois, Y., Galambosi, B., Liang, P. & Hashimoto, T. B. (2024). Length-Controlled AlpacaEval.
  *COLM 2024*. https://arxiv.org/abs/2404.04475
- Kim, S. et al. (2024). Prometheus 2: An Open Source Language Model Specialized in Evaluating Other
  Language Models. *EMNLP 2024*. https://aclanthology.org/2024.emnlp-main.248/ (agreement figures
  UNVERIFIED)
- Yang, J., Hu, Z., Qiu, C., Deng, Z., Jiao, X. & Zhou, T. (2026). Quantifying and Mitigating
  Self-Preference Bias of LLM Judges. arXiv:2604.22891. https://arxiv.org/abs/2604.22891
- Soumik, S. K. (2026). Judging the Judges: A Systematic Evaluation of Bias Mitigation Strategies in
  LLM-as-a-Judge Pipelines. arXiv:2604.23178. https://arxiv.org/abs/2604.23178
- Zhou, X., Sun, W., Ma, Q. et al. (2026). Mind the Sim2Real Gap in User Simulation for Agentic
  Tasks. arXiv:2603.11245. https://arxiv.org/abs/2603.11245
- Zhu, M., Tan, J., Murthy, R. et al. (2026). RealUserSim: Bridging the Reality Gap in Agent
  Benchmarking via Grounded User Simulation. arXiv:2605.20204. https://arxiv.org/abs/2605.20204
- Chopra, H., Ghate, K., Caliskan, A., Kohno, T., Shah, C. & Jaques, N. (2026). Beyond Cooperative
  Simulators: Generating Realistic User Personas for Robust Evaluation of LLM Agents.
  arXiv:2605.12894. https://arxiv.org/abs/2605.12894
- Chen, L. (2026). Simulated Customers Never Walk Away: Decision Fidelity of LLM User Simulators
  Measured Against Real Purchase Outcomes. arXiv:2606.20708. https://arxiv.org/abs/2606.20708
- Mayr, R., Schimpf, M. & Bohné, T. (2025). ChatChecker: A Framework for Dialogue System Testing and
  Evaluation Through Non-cooperative User Simulation. arXiv:2507.16792.
  https://arxiv.org/abs/2507.16792
- Ni, B., Wang, L., Wang, Y., Kveton, B. et al. (2026). A Survey on LLM-based Conversational User
  Simulation. arXiv:2604.24977. https://arxiv.org/abs/2604.24977
- Wester, M., Valentini-Botinhao, C. & Henter, G. E. (2015). Are we using enough listeners? No! — an
  empirically-supported critique of Interspeech 2014 TTS evaluations. *Interspeech 2015*, 3476–3480.
  DOI 10.21437/Interspeech.2015-689 ·
  https://www.isca-archive.org/interspeech_2015/wester15c_interspeech.html
- Kirkland, A., Mehta, S., Lameris, H., Henter, G. E., Székely, É. & Gustafson, J. (2023). Stuck in
  the MOS pit: A critical analysis of MOS test methodology in TTS evaluation. *SSW 2023*, 41–47.
  DOI 10.21437/SSW.2023-7 · https://www.isca-archive.org/ssw_2023/kirkland23_ssw.html
- Higashinaka, R., Funakoshi, K., Kobayashi, Y. & Inaba, M. (2016). The Dialogue Breakdown Detection
  Challenge: Task Description, Datasets, and Evaluation Metrics. *LREC 2016*.
  https://aclanthology.org/L16-1502/
- Miah, M. M. M., Schnaithmann, U., Raghuvanshi, A. & Son, Y. (2024). Multimodal Contextual Dialogue
  Breakdown Detection for Conversational AI Models. *NAACL 2024 Industry Track*.
  https://arxiv.org/abs/2404.08156
- Sandbank, T., Shmueli-Scheuer, M., Herzig, J., Konopnicki, D., Richards, J. & Piorkowski, D.
  (2018). Detecting Egregious Conversations between Customers and Virtual Agents. *NAACL 2018*.
  https://arxiv.org/abs/1711.05780

### Do not cite (located, not verified, or contradicted by the primary source)

- The condition-level percentages attributed to Luo et al. 2019 (23.7 / 25.1 / 4.8 / 11.0 / 23.2).
- Any "each second of latency costs 15–20% satisfaction" elasticity, or a 300 ms / 500 ms
  user-tolerance threshold for telephone voice agents. Vendor blogs only.
- RouteLLM's "85% cost reduction at 95% of GPT-4" — not in the paper.
- Per-tier (mini / flash / lite) τ²-bench cells, including the aggregator figures of 72.8 telecom /
  73.1 retail / 58.0 airline for Gemini 2.5 Flash-Lite.
- The "85% vs 81%" judge-agreement split attributed to Zheng et al. 2023; the abstract says only
  "over 80%".
- Prometheus 2's Pearson and human-agreement figures; Walker et al. 2001's 37%-of-variance figure;
  Ultes et al. 2013's correlations; any Alexa Prize rating-prediction correlation or RMSE.
- Specific numbers from FD-Bench (arXiv:2507.19040), Full-Duplex-Bench-v2 (arXiv:2510.07838), and
  Prompt-Guided Turn-Taking Prediction (SIGDIAL 2025).
- Any Smart Turn guidance on `stop_secs` or the latency cost of a false negative — the vendor
  write-ups are silent.
