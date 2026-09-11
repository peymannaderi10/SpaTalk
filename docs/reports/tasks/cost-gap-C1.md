# Cost gap C1: the calculator, the ledger and the call

Status: done with deviations
Branch: `cost-gap`, worktree `.claude/worktrees/agent-a3fc81b7367e772ee`. Nothing in the main
checkout, the running runtime on port 8000, `runtime/.env`, `portal/.env.server` or the
`spatalk` / `portal` / `spatalk_test` databases was written. One scratch database,
`spatalk_test_cost_2305`, for every test run. The `spatalk` database was read through the
new CLI and through `GET /internal/tenants/skincentrix/usage`; nothing was posted to it.

Commits: `426ed94` (the meter and the estimate), `f0f5795` (speech in seconds), `c8fae86`
(the prompt budget and the service ids), `1e0e8ac` (the sheet re-derived, 3.5 Flash-Lite
priced), `4cdcad5` (the report window's open end), `bbef549` (the portal's typed client),
`79ef5c9` (three in a breath covers people), plus the commit carrying this file.

Tests: 24 new ones in `tests/test_cost_breakdown.py` (19) and `tests/test_prompt_budget.py`
(5), every one seen failing first and named in the sections below; 205 existing tests in the
eight files these changes reach (`test_internal_api`, `test_ops_cost_report`,
`test_ops_latency`, `test_contract_snapshot`, `test_qa_gate_a`, `test_qa_gate_c`,
`test_tools_prompt`, `test_voice_steps`), three of them with expectations deliberately moved
(see Deviations). Full suite -> see "Full suite" below.

Interfaces produced: `spatalk.rates.components_cad(usage, rates=None) -> dict[str, float]`,
`spatalk.rates.live_stack(rates=None) -> dict`, `spatalk.rates.COMPONENTS`,
`spatalk.ops.cost_breakdown.CallCost` (`.minutes`, `.turns`, `.units`, `.components`,
`.total_cad`, `.cad_per_minute`, `.cached_fraction`),
`spatalk.ops.cost_breakdown.call_costs(ctx, tenant_id, since, until=None) -> (list[CallCost],
CallCost)`, `spatalk.ops.cost_breakdown.lines(calls, total, tenant_id) -> list[str]`,
`spatalk cost breakdown --tenant <id> --since <date> [--until <date>]`, the `tts_seconds`
usage unit, `UsageTotals.stt_seconds` on `GET /internal/tenants/{id}/usage`,
`tests/test_prompt_budget.cad_per_minute(tokens)`.

---

## The short version

A real call does not cost three to four times the sheet. It costs 14% more than the sheet, and
the sheet itself was 13% too cheap. The whole of the rest of the gap was the meter and the
estimate's arithmetic — CA$0.0725 of the CA$0.0810 in the meter alone.

