# LLM Failover Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Tests first (write the test, see it fail, make it pass, commit). Read `CLAUDE.md` (non-negotiable 4: providers are swappable, never hard-wire a vendor; 6: Pipecat 1.8 API), `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §10 (vendor risk), `runtime/spatalk/voice/pipeline.py` (`make_llm`, `run_call`, the pipeline order, `register_tool_handlers`), `runtime/spatalk/voice/resilience.py` and `runtime/tests/test_llm_resilience.py` (what already exists: SDK retries and the spoken `model_unavailable` line), `runtime/spatalk/brain/driver.py` (`provider_for`, `model_name`, `GeminiClient`, `OpenAIClient`), `runtime/spatalk/text/service.py` (`make_text_llm`), `runtime/spatalk/settings.py`, `runtime/tests/test_ops_model_check.py` and `test_llm_thinking.py` (how `make_llm` is tested with fakes). Status: **founder decision 2026-09-03 ~21:20 ("we need to operate and be ready for scale") after Google answered every request with 503 for twenty minutes.**

**Goal:** One vendor being down never takes the front desk down. Every conversational turn, on the phone and on text, has a primary model and a secondary model from a different vendor; when the primary fails after its retries, the same turn is answered by the secondary within about a second, the caller hears an answer rather than an apology, and the runtime keeps using the secondary for a cooling-off period before trying the primary again. A call that cannot reach any model ends with a fixed line that sends the caller to the clinic's own number, not a loop of apologies.

**Architecture:** Two additions in the runtime, no change to prompts, tools or the ledger. (1) A process-wide **breaker** per vendor: failures within a window open it, a cooldown closes it; `make_llm`-time and per-turn decisions read it. (2) A **router** in the voice pipeline that holds both LLM services and forwards each `LLMContextFrame` to the active one; on the primary's error for a turn it re-sends that same context to the secondary at once. On text channels the equivalent is a `FailoverLLMClient` that wraps two `LLMClient`s. The settings gain `LLM_MODEL_FALLBACK` (empty by default: today's behaviour, no failover) and the health endpoint reports which vendor is active.

**Tech Stack:** Pipecat 1.8.1 (`GoogleLLMService`, `OpenAILLMService`, `FrameProcessor`, `LLMContextFrame`, `ErrorFrame`, `PipelineWorker` events), google-genai, openai; existing fakes in tests.

**Spec:** §10 weakness 3 (the swap must be an environment change). This plan makes the swap automatic and keeps it an environment change.

## Global Constraints

- Non-negotiable 4: nothing names a vendor outside `driver.py`'s provider table and `make_llm`. The fallback is whatever `LLM_MODEL_FALLBACK` names, in the same `vendor:model` syntax as `LLM_MODEL`; a bare name is Google, `openai:` is OpenAI. Adding a third vendor later is a table entry.
- Non-negotiable 1 and 5: both services pass through the same `OutputGuardProcessor`, the same tool handlers and the same context; secrets stay in the environment (`OPENAI_API_KEY`, `GOOGLE_API_KEY`).
- No paid API is called by tests or by the agent; the breaker and the router are proved with fake services that raise on demand.
- Latency: a failover adds one model call; it never adds a retry storm. The primary's SDK retries stay as they are (three attempts within about four seconds); the secondary gets one attempt per turn.
- Do not restart or touch the running runtime, its `.env`, or its database; work against scratch test databases (create your own: `docker exec runtime-db-1 psql -U spatalk -d postgres -c "CREATE DATABASE spatalk_test_failover"`). The orchestrator restarts the runtime with `scratchpad/restart-runtime.sh`, which refuses while a call is live.

## File Structure

