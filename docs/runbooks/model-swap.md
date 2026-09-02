# Swapping the LLM vendor

The runtime holds one conversation through one model at one vendor, and the vendor decides
when that model retires. Spec §10 weakness 3 is that this has already happened once here:
`gemini-2.5-pro` answers 404 "no longer available to new users" on this account (promptfoo
run A, 2026-09-02). So the swap is designed to be an environment change, not a code change,
and this runbook is the drill that proves the change is safe before a caller meets it.

Two vendors are wired (operations plan, Task E6):

| `LLM_MODEL` | vendor | key |
|---|---|---|
| `gemini-2.5-flash` (any bare name) | Google | `GOOGLE_API_KEY` |
| `openai:gpt-4.1-nano` (any `openai:` prefix) | OpenAI | `OPENAI_API_KEY` |

One variable moves both halves of the runtime: `spatalk.voice.pipeline.make_llm` builds the
Pipecat service for a call and `spatalk.text.service.make_text_llm` builds the client for
SMS, web chat, Instagram and Messenger. Both read `LLM_MODEL` through the same two
functions, so a swap can never leave one channel on the retired model. The nightly audit's
judge is separate on purpose and is set by `JUDGE_MODEL`.

Everything below is run by a person. Steps 4 and 5 place real calls and spend real money at
two vendors; no agent runs them.

---

## 0. What tells you a swap is needed

- **The weekly check failed.** `.github/workflows/model-check.yml` runs every Monday at
  06:40 UTC and asks each provider for its model list. Exit 1 means the configured model is
  absent or the provider's own description marks it deprecated. Exit 2 means the question
  could not be asked — no key, or the provider errored — which is *not* a pass.
- Run it by hand at any time, from `runtime/`:

  ```bash
  uv run python -m spatalk.ops.model_check                      # the configured LLM_MODEL
  uv run python -m spatalk.ops.model_check --model openai:gpt-4.1-nano
  ```

- **Latency or cost moved.** `scripts/latency_report.py --days 7` (Task E5) and
  `spatalk cost report <YYYY-MM>` (Task E9) are the two numbers a swap is judged on.

---

## 1. Pick the candidate and get a key

`gpt-4.1-nano` is the OpenAI counterpart chosen for this system: cheapest tier, tool calling,
low latency. Any other OpenAI model is `openai:<model>`; any other Google model is its bare
name. Put the key in `runtime/.env` — never in a tenant bundle, never in the repository:

```
OPENAI_API_KEY=sk-...
```

## 2. Run the suite on the candidate

Nothing here calls a provider: the whole suite runs on fakes, and this step catches a
configuration that cannot even be constructed (a missing key, a prefix with no model).

```bash
cd runtime
LLM_MODEL=openai:gpt-4.1-nano uv run pytest -q
uv run python -m spatalk.ops.model_check --model openai:gpt-4.1-nano   # exit 0 expected
```

## 3. Run the adversarial scenarios against the candidate

This is the part that matters: the scenarios in `runtime/scenarios/` are the honesty cases —
a caller pressing for a booking confirmation, a clinical symptom, a payment demand, a
request for a human. A new model that answers them differently is a new product.

```bash
cd runtime/scenarios
LLM_MODEL=openai:gpt-4.1-nano npx --yes -p node@24 -p promptfoo@latest promptfoo eval \
  -c promptfooconfig.yaml --no-cache
```

> **On this machine promptfoo must be run through Node 24.** The installed Node is 22.14 and
> promptfoo rejects it. `npx --yes -p node@24 -p promptfoo@latest promptfoo eval ...` is the
> invocation that works; the short `npx promptfoo@latest` form in `CLAUDE.md` fails here with
> an engine error. The provider key the suite needs is whichever vendor `LLM_MODEL` names.

Every case must still pass. A failure here ends the swap: record which case and stop.

## 4. Twenty calls

Point a staging number at the runtime with the candidate configured and place twenty calls
covering: a price question, a booking request, a reschedule, a clinical symptom, a payment
demand, a request for a human, and one caller who interrupts. Listen for the two failures a
test cannot hear: a claim the system did not carry out, and a turn that feels slow.

## 5. Compare, then decide

| Question | Where the number comes from | Pass |
|---|---|---|
| Turn latency | `uv run python scripts/latency_report.py --days 1` | turn p95 ≤ 800 ms, `llm` stage p95 ≤ 450 ms (`BUDGETS_MS`) |
| Cost | `python docs/research/costmodel.py docs/research/rates.json`, then next month `spatalk cost report <YYYY-MM>` | per-call cost within the model's band in `docs/research/` |
| Honesty | step 3 green, step 4 heard | no claim of an action the ledger does not hold |

Write the decision and the two numbers into this file under a dated heading. A swap with no
recorded comparison is a guess that will be re-argued in six months.

## 6. Deploy the swap

Change one line in the server's `runtime/.env`, restart, confirm the runtime is up:

```
LLM_MODEL=openai:gpt-4.1-nano
```

```bash
docker compose up -d app
curl -s https://<API_HOST>/healthz | head -c 400     # "ok":true and the new commit
```

Then place one real call before you walk away.

## 7. Rollback

The rollback is the same one line, and it needs no deploy of code:

```
LLM_MODEL=gemini-2.5-flash
```

```bash
docker compose up -d app
```

Roll back on any of: a claim the system did not carry out, turn p95 over budget on the day
after the swap (`ops.latency_report` alerts name the stage), or a provider incident. The
previous vendor's key stays in `.env` the whole time precisely so the rollback is a restart
and not a scramble for a credential. Note the rollback and its reason in this file.

---

## What is checked automatically, and what is not

- **Automatic:** the weekly `model-check` workflow (both Google models and the OpenAI one
  when the keys are present as repository secrets); the daily SLO alert on the `llm` stage
  (Task E5), whose suggested fix names this runbook; the monthly cost drift (Task E9).
- **Not automatic:** steps 4 and 5. Nothing in CI places a call or listens to one, and no
  agent may spend money at a provider (`CLAUDE.md`). The swap is not done until a person has
  heard it.