Every row below is voice only (the month's SMS is CA$0.90 either way and was never in dispute)
and per metered call-minute over 42.03 minutes. Each line is the one above it with one thing
changed, so the whole gap is attributable:

| the same 42.03 minutes, priced | CA$/call-min | vs the old sheet |
|---|---|---|
| as the portal's overview card showed it | **0.1478** | 4.86x |
| ... cached input tokens billed once, not twice | 0.1231 | 4.05x |
| ... priced on `live_stack` (the task brief's baseline, "about CA$0.11") | **0.1114** | 3.66x |
| ... the meter fixed: one metrics frame is one reading | 0.0389 | 1.28x |
| ... the speech rate re-derived at 1,100 chars a spoken minute | 0.0355 | 1.17x |
| ... speech metered in seconds instead of characters | 0.0349 | 1.15x |
| ... the service ids out of the prompt | **0.0346** | **1.14x** |
| ... three names in a breath instead of nine (projected, not measured) | 0.0340 | 1.12x |
| the sheet, re-derived from the measurement | 0.0348 | — |
| the sheet as it was | 0.0304 | 1.00x |

The number the founder can quote from is **CA$0.0348 a call-minute**, and it is now what both
`costmodel.py` and the quote page print. The measured month lands on CA$0.0346. They agree to
half a percent, which is the point: a calculator that disagrees with the ledger is worth
nothing, and the two now disagree by less than the rounding.

CA$0.0304 is not reachable. Telephony and transcription alone are **CA$0.0208** a minute
before a word is spoken or a token read, and the assistant cannot speak for 58% of a call at
CA$0.0094 and think for three turns a minute at CA$0.0046 inside the CA$0.0096 the old sheet
left over. At CA$0.0348 and the founder's 65% margin the retail number is **CA$0.0994 a
call-minute**; at the CA$999 list price a clinic clears 91.7% margin and stays above 65% until
about 2,800 calls a month, eleven times the volume the business case assumes.

---

## 1. Before: what was measured, and how

`spatalk cost breakdown --tenant skincentrix --since 2026-09-01` against the live database,
September to date: **38 calls, 42.03 metered minutes, 126 model turns**. This is the first
run of it, before the speech rate moved, so the CA$ column here is the ledger as it stood at
the corrected arithmetic; the same command today prints CA$0.1196 a minute (see "September's
rows stay as they were recorded" below).

```
      call start               mins  turns        in    cached  cache%     out   chars       CA$  CA$/min
  85b942b6 2026-09-11 00:53    3.08     13   667,689   256,552     38%   4,146  10,764    0.5396   0.1755
  db10a255 2026-09-05 21:51    3.45     14   985,899   419,064     43%   5,246  11,728    0.6282   0.1824
     TOTAL                    42.03    126 6,488,708 2,493,844     38%  36,999 115,048    5.5852   0.1329
```

### The meter was counting hops, not turns

The runtime log of conversation `85b942b6` records what the provider actually reported, turn
by turn: **13 turns, 83,339 prompt tokens, 32,069 of them read from the vendor's cache, 516
output tokens, and thirty `Generating TTS` lines carrying 2,691 characters.** The ledger held
667,689 / 256,552 / 4,146 / 10,764. The ratios are not approximate:

| unit | ledger | provider | ratio |
|---|---|---|---|
| `llm_input_tokens` | 667,689 | 83,339 | **8.012** |
| `llm_cached_tokens` | 256,552 | 32,069 | **8.000** |
| `llm_output_tokens` | 4,146 | 516 | **8.035** |
| `tts_chars` | 10,764 | 2,691 | **3.999** |

`UsageObserver.on_push_frame` is called on every frame *push*, and a frame is pushed once per
processor hop. The LLM service sits sixth in a ten-processor pipeline and its `MetricsFrame`
was counted eight times on the way out; the TTS service sits eighth and its was counted four.
Fixed in `426ed94` by remembering the id of every frame already metered — keyed on the frame,
not on the pipeline's shape, so a processor added or moved cannot silently re-break it.

Two arithmetic faults sat on top of it, either of which alone misprices a month:

* **The cached tokens were billed twice.** Both providers report the cached count *inside* the
  input count — pipecat maps Gemini's `prompt_token_count` and `cached_content_token_count`
  straight across, and turn 2 of that call reports 6,046 prompt tokens of which 4,041 were
  cached for a context that had grown by 150 characters. `estimate_cad` billed all 6,046 at
  $0.25 and the 4,041 again at $0.025. It now bills the difference at the full rate.
* **The estimate priced the wrong stack.** It priced whichever candidate the September 1
  research marked `recommended` (Inworld TTS, 2.5 Flash) while the quote builder priced
  `live_stack` (Soniox TTS, 3.1 Flash-Lite). The overview card and the quote page put two
  different numbers on the same month. Both now price `live_stack`.

`cost_report` priced each metered row on its own, which re-introduced the double charge one
provider at a time; it now prices the bag per tenant, channel and provider.

### The corrected month

| | ledger | corrected | per turn | per call-minute |
|---|---|---|---|---|
| input tokens | 6,488,708 | **811,088** | 6,437 | 19,312 |
| of them cached | 2,493,844 | **311,730** | 2,474 (38%) | 7,417 |
| output tokens | 36,998 | **4,625** | 37 | 110 |
| characters sent to be spoken | 115,048 | **28,762** | — | 684 |
| model turns | 126 | 126 | — | 3.00 |

Against the old sheet's assumptions: **turns a minute were exactly right** (3.00 against 3.0),
the *size* of a turn was nearly right (6,437 input tokens against the 5,600 assumed, 37 output
against 60 — better than assumed), and the characters were 1.66x, not 6.6x. One assumption was
badly wrong and it is the whole of the model half of the gap: the sheet allowed **600** input
tokens a turn at the full rate on the belief that a cache would read the rest. It reads 2,474.

### Before, by component

```
                                                     tel     stt     tts     llm     total
as the portal's card showed it                   0.01806 0.00278 0.05706 0.06989 = 0.14779
the task brief's baseline (live stack, 8x meter) 0.01806 0.00278 0.05363 0.03692 = 0.11139
the same month, meter corrected                  0.01806 0.00278 0.01341 0.00461 = 0.03887
```

STT was never missing. `stt_seconds` has been recorded by `_finalize` since the first voice
commit and priced by `estimate_cad` all along; the usage *day row* never showed the field, so
the founder's cost table read as though transcription were free. The row now carries it and
the contract snapshot is regenerated.

**September's rows stay as they were recorded.** The observer fix cannot reach back into
`usage_events`, and nothing in this task writes to the production database. So
`spatalk cost breakdown --tenant skincentrix --since 2026-09-01` on this branch still prints
CA$0.1196 a minute for September — the old rows at the new prices — and the month's
reconciliation will read about eight times high against the Gemini invoice and four times
high against Soniox. Divide the September LLM figures by 8 and the characters by 4, or read
the month from the invoice. Every call from the first restart after this branch lands is
honest without arithmetic.

---

## 2. Where the tokens and the characters go

### The tokens: 5,930 of them are the same bytes every turn

Regressing the provider's own `prompt tokens` against the context it was sent, over the
thirteen turns of `85b942b6`:

```
 ctx chars  prompt tok  cache read    fitted
       284        6018           -      5974
      1992        6212           -      6235
      3485        6435        4009      6464
      5793        6851        3985      6817
slope 0.15305 tokens per logged context character  ->  6.53 log chars a token
intercept 5930 tokens = the static request (system instruction + tool declarations)
```

The static half is **5,930 tokens** and the growing history is 480 to 920. At 3 turns a minute
and $0.25 a million, every 1,000 tokens of static prompt costs **CA$0.00104 a call-minute**.
Where they sit, for the Skincentrix bundle (20,428 characters of system message before this
task, at the measured 3.7 characters a token):

| section | chars | tokens | CA$/min |
|---|---|---|---|
| FACTS (the knowledge base) | 8,083 | 2,185 | 0.00227 |
| SERVICES (42 rows from `services.yaml`) | 5,416 | 1,464 | 0.00152 |
| FREQUENTLY ASKED | 1,587 | 429 | 0.00045 |
| HARD RULES | 1,752 | 474 | 0.00049 |
| ON THE PHONE | 1,104 | 298 | 0.00031 |
| HOW YOU SOUND | 1,007 | 272 | 0.00028 |
| WHAT YOU CAN DO | 733 | 198 | 0.00021 |
| preamble, hours, wrapping up, right now | 746 | 202 | 0.00021 |
| tool declarations (3 at the Q&A step, 4–5 at the others) | ~1,340 | ~360 | 0.00037 |
| the step brief | 84–381 | 23–103 | 0.00003–0.00011 |

### The prefix does not move, and the cache does not care

The task's hypothesis — and the slot engine design's §7 worry, and item 5 of yesterday's
regression report — was that swapping the tool list per step drops the vendor's implicit cache
for the rest of the call. **The measurement rejects it.**

The static half is already byte-identical at every step: the brief rides after `STEP_MARKER`
at the end of the system message, and `tests/test_prompt_budget.py` now pins that both on the
pure functions and on a live session through `sync_context`. What changes between turns is the
brief and the tool list, and neither costs a cache hit:

| turn | prompt tokens | cache read | tool the model called on the turn before |
|---|---|---|---|
| 1 | 6,018 | — | (words only — nothing cached yet) |
| 2 | 6,046 | — | `start_request` (step moved) |
| 3 | 6,091 | **4,041** | `answer` (step moved) |
| 4 | 6,212 | — | `answer` |
| 5 | 6,369 | — | `choose_service` |
| 6 | 6,349 | **4,018** | `change_answer` (step moved) |
| 7–10 | 6,418–6,614 | **4,014 / 4,009 / 4,005 / 4,002** | words only |
| 11 | 6,670 | **3,995** | `start_request` (ignored) |
| 12 | 6,761 | — | `choose_service` |
| 13 | 6,851 | **3,985** | words only |

Turn 3 changed step and hit. Turn 2 changed step and missed. Turns 4 and 12 missed with the
same tool as turns that hit. There is no correlation with the step, and none with the gap
since the previous request either (turn 4 at +28 s missed, turn 10 at +25 s hit).

What the four logged calls do show is a **ceiling**. The `cache read input tokens` figure is
3,985 to 4,063 every single time it appears, across all four calls — including the 2026-09-03
calls whose static half was 7,400 tokens, not 5,930. A divergence point would move with the
prompt; this does not. So everything above roughly 4,050 tokens is billed at the full rate on
every turn whatever we hold identical, and the cache is best effort on top of that: it
appeared on 8 of 13 turns, 7 of 11, 6 of 13 and 8 of 12 — 29 of 49, 59%.

**Consequence: sending the full tool list every turn to hold the prefix identical buys
nothing and costs about 550 tokens a turn.** Not done. The only implicit-cache lever left is
total tokens a turn, priced linearly at CA$0.00104 a thousand.

### The characters: 1,100 a spoken minute, not 825, and 28% never heard

Pairing `Bot started speaking` / `Bot stopped speaking` with the `Generating TTS` lines
between them, on the spans no barge-in cut:

| call | uninterrupted spans | chars | seconds | chars a spoken minute |
|---|---|---|---|---|
| 2026-09-03 call17 | 7 | 1,361 | 68.5 | **1,193** |
| 2026-09-03 call18 | 10 | 2,002 | 105.0 | **1,144** |
| 2026-09-03 call19 | 9 | 1,588 | 83.8 | **1,136** |
| 2026-09-10 | 13 | 1,138 | 62.8 | **1,087** |

The sheet assumed 825. That single number was doing two jobs: it set `chars_per_spoken_minute`
*and* it was the divisor that turned Soniox's "$0.70 an hour of generated speech" into the
$14.1 per 1M characters in the table. Being 33% low in both places, the two errors partly
cancelled — which is why the sheet's TTS line was closer to the truth than the sheet's
reasoning was.

The second finding is the waste. On the 2026-09-10 call the runtime sent 2,691 characters to
be spoken and the line carried **107.1 seconds** of audio in a 185-second call — the assistant
spoke for 58% of the clock. At 1,087 characters a spoken minute, 107.1 seconds is 1,940
characters. **751 characters, 28% of what we sent, were cut off by one of the four barge-ins
and never heard.** They are visible span by span:

```
   chars    secs  chars/min  cut
     373   22.32       1003
     339   11.16       1822  CUT
     330    0.67      29508  CUT     <- the whole turn queued, two thirds of a second played
     347   14.53       1433  CUT
     537   17.98       1792  CUT
```

Who pays for that turns on where the vendor's meter is, and the code says the vendor does
not. Soniox quotes per hour of *generated* speech, and a barge-in stops the generating:
`TTSService._handle_interruption` drops the sentences still in the serialization queue and
calls `on_audio_context_interrupted` for every open stream, which `SonioxTTSService`
implements by sending `{"stream_id": ..., "cancel": true}` and taking `terminated` back
(`pipecat/services/soniox/tts.py`, `_close_stream`). Audio the vendor is told not to make is
audio it cannot charge for, while our character count held every sentence we queued
regardless. So the character meter over-states an interrupted call and the seconds meter does
not — which is the change in `f0f5795`.

**A correction to that commit's own message.** It says the socket is "torn down", citing the
reconnect in `InterruptibleTTSService._handle_interruption`. `SonioxTTSService` extends
`WebsocketTTSService`, not `InterruptibleTTSService`, so that is not the path: the socket
stays up and the stream is cancelled by name. The conclusion is the same and stronger — an
explicit cancel is a better guarantee than a dropped connection — but the mechanism named in
the commit is the wrong one, and it is the one a reader would go looking for.

Two other candidates, measured and dismissed:

* **The double question fixed yesterday.** Seven queued "What did you have in mind?" (182
  characters) and a duplicate "Is there someone in particular…" (73). Yesterday's `ff065ae`
  and `e8ae57d` take out about 229 characters of 2,691, 8.5%, and add back the model's words
  on the two turns an ignored tool now hands to it. Already on main; nothing more to do.
* **The sentence cap.** The prompt promises "at most 3 sentences" and the guard does not
  enforce it. Measured across the four calls, a turn queued more than three utterances **3
  times in 49 turns**. Two of the three are the 2026-09-10 turns where the fourth utterance
  was the runtime's own step question on top of three model sentences — the thing yesterday's
  `ff065ae` fixed, and not something a model-sentence cap touches. The third is call19 turn 4
  on 2026-09-03, before the slot engine put a question of its own on a turn: four model
  utterances, 377 characters. If that recurs at one turn in sixteen it is worth about
  **CA$0.0002 a call-minute** — the same order as the service ids — against a real risk of
  truncating the side answer §4.3 wants in full. Not shipped; see "Rejected".

---

## 3. The levers, biggest first

| # | lever | CA$/call-min | measured or projected | shipped |
|---|---|---|---|---|
| 1 | one metrics frame is one reading | **−0.0725** | measured exactly (x8.012, x8.000, x8.035, x3.999) | `426ed94` |
| 2 | cached input tokens billed once | **−0.0247** | arithmetic on the ledger as it stood | `426ed94` |
| 3 | the estimate prices `live_stack` | **−0.0117** | arithmetic (Flash-Lite against 2.5 Flash, Soniox against Inworld) | `426ed94` |
| 4 | the Soniox rate re-derived at the measured speaking rate | **−0.0033** | measured (1,087–1,193 chars a spoken minute against 825) | `f0f5795` |
| 5 | speech metered in seconds, not characters | **−0.0007** | measured (107.1 s against 2,691 chars on the 09-10 call) | `f0f5795` |
| 6 | "three in a breath" covers people, not just treatments | **−0.0006** | projected from one observed utterance (248 chars of nine names, 13 s of speech) | `79ef5c9` |
| 7 | service ids out of the prompt | **−0.0002** | measured (779 chars, 212 tokens a turn) | `c8fae86` |
| 8 | explicit context caching | −0.0019 net | projected; needs a live call | **no** — see "Rejected" |
| 9 | the full tool list every turn, for prefix identity | 0.0000 | measured: the cache ignores the tool swap | **no** |
| 10 | the sentence cap enforced in the guard | −0.0002 | measured: 3 turns in 49, two of them not the model's | **no** |
| 11 | `LLM_MODEL` back to 3.1 Flash-Lite | −0.0010 | published prices | **founder's call** — not touched |

Levers 1, 2 and 3 are each against the line above them in the table in "The short version",
so together they are the CA$0.1478 -> CA$0.0389 the reporting was wrong by. Levers 4 to 7 are
real money off the corrected number: CA$0.0048 of a CA$0.0389 minute, 12%.

Levers 1 to 3 move what the founder is *told* a call costs, not what a call costs. They are
first because a wrong meter is worse than a dear one: it was hiding that the real gap is 14%
and not 266%, and every decision made from it — which model, which vendor, what to charge —
would have been made from a number four times too high.

### Lever 11 in detail: the model running is not the model priced

`LLM_MODEL=gemini-3.5-flash-lite` in the deployed `.env`; the quote prices
`gemini_31_flash_lite`; the table had no row for 3.5 at all. Both are now in it from
ai.google.dev/gemini-api/docs/pricing, fetched 2026-09-10, paid tier:

| | input | cached input | output | cache storage |
|---|---|---|---|---|
| Gemini 3.1 Flash-Lite | $0.25 | $0.025 | $1.50 | $1.00 per 1M tokens an hour |
| Gemini 3.5 Flash-Lite | $0.30 | $0.03 | $2.50 | $1.00 per 1M tokens an hour |

3.5 is dearer on every line: +20% input, +20% cached, +67% output. At the measured shape of a
call (6,437 input tokens a turn, 2,474 cached, 37 output, 3 turns a minute) that is
**CA$0.00579 a minute against CA$0.00483** — running 3.5 costs **CA$0.00096 a call-minute
more**, CA$0.72 a month at 250 three-minute calls. The 2026-09-05 note guessed 3.1's cached
rate at a tenth of input and the published page agrees.

`LLM_MODEL` was not changed anywhere, as instructed. The decision is the founder's: 3.1 is
cheaper by a tenth of a cent a minute and the two have not been compared on a call.

---

## 4. After

```
                                                     tel     stt     tts     llm     total
as the portal's card showed it                   0.01806 0.00278 0.05706 0.06989 = 0.14779
after this task, characters priced               0.01806 0.00278 0.01009 0.00439 = 0.03533
after this task, seconds priced                  0.01806 0.00278 0.00940 0.00439 = 0.03464
... and three names in a breath (projected)      0.01806 0.00278 0.00880 0.00439 = 0.03403
the re-derived sheet                             0.01806 0.00278 0.00940 0.00456 = 0.03480
the old sheet                                    0.01806 0.00278 0.00808 0.00152 = 0.03042
the floor: telephony + transcription             0.01806 0.00278       —       — = 0.02084
```

The sheet's line is a hair above the measured one because its 3,900 uncached tokens a turn
leave room for a clinic with a longer catalogue than Skincentrix's forty-two treatments. The
sheet is left at 0.0348 rather than pulled down to the projected 0.0340: a quote should not
spend a saving that only an ear has yet to confirm.

### The floor, and what is above it

**CA$0.0208 a call-minute is immovable by code**: Telnyx inbound at $0.0095 plus the
WebSocket stream at $0.0035, and Soniox real-time transcription at $0.002 a minute. 60% of a
minute, and no engineering touches it. The only levers there are commercial — Plivo at
$0.0075 all-in instead of Telnyx's $0.013 would take CA$0.0076 a minute out, which is more
than every software lever in this task put together, at the cost of a vendor with no stated
Canadian PoP.

Above the floor there is **CA$0.0140**: CA$0.0094 of speech and CA$0.0046 of model. The old
sheet allowed CA$0.0096 for both. Closing that last CA$0.0044 would mean the assistant
speaking a third less (a product decision, not an engineering one — the two longest
utterances of the 09-10 call were the 347-character new-client offers recital and a
248-character list of nine practitioners; the second is what lever 6 shortens and the first
is a tenant script) or the model thinking on a third of the tokens. Neither is available tonight, and neither is worth
CA$0.0044 a minute against CA$999 a month.

### The margin question

At CA$0.0348 a minute and the founder's 65% margin, the retail number is **CA$0.0994 a
call-minute** (CA$0.298 for a three-minute call). At the CA$999 list price and the assumed
250 calls a month a clinic on the live stack costs CA$83.07 all in — CA$26.11 of voice,
CA$21.98 of SMS conversations, CA$5.21 of outbound texts, CA$0.76 of web chat, CA$4.50 of
number rental and CA$24.51 of platform — and clears **91.7%**. The margin stays above 65%
until roughly **2,800 calls a month**, eleven times the assumed volume. `costmodel.py` still
exits 0 and still passes its gates on the research stack too (91.3% at one tenant against the
65% the brief asks, 92.9% at three against 80%).

---

## 5. The sheet, line by line

`runtime/spatalk/rates.json` and `docs/research/rates.json`, pinned equal by
`test_the_packaged_rates_match_the_researched_table`. Every changed number carries a `_note`
giving its source.

| key | was | now | source |
|---|---|---|---|
| `assumptions.turns_per_minute` | 3.0 | 3.0 | measured 3.00 — unchanged |
| `assumptions.output_tokens_per_turn` | 60 | **37** | measured |
| `assumptions.input_tokens_cached_per_turn` | 5,000 | **2,500** | measured 2,474 |
| `assumptions.input_tokens_uncached_per_turn` | 600 | **3,900** | measured 3,963 |
| `assumptions.agent_speaking_fraction` | 0.5 | **0.58** | measured (107.1 s of 185) |
| `assumptions.chars_per_spoken_minute` | 825 | **1100** | measured (four calls, mean 1,140) |
| `assumptions.avg_call_minutes` | 3.0 | 3.0 | business assumption, kept and flagged |
| `tts.soniox_tts.per_spoken_min` | — | **0.011667** | soniox.com/pricing: $0.70 an hour |
| `tts.soniox_tts.per_1m_chars` | 14.1 | **10.61** | that price at 1,100 chars a spoken minute |
| `llm.gemini_31_flash_lite` | guessed cached rate | published, + storage | ai.google.dev, 2026-09-10 |
| `llm.gemini_35_flash_lite` | — | **new row** | ai.google.dev, 2026-09-10 |

`costmodel.py` gained the live stack as its first section — the stack the quote prices and the
calls run on, which it had never priced — and prices a per-hour speech vendor on the speaking
fraction directly rather than through a character count. A test pins `per_1m_chars` equal to
`per_spoken_min / chars_per_spoken_minute`, so the two cannot drift apart through one being
edited and the other forgotten.

---

## 6. Rejected, with the measurement that rejected it

* **The full tool list every turn, to hold the request prefix byte-identical.** The prefix is
  already byte-identical; the vendor's cache reads about 4,050 tokens of it whatever follows,
  and the hit/miss pattern has no relation to the step change (table in §2). The change would
  add ~550 tokens a turn, CA$0.00057 a minute, for a benefit the data says is zero, and it
  would take `file_request` and `send_link` out of the slot engine's schema-level guarantee
  (design §3.1) and leave them resting on the runtime gate alone. The measurement is committed
  as tests rather than as a change.
* **Explicit context caching (`cachedContents`).** The arithmetic *does* beat implicit
  caching, though not by much. The static prefix is 5,718 tokens after this task; cached
  explicitly it is billed at $0.025 on every turn instead of $0.25 on the 41% of turns the
  implicit cache misses and the 1,700 tokens it never reaches. Per call-minute the model line
  goes CA$0.00440 -> CA$0.00136, and storage at $1.00 per 1M tokens an hour with a 10-minute
  TTL per call adds CA$0.00120 back: **net CA$0.00185 a minute, 5% of the total**. It is
  ruled out tonight for three reasons, all of them recorded so the founder can overrule them:
  1. A cache holding the system instruction can only be reused while that instruction is
     identical, so the step brief would have to come out of the system message and go
     somewhere else. Every candidate somewhere-else changes behaviour: a second system message
     reads as the assistant's own words on the Gemini client (slot engine report, deviation 1),
     and a user or model message enters the transcript through `_finalize`.
  2. A cache holding the tools needs the tool list fixed, which is the rejected lever above.
  3. Keeping one warm between calls is the obvious implementation and the ruinous one: 5,718
     tokens alive around the clock is $4.11 a month against a total model bill of CA$0.19.
     Only a per-call cache with a short TTL wins, which means a create round trip at the head
     of every call — latency the founder has complained about twice — and there is no way to
     measure either the saving or the latency without a live call.
* **Enforcing the sentence cap in the guard.** 3 turns in 49 queued more than three
  utterances; two were the runtime's own question on top of three model sentences, which a cap
  on the model does not touch, and the third predates the slot engine. About CA$0.0002 a
  call-minute if the pre-slot-engine behaviour recurs, against the risk of cutting a side
  answer off mid-explanation on a demo call. Worth revisiting once a call confirms the
  four-sentence turn still happens.
* **Deduplicating the catalogue between `services.yaml` and `knowledge.md`.** The 42
  treatments are in the prompt twice: once as the SERVICES block (name, price, one detail) and
  once as the knowledge base's "Treatments and prices" section (4,392 characters, 1,182
  tokens, **CA$0.00123 a call-minute**), which is the largest single cut left. It is not a code
  change: the durations and repeat intervals only exist in the prose, so they would have to
  move into `services.yaml` and be rendered, and the founder's own wording would be rewritten
  by an agent overnight. Recorded for the founder to approve.
* **`TURN_END_FALLBACK_SECS`, barge-in tuning, audio tags.** Out of scope and unchanged.

---

## 7. Deviations

* **`estimate_cad` changed the stack it prices**, which changed
  `test_estimate_cad_prices_the_recommended_stack`. Renamed to
  `test_estimate_cad_prices_the_live_stack` and recomputed from the table, with the USD
  arithmetic written out in the comment. It was asked for by the task; recorded because it is
  an existing test whose expectation moved.
* **`test_qa_gate_a.py::test_usage_observer_accumulates_llm_and_tts_metrics` asserted the
  defect.** It pushed one frame twice and expected the totals to double. Rewritten to assert
  both halves — two frames accumulate, the same frame twice does not — so the gate is
  stronger, not weaker, than it was.
* **The portal's `pricing.test.ts` moved with the assumptions.** It is the same arithmetic in
  TypeScript over the same `rates.json`, so thirteen pinned figures changed. Every one was
  recomputed from the file by re-implementing the TypeScript's own formulas in Python and
  comparing against `costmodel.py`'s output, not adjusted to fit. The portal's
  `voicePerMinute` still prices speech per character and gets the same answer as the Python's
  per-hour path because the test pins the two rates consistent; it was left alone deliberately.
* **`commit f0f5795` left one test red.** Changing the Soniox rate moved
  `test_estimate_cad_prices_the_live_stack`, which was not in the set run before that commit.
  Corrected in `1e0e8ac` with the arithmetic in the comment. Recorded rather than rewritten.
* **`docs/contracts/runtime-internal.openapi.json` regenerated** (`spatalk openapi
  --internal`) for the `stt_seconds` field on `UsageDay` and `UsageTotals`, and
  `portal/src/runtime/client.ts` regenerated from it (`npm run gen:client`, openapi-typescript
  7.13.0 — the four lines the generator emits and nothing else), so `npm run check:client`
  still passes. Nothing in the portal reads the field yet; it is there for the cost card to
  show the transcription line when the founder wants it.
* **One fault of my own, found on review and fixed in `4cdcad5`.** `call_costs` took the
  window's open end from `date.today()`, the clock of whatever machine runs the report rather
  than the tenant's own day. A founder in Toronto reading a clinic in Vancouver would have
  lost its evening, and the new test — the founder's call of 2026-09-11 00:53 UTC, which is
  still 2026-09-10 in Toronto — would have started failing at the next midnight.
* **`cost_report` now prices a bag rather than a row.** Same per-provider attribution — units
  of one model always share a tenant, a channel and a provider — but it is a behaviour change
  in a module this task was not asked to touch, and it was necessary: pricing
  `llm_input_tokens` and `llm_cached_tokens` separately re-introduces the double charge.
* **The measurement CLI reads the production database.** `spatalk cost breakdown` was run
  against `spatalk` to produce §1, read-only, with no writes of any kind. The internal API was
  read with GET only.
* **`f0f5795` named the wrong interruption mechanism**, corrected in `73e4f8a`. It said the
  websocket is torn down, citing `InterruptibleTTSService`; `SonioxTTSService` extends
  `WebsocketTTSService`, so the socket stays up and the stream is cancelled by name instead.
  Same conclusion, stronger guarantee, wrong citation — and the citation is what a reader
  would have followed. Comments and docstrings only.
* **Token counts are an approximation where they are not the provider's own.** The
  provider-reported figures (5,930 static, 6,437 a turn, the cache reads) are measured. The
  per-section split in §2 is characters divided by 3.7, calibrated against that same
  measurement; no tokenizer was downloaded and no `count_tokens` call was made, as instructed.

---

## 8. Needs a live call to confirm

1. **The seconds meter against a real bill.** `tts_seconds` is recorded from
   `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` and priced at $0.70 a spoken hour.
   Whether Soniox's invoice agrees is the only test that matters, and `spatalk cost report
   <month>` with the invoice entered is the instrument: it prints the drift per provider. Enter
   the September invoices and read it.
2. **Whether Soniox bills for a cancelled utterance.** The runtime sends `cancel: true` for
   the open stream, so the audio it never makes should not be billed; the text it already
   received is still $4 per 1M input text tokens, a sixth of the blended price. If the
   invoice comes in above the seconds meter by roughly that sixth, the answer is the text
   half, and the character meter's number is the safer one to quote.
3. **The implicit cache's ~4,050-token ceiling.** Four calls, one vendor, one model. If the
   ceiling is really a cap, no amount of prompt work below 4,050 tokens buys more caching and
   the only lever is total tokens. If it is a block boundary, a static half just under 8,192
   tokens might cache twice as much, which would be an argument for a *bigger* prompt. Two
   deliberate calls with a padded and an unpadded prompt would settle it; neither can be done
   without paid calls.
4. **Explicit caching's latency at the head of a call.** The arithmetic is CA$0.00185 a
   minute. The cost is a create round trip before the first token. Unmeasurable from a desk.
5. **3.1 against 3.5 Flash-Lite on the ear.** 3.1 is CA$0.00096 a minute cheaper. Nobody has
   heard a call on it: the whole slot-engine era ran on 3.5. Worth one call before the price
   decides.
6. **The speaking fraction on a real conversation.** 0.58 comes from one call with exact
   boundaries. Every call from here records `tts_seconds` and `telephony_seconds` together, so
   the next three calls give it properly — and the assumption in the sheet is the one number
   the speech line is most sensitive to.
7. **Whether three names and an offer sound better than nine.** Lever 6 narrows "never list
   more than three options in one breath" to cover people. It should read better on the phone
   as well as cheaper — the nine-name recital is in the voice regression report's own list of
   what made the call feel long — but it is a prompt change and only an ear can confirm the
   model now offers the rest rather than dropping them.
8. **A deterministic yes/no fast path.** The runtime asks the yes/no questions and the model
   is called only to route the answer into `answer(value)`. On the one logged slot-engine call
   that was 2 of 13 turns; skipping the model on a bare "yes" or "no" would take about 15% off
   the model line, CA$0.0007 a minute. It cannot be shipped from a desk: a caller who answers
   "no, but what's your address?" must still reach the model, and the only way to know how
   often that happens is to listen.

---

## 9. Full suite

One scratch database for every run in this task, created with
`docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_cost_2305"`.
`spatalk`, `portal` and `spatalk_test` were not written.

The green run below is the only one that counts, and it is the third attempt. The first was
abandoned because I ran small test files against the same scratch database while it was going,
and the `engine` fixture drops and recreates the schema for every test — two pytest sessions
on one database are two sessions rewriting each other's tables. The second was abandoned
deliberately, to keep the claim exact: it was already running when I found the dead constant
and the wrong interruption citation, so it would have been green on a tree that no longer
existed. This one ran alone, on this tree, with nothing else touching the database.

```
cd runtime && TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_cost_2305 \
  .venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider

FAILED tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick
1 failed, 1367 passed, 2 skipped, 1 warning in 1916.72s (0:31:56)
```

1,367 of 1,368 runnable tests pass, against 1,343 on `main` before this branch: the 24 new
ones and not one existing test lost. The one failure is the pre-existing scheduler timing
test below.

`ruff check spatalk tests scenarios` -> All checks passed.
`python docs/research/costmodel.py docs/research/rates.json` -> exit 0.

### The one failure that is not mine

`tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick` fails on this
machine and failed identically on `main` before this branch, as yesterday's regression report
records. It starts `run_scheduler_forever` and polls for three seconds; nothing in this task
goes near the scheduler, the job queue or the alert module. Checked rather than assumed:

```
git archive 145f5dc runtime | tar -x -C <scratch>          # main, before this branch
cd <scratch>/runtime && PYTHONPATH=. pytest "tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick"
  FAILED ... asyncio.exceptions.CancelledError
  1 failed in 6.70s
```

Same failure, same line, on the tree this branch started from. Left alone.

### The promptfoo suite was not run

`scenarios/promptfooconfig.yaml` needs `GOOGLE_API_KEY` and a paid Gemini call a case. Two
changes here reach the model and both want a run at the next QA gate:

* **The service ids left the SERVICES block.** No case asserts on an id — they set
  `service_id` in `slots` directly, and `choose_service` has always taken the caller's own
  words — so nothing should move. The case to watch is any that names a treatment and expects
  `choose_service` to resolve it, since the catalogue is now name-and-price only.
* **"Never name more than three treatments or three people in one breath."** The cases that
  ask for options expect two or three named with prices, which is what the rule still allows;
  none asks for the team. A model that reads the rule as a reason to name nothing would show
  up there first.

## The measurement scripts

Every number in this report that is not the runtime's own output came from a short script in
the scratchpad (`…/scratchpad/cg/`), each run against the ANSI-stripped call logs in
`…/scratchpad/v1/`. They are throwaway, but they are the working, so they are named:

| script | what it measures |
|---|---|
| `tok.py` | per-turn prompt, cached and completion tokens, and every `Generating TTS` line, from one log |
| `regress.py` | prompt tokens against context size -> the 5,930-token static request |
| `cache.py` | each turn's cache read beside the tool the model called, for the step-change hypothesis |
| `spans.py` | per speaking span: characters queued, seconds played, whether a barge-in cut it |
| `spoken.py` | the same summed per call -> characters a spoken minute |
| `turnlen.py` | utterances and characters per model turn, for the sentence cap |
| `compose.py`, `cuts.py` | the system prompt section by section, and what each candidate cut is worth |
| `chain.py` | the lever chain in §3, one line per change, from the ledger totals |
| `portalnums.py` | the TypeScript pricing formulas in Python, to recompute the portal's pinned figures |

`spatalk cost breakdown` replaces `tok.py` and `regress.py` for every call from here: it reads
the ledger rather than a log, and the ledger is now honest.

## Notes for neighbours

* `spatalk.rates.estimate_cad` is unchanged in signature and now sums
  `components_cad(usage)`. Anything wanting the split should call `components_cad`;
  `COMPONENTS` names the seven lines in print order.
* `recommended_stack` is still exported and still means the September 1 research's pick. It no
  longer decides what the portal shows. `live_stack(rates=None)` is the product's stack.
* `UsageEvent.unit` gained `tts_seconds`. No migration: `unit` is a string column. Old rows
  have no seconds and are priced from their characters, which is exactly what
  `telephony_seconds` versus `call_minutes` already does.
* `VoiceSession.usage` gained a `tts_seconds` key. Anything asserting the whole dict needs it.
* `UsageTotals` on `/internal/tenants/{id}/usage` gained `stt_seconds` (a float, seconds).
  Additive; the contract snapshot is regenerated in `426ed94`.
* `_services_text` no longer renders service ids. If a future tool ever takes an id from the
  model, the ids have to go back and `test_a_service_id_is_never_spent_on_the_prompt` is the
  test that will say so.
* `tests/test_prompt_budget.py` fails when the system prompt passes 22,000 characters or the
  estimated static request leaves the 5,000–6,500 token band. Both are cost decisions. Move
  them deliberately and say what the minute now costs.
* The HOW YOU SOUND rule now reads "Never name more than three treatments or three people in
  one breath". `test_three_in_a_breath_covers_people_as_well_as_treatments` pins both halves,
  so the treatments half cannot be dropped while tidying the people half back out.
* `spatalk.ops.cost_breakdown` is the only module that reads `Conversation.latency_ms` as a
  turn count. If a future change writes one reading per something-other-than-a-turn, the
  breakdown's turn column and the per-turn token figures in this report go with it.