```
runtime/spatalk/settings.py                       llm_model_fallback: str = "" (env LLM_MODEL_FALLBACK); llm_breaker_failures: int = 3; llm_breaker_window_secs: int = 60; llm_breaker_cooldown_secs: int = 300
runtime/spatalk/brain/breaker.py (new)            VendorBreaker: record_failure(vendor), record_success(vendor), is_open(vendor) -> bool, active(primary, secondary) -> str; one process-wide instance, monotonic clock injectable
runtime/spatalk/brain/driver.py                   FailoverLLMClient(primary: LLMClient, secondary: LLMClient, breaker, vendors) implementing complete(); TRANSIENT_STATUSES reused
runtime/spatalk/text/service.py                   make_text_llm builds the FailoverLLMClient when the fallback is set
runtime/spatalk/voice/llm_router.py (new)         LLMRouter(FrameProcessor): owns primary and secondary services; forwards LLMContextFrame to the active one; on the primary's error for the current turn re-sends the context to the secondary; records success/failure on the breaker
runtime/spatalk/voice/pipeline.py                 make_llm returns (primary, secondary | None); the pipeline places `LLMRouter` where `llm` was; register_tool_handlers on both; apology_for_error only when the router has no secondary or both failed
runtime/spatalk/voice/resilience.py               model_down: after two failed turns with no answer in between, speak scripts.model_down and end the call
runtime/spatalk/tenants/schema.py + tenants/skincentrix/scripts.yaml + docs/reference/tenant-config.md   scripts.model_down: "I'm sorry, I'm not able to help on this line right now. Please call the clinic directly at {phone}."
runtime/spatalk/http/internal.py                  /healthz gains llm: {primary, secondary, active, breaker_open_until}
runtime/tests/test_llm_failover.py (new), test_llm_resilience.py (extended), test_ops_model_check.py (extended)
docs/reference/api-surface.md (env vars, healthz), docs/runbooks/accounts-and-env.md (the fallback key), docs/reports/2026-09-03-demo-day-state.md is the orchestrator's
```

## Task F1: Breaker, text failover, settings

**Produces:**
- `VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=time.monotonic)`: `record_failure(vendor)` keeps timestamps per vendor and opens the breaker when the window holds `failures` or more; `record_success(vendor)` clears it; `is_open(vendor)`; `active(primary, secondary) -> vendor` returns the primary unless its breaker is open and the secondary's is not. Module-level `BREAKER = VendorBreaker()` built from settings at import of `spatalk.settings`-free defaults, reconfigured by `configure(settings)` at app start.
- `FailoverLLMClient.complete(system, history, tools)`: calls the active client; on an exception from the primary (any exception, the SDK has already retried the transient ones) records the failure, calls the secondary once, records success or failure for it, re-raises only if both failed. Never swallows a tool call: the secondary's `LLMResponse` is returned as is.
- `make_text_llm(settings)` returns the plain client when `llm_model_fallback` is empty, else the failover client with `provider_for` naming the vendors.
- Settings fields and their env names as in the file structure; `docs/reference/api-surface.md` lists them.

**Tests (`tests/test_llm_failover.py`):** breaker opens on the third failure within the window and not on two; closes after the cooldown; `active()` prefers the primary when both are open (the least bad choice, and say so in a comment); the failover client answers from the secondary when the primary raises, records the failure, and raises when both raise; a tool call from the secondary comes back intact; `make_text_llm` shape for empty and set fallback (fakes, no network).

**Done when:** tests green, ruff clean. Commit `feat(brain): vendor breaker and text-channel LLM failover`.

## Task F2: Voice router

**Produces:**
- `LLMRouter(primary, secondary, breaker, vendors: tuple[str, str])`: a `FrameProcessor` that links the two services as its own children in Pipecat 1.8 terms (study how `ParallelPipeline` or the `Pipeline` class links processors and how a service's output frames reach the next processor; the router must pass every frame that is not an `LLMContextFrame` through the active service's chain unchanged so `LLMTextFrame`, `LLMFullResponseStart/EndFrame`, function-call frames and metrics behave exactly as today). For each `LLMContextFrame` it remembers the frame, forwards it to the active service; when the active service pushes an `ErrorFrame` for that turn (identify the service by the frame's source or by wrapping the service's `push_error`), it records the failure, marks the other service active if the breaker says so, and re-forwards the remembered context to the secondary; a second failure in the same turn surfaces the `ErrorFrame` downstream so the existing `on_pipeline_error` handling runs.
- `make_llm(settings)` returns `(primary_service, secondary_service_or_None)`; `run_call` builds the router when a secondary exists and registers tool handlers on both services; with no fallback configured the pipeline is exactly today's (the router is not inserted).
- `resilience.py`: `session.model_failures` counts turns that reached the apology; on the second consecutive one with no answered turn in between, `apology_for_error` returns the `model_down` line and the caller is ended with an `EndFrame` after it (the same shape as the idle-timeout goodbye). `OutputGuardProcessor` resets the counter on `LLMFullResponseStartFrame`.
- `/healthz`: `llm: {"primary": ..., "secondary": ... | null, "active": ..., "breaker_open_until": iso | null}`.

