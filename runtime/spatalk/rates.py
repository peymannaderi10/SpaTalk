"""Provider rates and the cost estimate the portal shows (portal plan, Task C3).

`spatalk/rates.json` is a copy of `docs/research/rates.json`, taken so a deployed runtime
carries its own prices instead of reading a document that only exists in the repository.
Refresh it with `make sync-rates`; `tests/test_internal_api.py` fails if the two drift.

No vendor is named here. The stack priced is `live_stack` in the rates table — the one the
quote builder prices and the one the calls actually run on — so swapping providers is a
change to the table, not to this module. The candidate stacks above it in the table are the
September 1 research and are priced by `docs/research/costmodel.py`, not by this module:
pricing the research row here made the portal's overview card and the quote page disagree
about the same month (cost gap C1).

Two arithmetic rules, each with an obvious wrong alternative:

* **Cached input tokens are billed once.** Both providers' usage metadata report the cached
  count *inside* the input count (`prompt_token_count` includes `cached_content_token_count`;
  OpenAI's `prompt_tokens` includes `cached_tokens`), so the full-rate half of an input
  count is the difference. Billing the whole input at the full rate and the cached count
  again at the cached rate charged the cheap tokens twice.
* **Every priced unit lands in exactly one component**, so a per-component report adds up to
  the estimate and nothing quietly falls out of it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Mapping

RATES_PATH = Path(__file__).with_name("rates.json")

# The usage units this module knows how to price. `spatalk.models.UsageEvent.unit` may
# carry more (chat and social message counts); those cost nothing beyond their LLM tokens.
PRICED_UNITS: tuple[str, ...] = (
    "telephony_seconds",
    "call_minutes",
    "stt_seconds",
    "tts_seconds",
    "tts_chars",
    "llm_input_tokens",
    "llm_cached_tokens",
    "llm_output_tokens",
    "sms_in",
    "sms_out",
)

# The cost lines a call is read in. The three LLM lines stay apart because the whole cost
# question is how much of the input is cached (cost gap C1).
COMPONENTS: tuple[str, ...] = (
    "telephony",
    "stt",
    "tts",
    "llm_input",
    "llm_cached",
    "llm_output",
    "sms",
)


@lru_cache
def load_rates(path: str | None = None) -> dict:
    """The rates table shipped with the package (or another file, for tests)."""
    return json.loads(Path(path or RATES_PATH).read_text(encoding="utf-8"))


def recommended_stack(stacks: Mapping[str, dict]) -> dict:
    """The September 1 research's pick among a set of candidate stacks.

    Kept for the research model and for tests that compare the candidates; the money the
    portal shows is priced on `live_stack`.
    """
    for stack in stacks.values():
        if stack.get("recommended"):
            return stack
    raise KeyError("no stack in the rates table is marked recommended")


def live_stack(rates: Mapping[str, dict] | None = None) -> dict:
    """The stack the calls run on and the quote prices: telephony, stt, tts, llm, sms."""
    r = rates if rates is not None else load_rates()
    return r["live_stack"]


def components_cad(usage: Mapping[str, float], rates: dict | None = None) -> dict[str, float]:
    """Estimated Canadian dollars per cost line for a bag of usage quantities.

    `usage` is a mapping of unit name to quantity; unknown and missing keys count as zero.
    Telephony is taken from `telephony_seconds` when present and from `call_minutes`
    otherwise. This is an estimate for the portal to show, never an invoice: the recorded
    provider invoices in the operations plan are the money.
    """
    r = rates or load_rates()
    live = live_stack(r)
    tel = r["telephony"][live["tel"]]
    stt = r["stt"][live["stt"]]
    tts = r["tts"][live["tts"]]
    llm = r["llm"][live["llm"]]
    sms = r["sms"][live["sms"]]
    fx = float(r["usd_to_cad"])

    def q(key: str) -> float:
        try:
            return float(usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    minutes = q("telephony_seconds") / 60 if usage.get("telephony_seconds") else q("call_minutes")
    # Speech is priced by the hour the vendor generates. `tts_seconds` is the exact unit and
    # `tts_chars` the older proxy, which over-states an utterance a caller talked over: the
    # runtime cancels the stream on an interruption, so the audio that was never generated
    # was never billed. Seconds win when the call recorded them and the row carries the rate.
    spoken_min = tts.get("per_spoken_min")
    if usage.get("tts_seconds") and spoken_min is not None:
        tts_usd = q("tts_seconds") / 60 * spoken_min
    else:
        tts_usd = q("tts_chars") / 1_000_000 * tts["per_1m_chars"]
    cached = q("llm_cached_tokens")
    # The input count already holds the cached count; the difference is what is billed full.
    uncached = max(q("llm_input_tokens") - cached, 0.0)
    split = {
        "telephony": minutes
        * (tel["inbound_per_min"] + tel.get("stream_per_min", 0) + tel.get("record_per_min", 0)),
        "stt": q("stt_seconds") / 60 * stt["per_min"],
        "tts": tts_usd,
        "llm_input": uncached / 1_000_000 * llm["in"],
        "llm_cached": cached / 1_000_000 * llm["cached_in"],
        "llm_output": q("llm_output_tokens") / 1_000_000 * llm["out"],
        "sms": q("sms_in") * (sms["in_per_msg"] + sms.get("carrier_in_per_msg", 0))
        + q("sms_out") * (sms["out_per_msg"] + sms.get("carrier_out_per_msg", 0)),
    }
    return {name: round(usd * fx, 6) for name, usd in split.items()}


def estimate_cad(usage: Mapping[str, float], rates: dict | None = None) -> float:
    """Estimated Canadian dollars for a bag of usage quantities, on the live stack."""
    return round(sum(components_cad(usage, rates).values()), 4)
