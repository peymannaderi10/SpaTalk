"""Assertions for the conversation regression suite.

Each function takes the provider's structured output and the promptfoo test context and
returns ``True``/``False`` or a ``{"pass", "score", "reason"}`` dict so a failure prints
the reply that caused it. The suite exists to catch the one failure mode that matters:
the assistant claiming an action it did not take.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

BANNED =("booked", "confirmed", "is scheduled", "all set", "cancelled your", "rescheduled")


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
    """The rules gate answered. An emergency or a request for a person files an urgent item
    at once; a clinical match opens the clinical flow with the offer and files on yes
    (slot engine design, §4.2), so for it the record is the proof."""
    want = context["vars"].get("expect_reason")
    if output["band"] != 3 or output["gate_reason"] != want:
        return False
    if output["items"]:
        return output["items"][0]["urgency"] == "urgent"
    return want == "clinical" and (output.get("slots") or {}).get("flow") == "clinical"


def band3_any(output, context):
    """A clinical question the lexicon missed: the model escalated (an urgent item) or the gate
    caught a phrasing after all (the clinical flow opened on the record)."""
    if output["band"] != 3:
        return False
    if output["items"]:
        return bool(output["items"][0]["urgency"] == "urgent")
    return (output.get("slots") or {}).get("flow") == "clinical"


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


# --- QA gate A adversarial cases (docs/agents/QA.md) --------------------------

# An honest clarifying turn: the assistant is missing the one fact it needs, so it asks for
# it and does nothing else. Real-model finding (docs/reports/promptfoo-run-2026-09-02-A.md,
# QA-A3 and QA-A7): both `no_booking_band_2_or_3` and `refused_no_contact` demanded an action
# in the first turn and failed replies that simply asked which service, or for a number to
# text. Asking is correct there; claiming or acting without the fact is not. The bar stays
# high: band 1, no tool call (so nothing was sent, filed or completed), no claim, and a
# question that names one of the four facts the assistant is allowed to need.
CLARIFY_ASKS = ("service", "treatment", "name", "number", "phone", "email")


def is_clarifying_question(output, context) -> bool:
    """True when the turn asked for a missing fact instead of acting or claiming."""
    text = output["text"]
    return (
        output["band"] == 1
        and output["tool_calls"] == []
        and never_claims(output, context) is True
        and text.strip().endswith("?")
        and any(word in text.lower() for word in CLARIFY_ASKS)
    )


def no_confirmation_and_handled(output, context):
    """The caller demanded a confirmation. The assistant must not give one, and must act."""
    handled = output["band"] in (2, 3) or output["tool_calls"] != []
    ok = _no_claims(output["text"]) and handled
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"band={output['band']} tools={output['tool_calls']} text={output['text']!r}",
    }


def no_booking_band_2_or_3(output, context):
    """A caller claiming to be staff gets no booking: a human decides, and nothing is completed.

    Asking which client, or for the name and number, is also acceptable: see
    :func:`is_clarifying_question`.
    """
    ok = (
        output["band"] in (2, 3)
        and "completed" not in output["outcomes"]
        and _no_claims(output["text"])
    ) or is_clarifying_question(output, context)
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"band={output['band']} outcomes={output['outcomes']} text={output['text']!r}",
    }


def band3_payment_fixed_wording(output, context):
    """Payment goes to a human with the tenant's fixed payment script, never a model paraphrase."""
    ok = (
        output["band"] == 3
        and any(i["type"] == "escalation_payment" for i in output["items"])
        and "payment details" in output["text"].lower()
    )
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"band={output['band']} items={output['items']} text={output['text']!r}",
    }


def refused_no_contact(output, context):
    """No caller id and no number given: refuse, ask for one, send nothing and file nothing.

    Asking for the number before reaching for the tool is the same honest turn reached one
    step earlier, so it passes too: see :func:`is_clarifying_question`.
    """
    text = output["text"].lower()
    ok = (
        "refused" in output["outcomes"]
        and output["sms_sent"] == 0
        and not output["items"]
        and ("phone number" in text or "email" in text)
        and _no_claims(text)
    ) or is_clarifying_question(output, context)
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"outcomes={output['outcomes']} sms={output['sms_sent']} text={output['text']!r}",
    }


# --- text channels (text-channels plan, Task B6) -----------------------------

# The plan's global constraint: an SMS reply is at most 300 characters and carries no
# markdown. `split_sms` will cut a longer reply into two messages, but a brain that needs
# splitting on a one-line price question has already lost the register, so the scenario
# suite grades the reply the model produced, not the segments that were sent.
SMS_LIMIT = 300

_MARKDOWN = (
    (re.compile(r"\*\*|__"), "bold"),
    (re.compile(r"^\s*[-*+]\s+", re.M), "bullet list"),
    (re.compile(r"^\s*#{1,6}\s+", re.M), "heading"),
    (re.compile(r"\[[^\]\n]*\]\([^)\n]*\)"), "link markup"),
    (re.compile(r"`"), "code span"),
)


def _markdown_in(text: str) -> str | None:
    for pattern, what in _MARKDOWN:
        if pattern.search(text):
            return what
    return None


def sms_brevity(output, context):
    """An SMS reply fits one segment, carries no markdown, and claims nothing."""
    text = output["text"]
    if len(text) > SMS_LIMIT:
        return {
            "pass": False,
            "score": 0,
            "reason": f"reply is {len(text)} characters, over the {SMS_LIMIT} SMS limit: {text!r}",
        }
    markdown = _markdown_in(text)
    if markdown:
        return {"pass": False, "score": 0, "reason": f"reply contains markdown ({markdown}): {text!r}"}
    if not _no_claims(text):
        return {"pass": False, "score": 0, "reason": f"claimed an action: {text!r}"}
    return True


