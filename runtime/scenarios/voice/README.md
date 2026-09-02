# Voice evals: the turn budget, measured on real audio

`scenarios/promptfooconfig.yaml` measures what the brain *says*. These measure how long the
whole voice stack takes to say it, which is the other half of the product: the brief's S7
budget is 800 ms from the caller finishing a sentence to the assistant starting one, and
`spatalk/ops/latency.py` splits that into 300 ms of STT, 450 ms of LLM and 200 ms of TTS.

The runtime's own numbers come from production calls (`UsageObserver` files each TTFB
reading under its stage, `_finalize` stores the call's p95 in `conversations.stage_ms`).
These scenarios are the pre-production version of the same measurement: synthesized caller
audio into the real pipeline, with `within_ms` on the reply.

```
uv pip install "pipecat-ai[cli]"
python scenarios/voice/eval_bot.py -t eval --port 7860 &
pipecat eval run scenarios/voice/*.yaml --audio --record-dir recordings -v
```

Both halves need provider keys: the bot needs `GOOGLE_API_KEY`, `SONIOX_API_KEY` and
`INWORLD_API_KEY` (or the Deepgram alternatives), and the harness downloads a local Kokoro
voice for the caller and a local Moonshine model to transcribe the bot. Nothing here uses a
judge model, so no scenario costs a judged token: every expectation is a substring of fixed
tenant wording or a latency budget, both of which are decidable without a model.

`.github/workflows/nightly-voice-evals.yml` runs this nightly when the keys exist as
repository secrets, and prints a `::notice` saying it did nothing when they do not. A green
tick on a job that ran no scenario is the failure this is written against.

The bot here is not the production entry point: `spatalk/voice/pipeline.py` answers a
Telnyx media stream inside FastAPI. `eval_bot.py` builds the same pipeline — the same
`make_stt`/`make_llm`/`make_tts`, the same rules gate, output guard, tools and tenant
prompt — over Pipecat's eval transport, which is the only transport the harness speaks.
