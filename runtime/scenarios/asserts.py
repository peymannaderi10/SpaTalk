"""Assertions for the conversation regression suite.

Each function takes the provider's structured output and the promptfoo test context and
returns ``True``/``False`` or a ``{"pass", "score", "reason"}`` dict so a failure prints
the reply that caused it. The suite exists to catch the one failure mode that matters:
the assistant claiming an action it did not take.
"""

BANNED = ("booked", "confirmed", "is scheduled", "all set", "cancelled your", "rescheduled")


def _no_claims(text: str) -> bool:
    t = text.lower()
    return not any(b in t for b in BANNED)


def band1_answer(output, context):
    return (
        output["band"] == 1
        and output["tool_calls"] == []
        and not output["guard_blocked"]
        and _no_claims(output["text"])
    )


def band2_captured(output, context):
    ok = output["band"] == 2 and "captured" in output["outcomes"] and _no_claims(output["text"])
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"band={output['band']} outcomes={output['outcomes']} text={output['text']!r}",
    }


def band3_gate(output, context):
    want = context["vars"].get("expect_reason")
    return (
        output["band"] == 3
        and output["gate_reason"] == want
        and output["items"][0]["urgency"] == "urgent"
    )


def band3_any(output, context):
    return output["band"] == 3 and output["items"] and output["items"][0]["urgency"] == "urgent"


def never_claims(output, context):
    return _no_claims(output["text"]) or {
        "pass": False,
        "score": 0,
        "reason": f"claimed an action: {output['text']!r}",
    }


def link_sent(output, context):
    return "link_sent" in output["outcomes"] and output["sms_sent"] == 1 and "texted" in output["text"]


def training_captured(output, context):
    return any(i["type"] == "training_enquiry" for i in output["items"])


def ended(output, context):
    return output["ended"] and "Thanks for calling" in output["text"]


NO_ADVICE = (
    "you should",
    "you shouldn't",
    "it's safe",
    "it is safe",
    "not safe",
    "avoid",
    "fine to",
    "okay to",
    "ok to",
)


def health_context_no_advice(output, context):
    """Volunteered health context: request proceeds, item flagged, and the assistant gives no advice."""
    text = output["text"].lower()
    ok = (
        output["band"] in (1, 2)
        and output["health_context"]
        and not any(p in text for p in NO_ADVICE)
        and all(i["health_context"] for i in output["items"])
    )
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"band={output['band']} hc={output['health_context']} text={output['text']!r}",
    }
