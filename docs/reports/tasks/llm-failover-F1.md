# llm-failover Task F1: Breaker, text failover, settings
Status: done with deviations
Commit: b2ac659

Tests: `pytest tests/test_llm_failover.py` -> 41/41; full suite -> 1158 passed, 2 skipped (296 s). `ruff check spatalk tests scenarios` clean.

Seen failing first: `40 failed, 1 passed` on the first run of `tests/test_llm_failover.py` (the one pass was `test_make_text_llm_is_still_none_when_the_primary_vendor_has_no_key`, which the old `make_text_llm` already satisfied). After `breaker.py`, the driver's vendor table and `FailoverLLMClient`: `37 passed, 4 failed`, the four being the documentation assertions; green once `.env.example`, `api-surface.md` and `accounts-and-env.md` were written.

Interfaces produced: `spatalk.brain.breaker.VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=time.monotonic)` with `record_failure(vendor)`, `record_success(vendor)`, `is_open(vendor)`, `active(primary, secondary) -> str`, `failure_count(vendor)`, `open_until(vendor)`, `remaining_secs(vendor)`, `reconfigure(failures, window_secs, cooldown_secs)`, `reset()`; module-level `BREAKER`, `configure(settings) -> VendorBreaker`, `llm_health(settings, now, breaker=None) -> dict`; `spatalk.brain.driver.Vendor(base_url, key_field)` with `key_env` / `base_url_field`, `VENDORS`, `provider_for(model)`, `model_name(model)`, `base_url_for(settings, vendor)`, `vendor_key(settings, vendor)`, `FailoverLLMClient(primary, secondary, breaker, vendors)` with `.primary`, `.secondary`, `.vendors`, `complete(system, history, tools)`; `OpenAIClient(api_key, model, temperature=0.3, client=None, base_url=None)` with public `.model` and `.base_url`; `spatalk.text.service.make_client_for(settings, model)` and `make_text_llm(settings)`; `Settings.llm_model_fallback`, `llm_breaker_failures`, `llm_breaker_window_secs`, `llm_breaker_cooldown_secs`, `openrouter_api_key`, `deepseek_api_key`, `xai_api_key`, `groq_api_key`, `together_api_key`, `fireworks_api_key`, `dashscope_api_key`, `compat_api_key`, and `llm_<vendor>_base_url` for all nine vendors.

## Deviations

- **The breaker has five reading methods, not three.** The plan names `record_failure`, `record_success`, `is_open`, `active`. `failure_count`, `open_until`, `remaining_secs`, `reconfigure` and `reset` were added because the previous agent's tests already asserted them and because `/healthz` (F2) needs a deadline it can print. None of them change the four the plan named.
- **`llm_health()` lives in `breaker.py`.** The plan puts the healthz payload in F2 but names no module for it. It sits next to the breaker because that is what it reads; it imports `provider_for` inside the function so `breaker.py` still drags nothing into an import (`tests/test_llm_failover.py::test_the_module_level_breaker_needs_no_settings_to_exist` asserts the module never imports `spatalk.settings`).
- **`VENDORS` is keyed by the vendor name, not by the literal prefix.** The addendum writes `{prefix: Vendor(...)}`; the table is keyed `"openai"`, not `"openai:"`, because that is exactly what `provider_for` returns, what the breaker keys on, and what `/healthz` prints. `provider_for` matches `f"{name}:"`.
- **`spatalk/ops/model_check.py` was touched, and the plan does not list it.** Its `KEY_ENV`/`KEY_SETTING` were two-entry literals; a `groq:` model would have raised `KeyError` in the weekly model check. They are now derived from `VENDORS`, and `list_models` asks any non-Google vendor through `AsyncOpenAI(base_url=...)`. Evidence: `pytest tests/test_ops_model_check.py -q -> 51 passed`.
- **Coordinator change, mid-task, applied:** `dashscope:` defaults to `https://dashscope-us.aliyuncs.com/compatible-mode/v1` (not the Singapore `dashscope-intl` host the addendum named), and **every** vendor's base URL is overridable by `LLM_<VENDOR>_BASE_URL` — nine new settings fields, empty by default. `LLM_COMPAT_BASE_URL` is the only one with no built-in default; `base_url_for` raises naming it.
- **`make_text_llm` decides two cases the plan does not mention.** A fallback whose vendor has no key returns the plain primary with a warning (a "failover" that cannot reach a second vendor is one vendor and a misleading log line), and a primary whose vendor has no key with a working fallback returns the fallback alone (`LLM_MODEL` naming a vendor whose key was removed is still a configuration text channels can serve).
- **`configure(settings)` is called from `create_app`** (`spatalk/http/app.py`), which the plan's File Structure does not list. It is the only place the runtime has an app-start hook, and the breaker exists with defaults from import, so the call only ever adjusts it.
- **`OpenAIClient` gained `base_url`** (the addendum permitted this after checking Pipecat's source) plus public `.model` and `.base_url` attributes so the tests can assert which host a client points at without touching a private field.

## Notes for neighbours

- `provider_for` now returns nine possible vendor names plus `"google"`. Anything switching on `== OPENAI` should switch on `!= GOOGLE`; `voice/pipeline.py`, `text/service.py` and `ops/model_check.py` were updated, `scenarios/provider.py` still reads `== OPENAI` and is correct for its own purpose (it only ever builds one of the two clients the swap drill uses).
- `BREAKER` is process-wide and shared by text and voice. A test that records failures on it must reset it (`BREAKER.reset()`), which is why every test here builds its own `VendorBreaker` with a fake monotonic clock.

## What the founder must set

Nothing, until they want failover: `LLM_MODEL_FALLBACK` is empty by default and empty means today's behaviour exactly, one vendor and no second key.

To pick a vendor (either slot), in `runtime/.env`:

- `LLM_MODEL=<prefix>:<model>` — a bare name is Google; the prefixes are `openai:`, `openrouter:`, `deepseek:`, `xai:`, `groq:`, `together:`, `fireworks:`, `dashscope:`, `compat:`.
- that vendor's key: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `DASHSCOPE_API_KEY`, or `COMPAT_API_KEY` (+ `LLM_COMPAT_BASE_URL`).
- optionally `LLM_<VENDOR>_BASE_URL` to move that vendor to another region.

To activate failover: `LLM_MODEL_FALLBACK=<prefix>:<model>` naming a **different company** from `LLM_MODEL`, plus that vendor's key. The example in the runbook is `LLM_MODEL_FALLBACK=openai:gpt-4.1-mini` with `OPENAI_API_KEY`. `LLM_BREAKER_FAILURES=3`, `LLM_BREAKER_WINDOW_SECS=60` and `LLM_BREAKER_COOLDOWN_SECS=300` are defaults and need not be written. Step 6a of `docs/runbooks/accounts-and-env.md` lists where each vendor's key comes from and which endpoints process transcripts outside North America.