**Tests:** the router with two fake LLM services (Pipecat `FrameProcessor`s that either answer with a fixed `LLMTextFrame` sequence or push an `ErrorFrame`), driven with `pipecat.tests.utils.run_test` and `start_timeout=10.0` as every other pipeline test in this repo: a turn answered by the primary; a turn where the primary errors and the secondary answers, with exactly one context frame reaching the secondary and no `ErrorFrame` reaching downstream; both failing surfaces one `ErrorFrame`; tool handlers registered on both; the pipeline built with no fallback has no router. `resilience.py`: two consecutive failures speak `model_down` and end; a success in between resets. Health payload test. `tests/test_ops_model_check.py` extended for the tuple return.

**Done when:** tests green, full suite green, ruff clean, docs updated. Commit `feat(voice): per-turn LLM failover to a second vendor, model_down line, health reports the active vendor`.

## Self-review against the spec

- §10: the vendor decision stays an environment change (`LLM_MODEL`, `LLM_MODEL_FALLBACK`); the code has no opinion about which vendor is which.
- §5 honesty: both models run behind the same guard and the same fixed scripts; a failover never changes wording; the `model_down` line claims nothing and gives the clinic's own number.
- Cost: a failover turn costs one extra model call; the breaker stops a dead vendor from being tried on every turn.
- Founder decision needed to activate: an `OPENAI_API_KEY` (or another vendor's) in `runtime/.env` and `LLM_MODEL_FALLBACK=openai:gpt-4.1-mini` or the model they choose; until then nothing changes at runtime.

## Addendum (founder decision 2026-09-03 ~21:40): any OpenAI-compatible host is a vendor

The founder wants to choose the cheapest model by env value alone, so the vendor table accepts every OpenAI-compatible host. Part of F1 (driver, settings, `make_text_llm`) and F2 (`make_llm`), same commits.

- `provider_for(model)` recognises these prefixes, case-insensitive, all OpenAI-compatible: `openai:` (https://api.openai.com/v1, as today), `openrouter:` (https://openrouter.ai/api/v1), `deepseek:` (https://api.deepseek.com/v1), `xai:` (https://api.x.ai/v1), `groq:` (https://api.groq.com/openai/v1), `together:` (https://api.together.xyz/v1), `fireworks:` (https://api.fireworks.ai/inference/v1), `dashscope:` (https://dashscope-intl.aliyuncs.com/compatible-mode/v1, Alibaba's Qwen), and a generic `compat:` whose base URL comes from `LLM_COMPAT_BASE_URL`. A bare name stays Google. `model_name()` strips whichever prefix.
- One table in `driver.py`: `VENDORS = {prefix: Vendor(base_url, key_field)}`, `key_field` naming the settings field with that vendor's key: `openai_api_key`, `openrouter_api_key`, `deepseek_api_key`, `xai_api_key`, `groq_api_key`, `together_api_key`, `fireworks_api_key`, `dashscope_api_key`, `compat_api_key` (env names upper-case, all default empty). `make_llm` and `make_text_llm` build `OpenAILLMService(api_key, base_url, settings)` and `OpenAIClient(..., base_url)` from the table and raise the same `ValueError` as today when the vendor's key is missing; add `base_url` to `OpenAIClient` if it lacks one, after checking Pipecat's `OpenAILLMService.__init__` against its source.
- `LLM_MODEL` and `LLM_MODEL_FALLBACK` may name any two vendors; the breaker keys on the prefix.
- Docs: `docs/reference/api-surface.md` lists every new variable with its vendor; `docs/runbooks/accounts-and-env.md` gets one line per vendor on where the key comes from.
- Tests: `provider_for` and `model_name` for every prefix; `make_llm` for a `compat:` model builds an OpenAI service with that base URL when the key is set and raises without it; `make_text_llm` likewise; the breaker distinguishes `openrouter` from `openai`. No network.
- Data handling note for the runbook: the first-party DeepSeek and DashScope endpoints process transcripts outside North America; for a health-adjacent tenant, run open-weight models through a North American host.
