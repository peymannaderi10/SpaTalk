"""Provider rates and the cost estimate the portal shows (portal plan, Task C3).

`spatalk/rates.json` is a copy of `docs/research/rates.json`, taken so a deployed runtime
carries its own prices instead of reading a document that only exists in the repository.
Refresh it with `make sync-rates`; `tests/test_internal_api.py` fails if the two drift.

No vendor is named here. The stack priced is whichever entry in the rates table carries
`recommended: true`, so swapping providers is a change to the table, not to this module.
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
    "tts_chars",
    "llm_input_tokens",
    "llm_cached_tokens",
    "llm_output_tokens",
    "sms_in",
    "sms_out",
)


@lru_cache
def load_rates(path: str | None = None) -> dict:
    """The rates table shipped with the package (or another file, for tests)."""
    return json.loads(Path(path or RATES_PATH).read_text(encoding="utf-8"))


def recommended_stack(stacks: Mapping[str, dict]) -> dict:
    for stack in stacks.values():
        if stack.get("recommended"):
            return stack
    raise KeyError("no stack in the rates table is marked recommended")


def estimate_cad(usage: Mapping[str, float], rates: dict | None = None) -> float:
    """Estimated Canadian dollars for a bag of usage quantities.

    `usage` is a mapping of unit name to quantity; unknown and missing keys count as zero.
    Telephony is taken from `telephony_seconds` when present and from `call_minutes`
    otherwise. This is an estimate for the portal to show, never an invoice: the recorded
    provider invoices in the operations plan are the money.
    """
    r = rates or load_rates()
    voice = recommended_stack(r["voice_stacks"])
    text = recommended_stack(r["text_stacks"])
    tel = r["telephony"][voice["tel"]]
    stt = r["stt"][voice["stt"]]
    tts = r["tts"][voice["tts"]]
    llm = r["llm"][voice["llm"]]
    sms = r["sms"][text["sms"]]

    def q(key: str) -> float:
        try:
            return float(usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    minutes = q("telephony_seconds") / 60 if usage.get("telephony_seconds") else q("call_minutes")
    usd = minutes * (
        tel["inbound_per_min"] + tel.get("stream_per_min", 0) + tel.get("record_per_min", 0)
    )
    usd += q("stt_seconds") / 60 * stt["per_min"]
    usd += q("tts_chars") / 1_000_000 * tts["per_1m_chars"]
    usd += q("llm_input_tokens") / 1_000_000 * llm["in"]
    usd += q("llm_cached_tokens") / 1_000_000 * llm["cached_in"]
    usd += q("llm_output_tokens") / 1_000_000 * llm["out"]
    usd += q("sms_in") * (sms["in_per_msg"] + sms.get("carrier_in_per_msg", 0))
    usd += q("sms_out") * (sms["out_per_msg"] + sms.get("carrier_out_per_msg", 0))
    return round(usd * float(r["usd_to_cad"]), 4)