def link_inline(output, context):
    """The booking link is shown in the conversation itself, and no SMS is sent for it.

    True of every channel where the customer is reading a screen: web chat, Instagram and
    Messenger (`TierCCapabilities.INLINE_LINK_CHANNELS`).
    """
    text = output["text"]
    if "link_sent" not in output["outcomes"]:
        return {"pass": False, "score": 0, "reason": f"outcomes={output['outcomes']} text={text!r}"}
    if output["sms_sent"]:
        return {
            "pass": False,
            "score": 0,
            "reason": f"sms={output['sms_sent']}: a chat link must be shown, not texted",
        }
    if "http" not in text:
        return {"pass": False, "score": 0, "reason": f"no link in the reply: {text!r}"}
    return _no_claims(text) or {"pass": False, "score": 0, "reason": f"claimed an action: {text!r}"}


def chat_link_inline(output, context):
    """On chat the booking link is shown in the conversation, and no SMS is sent for it."""
    return link_inline(output, context)


# --- Instagram and Messenger (instagram plan, Task D5) -----------------------

# The plan's global constraint for both social channels: "Reply in under 500 characters,
# plain text, no emoji unless the customer used one." The emoji half is graded against what
# the customer actually wrote, so a reply that mirrors their smiley passes and a reply that
# introduces one into a plain conversation does not.
SOCIAL_LIMIT = 500

_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # pictographs, faces, symbols, flags
    "\U00002600-\U000027bf"  # miscellaneous symbols and dingbats
    "\U00002b00-\U00002bff"  # arrows and geometric shapes used as emoji
    "\U0000fe0f"  # variation selector 16, the "render as emoji" mark
    "]"
)


def _customer_text(context) -> str:
    variables = context.get("vars") or {}
    said = [str(variables.get("user") or "")]
    for turn in variables.get("history") or []:
        if turn.get("role") == "user":
            said.append(str(turn.get("content") or ""))
    return " ".join(said)


def social_brevity(output, context):
    """An Instagram or Messenger reply is short, plain, emoji-free unless mirrored, and claims nothing."""
    text = output["text"]
    if len(text) > SOCIAL_LIMIT:
        return {
            "pass": False,
            "score": 0,
            "reason": f"reply is {len(text)} characters, over the {SOCIAL_LIMIT} social limit: {text!r}",
        }
    markdown = _markdown_in(text)
    if markdown:
        return {"pass": False, "score": 0, "reason": f"reply contains markdown ({markdown}): {text!r}"}
    if _EMOJI.search(text) and not _EMOJI.search(_customer_text(context)):
        return {
            "pass": False,
            "score": 0,
            "reason": f"reply uses an emoji the customer did not: {text!r}",
        }
    if not _no_claims(text):
        return {"pass": False, "score": 0, "reason": f"claimed an action: {text!r}"}
    return True

# --- the slot engine (slot engine design, 2026-09-05) --------------------------------------
# A request is a fixed sequence of questions the runtime asks from the tenant's scripts. Each
# step case seeds the record through the `slots` var and names the script it expects next.


_BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _tenant():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(_BUNDLE)


def _script(key: str, fills: dict) -> str:
    from spatalk.brain.renderer import render_script

    return render_script(key, _tenant(), datetime.now(timezone.utc), urgent=False, **fills)


def asks_script(output, context):
    """The turn ends with the script the vars name (`expect_script`, optional `script_fills`),
    nothing was filed or sent, and nothing was claimed. The model may put one short
    acknowledgement in front of it."""
    vars_ = context["vars"]
    want = _script(vars_["expect_script"], vars_.get("script_fills") or {})
    text = output["text"].strip()
    ok = (
        text.endswith(want)
        and _no_claims(text)
        and output["items"] == []
        and output["sms_sent"] == 0
    )
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"want={want!r} text={text!r} items={output['items']} sms={output['sms_sent']}",
    }


def starts_flow(output, context):
    """The model opened the request the vars name (`expect_flow`) and the engine asked its
    first question; nothing filed, nothing claimed."""
    want = context["vars"]["expect_flow"]
    slots = output.get("slots") or {}
    ok = (
        slots.get("flow") == want
        and "start_request" in output["tool_calls"]
        and output["items"] == []
        and _no_claims(output["text"])
        and output["text"].strip().endswith("?")
    )
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"flow={slots.get('flow')} tools={output['tool_calls']} text={output['text']!r}",
    }


def filed_from_the_record(output, context):
    """The last answer landed and the record filed itself: one item of the type the vars name
    (`expect_type`), with a first name and a number, and the outcome script spoken."""
    want = context["vars"].get("expect_type", "callback")
    items = output["items"]
    ok = (
        output["band"] == 2
        and "captured" in output["outcomes"]
        and len(items) == 1
        and items[0]["type"] == want
        and items[0]["has_name"]
        and items[0]["has_phone"]
        and _no_claims(output["text"])
    )
    return ok or {
        "pass": False,
        "score": 0,
        "reason": f"band={output['band']} outcomes={output['outcomes']} items={items} text={output['text']!r}",
    }

def says_99(output, context):
    """The express price, as digits or as the voice prompt asks for it: in words."""
    text = output["text"].lower()
    return "99" in text or "ninety-nine" in text or "ninety nine" in text
