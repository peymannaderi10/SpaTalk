"""Adversarial verification of the lead context plan (QA task V1).

Written after tasks L1 (69dd0bf) and L2 (13977db) were committed, from the diffs rather
than from the task reports. Every test here tries to break a promise the plan makes, in
the words the plan makes it:

* "Still no free text: `practitioner` and `concern` are enums from the tenant config"
  (Global Constraints).
* "Health stays out of the fields." (Global Constraints)
* "The summary is composed from fields and fixed labels only" and
  "`preferred_text(window)` ... never `"any any"`" (Task L1, Interfaces).
* "the second line becomes the summary ..., still within the three-segment rule"
  (Task L1, Interfaces).
* "Offers are the clinic's own, from the knowledge file ... it never invents a discount."
  (Global Constraints)
* "No raw ids, no `"any any"`, no field shown when empty." (Task L2, Interfaces)

Every test asserts the promise plainly, so the door stays shut. The eight gaps this file
first recorded as ``xfail(strict=True)`` were closed on 2026-09-03; each marker was deleted
with its fix, which is what ``strict=True`` was there to force. Two of the assertions moved
with their fix and say so in the test's own docstring: the preferred-window grid, because a
real date now carries the day and the month, and the SMS drop order, because the summary is
now the first line to go rather than the last.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "runtime" / "tenants" / "skincentrix"
MIGRATION = REPO / "runtime" / "alembic" / "versions" / "0011_lead_context.py"
NOW = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)  # Tue 19:30 Toronto, closed


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _links():
    from spatalk.ledger.delivery import ActionLinks

    return ActionLinks(
        "https://api.test/a/" + "a" * 24,
        "https://api.test/a/" + "b" * 24,
        "https://api.test/a/" + "c" * 24,
        "a" * 24,
        "b" * 24,
    )


def _item(**over):
    """An `items` row as the renderers read it: only the columns, never a helper."""
    row = dict(
        id=41,
        tenant_id="skincentrix",
        type="new_booking",
        urgency="normal",
        channel="voice",
        service_id="mirapeel_facial",
        contact_name="Priya Balasubramanian",
        contact_phone="+19055550142",
        contact_email=None,
        preferred_window={"date": "any", "part_of_day": "any"},
        returning_client=None,
        practitioner=None,
        concern=None,
        health_context=False,
        due_at=NOW,
    )
    row.update(over)
    return SimpleNamespace(**row)


# =============================================================================================
# 1. No free text can reach an item
# =============================================================================================


def test_the_only_unenumerated_strings_on_a_tool_are_contact_details():
    """CLAUDE.md 2 and the plan's "Still no free text", checked at the model's edge.

    A contact name, phone and email are details about a person, not notes; every other
    string a tool accepts must be a closed vocabulary, or the model has somewhere to write
    a sentence that then lives on the item.
    """
    from spatalk.brain.tools import build_tools

    free = []
    for tool in build_tools(_cfg()):
        for pname, spec in tool.properties.items():
            if spec.get("type") == "string" and "enum" not in spec:
                free.append(f"{tool.name}.{pname}")
            if spec.get("type") == "object":
                for sub, subspec in spec.get("properties", {}).items():
                    if subspec.get("type") == "string" and "enum" not in subspec:
                        free.append(f"{tool.name}.{pname}.{sub}")
    contact_details = {
        f"{tool}.contact.{field}"
        for tool in ("send_booking_link", "capture_request", "request_appointment_change")
        for field in ("name", "phone", "email")
    }
    # The two window dates cannot be an enum — an ISO date is not a list — so they are the
    # one string the schema leaves open. `PreferredWindow` closes it instead: anything but a
    # date, a weekday name or "any" becomes "any" before the ledger sees it, which is what
    # `test_free_text_in_the_preferred_window_never_reaches_the_items_table` holds shut.
    closed_downstream = {
        "capture_request.preferred_window.date",
        "request_appointment_change.preferred_window.date",
    }
    assert set(free) <= contact_details | closed_downstream, (
        f"a new free string: {sorted(set(free))}"
    )
    assert not {f for f in free if f.rsplit(".", 1)[-1] in
                ("practitioner", "concern", "returning_client", "service_id", "kind", "reason")}


def test_the_three_lead_parameters_are_a_boolean_and_two_closed_enums():
    """Task L1: "returning_client (boolean), practitioner (enum ...), concern (enum ...)"."""
    from spatalk.brain.tools import build_tools

    cfg = _cfg()
    tools = {t.name: t for t in build_tools(cfg)}
    for name in ("send_booking_link", "capture_request"):
        props = tools[name].properties
        assert props["returning_client"]["type"] == "boolean"
        assert "enum" not in props["returning_client"]
        assert props["practitioner"]["enum"] == cfg.practitioner_names()
        assert props["concern"]["enum"] == list(cfg.concerns)
        # Optional, all three: the plan says the assistant asks once and takes no for an answer.
        assert not set(tools[name].required) & {"returning_client", "practitioner", "concern"}


def test_no_other_tool_gained_a_parameter():
    """Task L1: "No other new parameters." A change tool is not a qualification moment."""
    from spatalk.brain.tools import build_tools

    tools = {t.name: sorted(t.properties) for t in build_tools(_cfg())}
    assert tools["request_appointment_change"] == ["contact", "kind", "preferred_window"]
    assert tools["escalate"] == ["reason"]
    assert tools["end_conversation"] == []
    assert not any("note" in p for props in tools.values() for p in props)


async def test_an_invented_practitioner_or_concern_never_reaches_the_column(
    sf, registry, fixed_clock
):
    """Task L1: "an unknown name becomes `None` and is logged".

    Six values a model plausibly returns instead of the enum, including the caller's own
    words and a health phrase. None of them may be stored.
    """
    from sqlalchemy import select

    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger
    from spatalk.models import Item

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice")
    invented = [
        ("Dr Nobody", "wants a discount"),
        ("sabah shaikh", "Acne"),                       # right person, wrong case
        ("Sabah", "acne scarring"),                     # first name only
        ("the nurse who did my filler", "my rash"),     # the caller's own words
        ("ANY", "pregnancy safe treatments"),           # "any" is case-sensitive too
        ("", " "),
    ]
    for who, what in invented:
        await ledger.create_item(
            ref, ItemDraft(type="callback", urgency="normal", practitioner=who, concern=what)
        )
    async with sf() as s:
        rows = (await s.execute(select(Item))).scalars().all()
    assert len(rows) == len(invented)
    assert {r.practitioner for r in rows} == {None}
    assert {r.concern for r in rows} == {None}


async def test_the_ledger_is_the_only_place_an_item_row_is_built(sf, registry, fixed_clock):
    """The closed-vocabulary check is worth nothing if a second writer skips it."""
    sources = list((REPO / "runtime" / "spatalk").rglob("*.py"))
    writers = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Item":
                writers.append(str(path.relative_to(REPO)).replace("\\", "/"))
    assert writers == ["runtime/spatalk/ledger/items.py"]


async def test_free_text_in_the_preferred_window_never_reaches_the_items_table(
    sf, registry, fixed_clock
):
    from sqlalchemy import select

    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ConversationRef, PreferredWindow
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger
    from spatalk.models import Item

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice")
    await ledger.create_item(
        ref,
        ItemDraft(
            type="new_booking",
            urgency="normal",
            preferred_window=PreferredWindow(
                date="whenever the burn on my arm from the laser settles down"
            ),
        ),
    )
    async with sf() as s:
        row = (await s.execute(select(Item))).scalars().one()
    assert row.preferred_window["date"] in ("any", "") or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", row.preferred_window["date"]
    ), f"free text stored on the item: {row.preferred_window!r}"


def test_a_rejected_value_is_not_echoed_into_the_service_log():
    from loguru import logger

    from spatalk.ledger.items import concern_for, practitioner_for

    cfg = _cfg()
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="WARNING")
    try:
        assert practitioner_for(cfg, "the nurse who did my botox, I had a reaction") is None
        assert concern_for(cfg, "my rash keeps coming back and I am 20 weeks pregnant") is None
    finally:
        logger.remove(sink)
    logged = " ".join(seen).lower()
    assert "skincentrix" in logged, "the tenant and the field are the useful part of the log"
    for word in ("botox", "reaction", "rash", "pregnant", "nurse"):
        assert word not in logged, f"the log echoes the caller's word {word!r}"


# =============================================================================================
# 2. The summary says nothing it does not know
# =============================================================================================


def test_the_summary_never_says_none_or_any_any_or_shows_a_seam():
    """Task L1: composed "from closed fields and fixed labels only"; never `"any any"`.

    Every combination of the columns the sentence reads, including the shapes a legacy row
    and a mangled tool call produce (a null window, an empty string, an unparseable date).
    """
    from spatalk.ledger.summary import TYPE_LABELS, summarize_item

    cfg = _cfg()
    windows = [
        None,
        {},
        {"date": "any", "part_of_day": "any"},
        {"date": None, "part_of_day": None},
        {"date": "", "part_of_day": ""},
        {"date": "2026-09-24", "part_of_day": "afternoon"},
        {"date": "2026-09-24", "part_of_day": "any"},
        {"date": "any", "part_of_day": "morning"},
        {"date": "next Thursday", "part_of_day": "any"},
    ]
    checked = 0
    for item_type, service_id, who, what, returning, window in product(
        list(TYPE_LABELS),
        [None, "", "a_service_the_catalog_dropped", "mirapeel_facial", "laser_hair_removal"],
        [None, "", "any", "Sabah Shaikh"],
        [None, "", "acne", "hair removal"],
        [None, True, False],
        windows,
    ):
        out = summarize_item(
            _item(
                type=item_type,
                service_id=service_id,
                practitioner=who,
                concern=what,
                returning_client=returning,
                preferred_window=window,
            ),
            cfg,
        )
        checked += 1
        assert "None" not in out
        assert "any any" not in out
        assert "  " not in out and " ." not in out and ".." not in out
        assert out.endswith(".") and not out.startswith((".", ",", " "))
        # A raw id or a raw type is snake_case; a label, a service name and a concern are words.
        assert "_" not in out, f"raw id leaked: {out!r}"
    assert checked > 10_000


def test_every_item_type_the_runtime_can_create_has_a_label():
    """The one door through which a raw id could still reach the summary.

    `type_label` falls back to the raw `item.type`, so a type with no label prints
    `escalation_whatever` to the owner. Every type the code constructs must be labelled.
    """
    from spatalk.brain.requests import CaptureKind, ChangeKind, EscalateReason
    from spatalk.ledger.summary import TYPE_LABELS
    from typing import get_args

    produced = (
        set(get_args(CaptureKind))
        | set(get_args(ChangeKind))
        | {f"escalation_{r}" for r in get_args(EscalateReason)}
        | {"send_link"}
    )
    assert produced <= set(TYPE_LABELS), f"unlabelled: {sorted(produced - set(TYPE_LABELS))}"


def test_the_summary_never_names_a_service_by_its_id():
    """Task L2: "Service (by name)... No raw ids"; the sentence is the card's title."""
    from spatalk.ledger.summary import summarize_item

    cfg = _cfg()
    for service in cfg.services:
        out = summarize_item(_item(service_id=service.id), cfg)
        assert service.name in out
        assert service.id not in out


def test_the_summary_is_derived_and_never_stored():
    """data-model.md: "derived, never stored ... so it cannot drift from the fields"."""
    from spatalk.models import Item

    columns = set(Item.__table__.columns.keys())
    assert not columns & {"summary", "service_name", "preferred_text"}
    assert {"returning_client", "practitioner", "concern"} <= columns


def test_the_summary_never_reaches_the_caller():
    """CLAUDE.md 1: what a caller hears comes from `scripts`, never from a composed sentence.

    Structural, not behavioural: nothing under `spatalk/brain` may import the summary
    module, so no renderer, guard or tool result can start speaking it.
    """
    brain = REPO / "runtime" / "spatalk" / "brain"
    for path in brain.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ledger.summary" not in source, f"{path.name} imports the staff summary"


async def test_the_spoken_outcome_says_nothing_about_the_lead_fields(fixed_clock):
    """The caller is told what was filed, never what the assistant wrote down about them."""
    from spatalk.brain.driver import dispatch_tool
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities

    caps = TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid4(), tenant=_cfg(), channel="voice", caller_phone="+19055550101"
    )
    _outcome, spoken, _ended = await dispatch_tool(
        caps,
        ref,
        "capture_request",
        {
            "kind": "new_booking",
            "service_id": "mirapeel_facial",
            "contact": {"name": "Dana", "phone": "+19055550101"},
            "returning_client": False,
            "practitioner": "Sabah Shaikh",
            "concern": "pigmentation",
        },
        fixed_clock.now(),
    )
    low = spoken.lower()
    for leaked in ("sabah", "pigmentation", "new client", "returning"):
        assert leaked not in low, f"the caller was told {leaked!r}"


def test_preferred_text_over_the_whole_grid_of_windows():
    """Task L1's table, plus the shapes it does not list: null, empty, and a mangled date.

    Updated with the fix for this file's own finding: Task L1's table mapped an ISO date to
    a bare weekday, which loses the day the caller named. A real date now renders as the
    weekday, the day and the month; a weekday the caller named without a date still renders
    as the plan's bare weekday, because that is all it is.
    """
    from spatalk.ledger.summary import preferred_text

    assert preferred_text(None) == "any day"
    assert preferred_text({}) == "any day"
    assert preferred_text({"date": "any", "part_of_day": "any"}) == "any day"
    assert preferred_text({"date": "2026-09-24", "part_of_day": "any"}) == "Thursday 24 September"
    assert preferred_text({"date": "2026-09-24", "part_of_day": "afternoon"}) == (
        "Thursday 24 September, afternoons"
    )
    assert preferred_text({"date": "Thursday", "part_of_day": "any"}) == "Thursday"
    assert preferred_text({"date": "Thursday", "part_of_day": "afternoon"}) == "Thursday afternoon"
    assert preferred_text({"date": "any", "part_of_day": "morning"}) == "mornings"
    assert preferred_text({"date": "not a date", "part_of_day": "any"}) == "any day"
    assert preferred_text({"date": None, "part_of_day": None}) == "any day"
    for date_ in (None, "", "any", "2026-09-24", "Thursday", "tomorrow-ish", "0000-00-00"):
        for part in (None, "", "any", "morning", "afternoon", "evening"):
            out = preferred_text({"date": date_, "part_of_day": part})
            assert "any any" not in out and "None" not in out and out.strip() == out
            assert out


def test_a_date_the_caller_named_survives_to_the_staff_email():
    from spatalk.ledger.delivery import build_email

    item = _item(preferred_window={"date": "2026-09-24", "part_of_day": "afternoon"})
    _subject, body = build_email(item, _cfg(), _links(), NOW)
    assert "2026-09-24" in body or "24 September" in body or "September 24" in body


# =============================================================================================
# 3. Health stays out of the fields, and out of everything a staff member is shown
# =============================================================================================


def test_the_default_concerns_share_no_word_with_the_clinical_or_health_lexicons():
    """Global Constraints: "`concern` is a cosmetic taxonomy ... Health stays out of the fields"."""
    from spatalk.brain.rules import DEFAULT_LEXICONS, HEALTH_CONTEXT_DEFAULT
    from spatalk.tenants.schema import DEFAULT_CONCERNS

    medical = {w.lower() for w in DEFAULT_LEXICONS["clinical"] + HEALTH_CONTEXT_DEFAULT}
    for concern in DEFAULT_CONCERNS:
        assert concern.lower() not in medical
        # and no single word of a concern is a lexicon term either ("hair loss" vs "loss").
        for word in concern.lower().split():
            assert word not in medical, f"concern {concern!r} shares {word!r} with the lexicon"


def test_the_bundle_ships_the_cosmetic_taxonomy_and_no_medical_word():
    from spatalk.brain.rules import DEFAULT_LEXICONS, HEALTH_CONTEXT_DEFAULT

    cfg = _cfg()
    medical = {w.lower() for w in DEFAULT_LEXICONS["clinical"] + HEALTH_CONTEXT_DEFAULT}
    assert set(cfg.concerns) and not {c.lower() for c in cfg.concerns} & medical
    assert not {m.name.lower() for m in cfg.team} & medical


async def test_a_health_word_never_lands_in_a_lead_column(sf, registry, fixed_clock):
    """Every clinical and health-context term, offered to the ledger as a lead value."""
    from sqlalchemy import select

    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.rules import DEFAULT_LEXICONS, HEALTH_CONTEXT_DEFAULT
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger
    from spatalk.models import Item

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice")
    words = DEFAULT_LEXICONS["clinical"] + HEALTH_CONTEXT_DEFAULT
    for word in words:
        await ledger.create_item(
            ref,
            ItemDraft(
                type="new_booking", urgency="normal", practitioner=word, concern=word,
                health_context=True,
            ),
        )
    async with sf() as s:
        rows = (await s.execute(select(Item))).scalars().all()
    assert len(rows) == len(words)
    assert all(r.practitioner is None and r.concern is None for r in rows)
    assert all(r.health_context is True for r in rows), "the flag is how staff learn to read"


def test_the_summary_of_a_flagged_item_says_nothing_about_health():
    """CLAUDE.md 2: the flag travels, the detail does not. The sentence must not name it."""
    from spatalk.ledger.summary import summarize_item

    out = summarize_item(_item(health_context=True, concern="acne", returning_client=False), _cfg())
    for word in ("health", "condition", "pregnan", "medication", "transcript"):
        assert word not in out.lower()


def test_a_tenant_cannot_configure_a_medical_concern():
    from pydantic import ValidationError

    from spatalk.tenants.schema import TenantConfig

    raw = _cfg().model_dump()
    raw["concerns"] = ["pigmentation", "rosacea", "pregnancy"]
    with pytest.raises(ValidationError):
        TenantConfig.model_validate(raw)


def test_the_config_cannot_hold_a_value_wider_than_its_column():
    from pydantic import ValidationError

    from spatalk.tenants.schema import TenantConfig

    raw = _cfg().model_dump()
    raw["team"] = [{"name": "N" * 200, "role": ""}]
    raw["concerns"] = ["c" * 100]
    with pytest.raises(ValidationError):
        TenantConfig.model_validate(raw)


# =============================================================================================
# 4. The owner's text still fits, and still carries what the owner needs
# =============================================================================================


def test_the_staff_sms_holds_three_segments_however_long_the_lead_is(fixed_clock):
    """Task L1: "still within the three-segment rule". 459 GSM-7 characters, or 201 in UCS-2."""
    from spatalk.ledger.delivery import SMS_STAFF_SEGMENTS, build_sms_text, sms_segments

    cfg = _cfg()
    links = _links()
    longest_service = max(cfg.services, key=lambda s: len(s.name)).id
    longest_person = max(cfg.practitioner_names(), key=len)
    longest_concern = max(cfg.concerns, key=len)
    cases = [
        _item(),
        _item(type="escalation_clinical", urgency="urgent", health_context=True),
        _item(
            service_id=longest_service,
            practitioner=longest_person,
            concern=longest_concern,
            returning_client=False,
            health_context=True,
            urgency="urgent",
            id=9999999,
            contact_name="Bartholomew Fitzgerald-Wintersmith the Third",
            contact_email="bartholomew.fitzgerald.wintersmith@averylongdomainname.example.com",
            preferred_window={"date": "2026-09-24", "part_of_day": "afternoon"},
        ),
        # A name outside GSM-7 turns the whole body into UCS-2: three segments hold 201.
        _item(
            service_id=longest_service,
            practitioner=longest_person,
            concern=longest_concern,
            returning_client=True,
            health_context=True,
            contact_name="張偉廉 王小雲",
            contact_email="a.very.long.email.address@an-even-longer-domain.example.com",
        ),
    ]
    for item in cases:
        for escalation in (False, True):
            text = build_sms_text(item, cfg, links, fixed_clock.now(), escalation=escalation)
            assert sms_segments(text) <= SMS_STAFF_SEGMENTS, text
            assert text.endswith(links.transcript_url), "the link survives every cut"
            assert "None" not in text and "any any" not in text


def test_the_owner_text_of_an_ordinary_lead_carries_the_whole_story(fixed_clock):
    """The point of the plan: the owner can call the lead back from the text alone."""
    from spatalk.ledger.delivery import build_sms_text

    item = _item(
        returning_client=False,
        practitioner="Mariam Khaizaran",
        concern="body contouring",
        preferred_window={"date": "any", "part_of_day": "afternoon"},
    )
    text = build_sms_text(item, _cfg(), _links(), fixed_clock.now())
    assert item.contact_phone in text
    assert "New booking:" in text and "body contouring" in text
    assert "New client" in text and "Mariam Khaizaran" in text
    assert "Callback afternoons" in text


def test_the_summary_never_outranks_the_health_line_or_the_callers_number(fixed_clock):
    """The drop order is summary, then health line, then who line (fixed 2026-09-03).

    Every word of the summary is on the portal card and in the transcript; the health line
    tells the owner how to read the call before they make it, and the who line is the number
    they call. So the sentence is the first thing to go, not the last.
    """
    from spatalk.ledger.delivery import SMS_HEALTH_LINE, build_sms_text

    item = _item(
        contact_email="priya.balasubramanian@gmail.com",
        returning_client=False,
        practitioner="Mariam Khaizaran",
        concern="body contouring",
        health_context=True,
        preferred_window={"date": "2026-09-24", "part_of_day": "afternoon"},
    )
    text = build_sms_text(item, _cfg(), _links(), fixed_clock.now(), escalation=True)
    assert SMS_HEALTH_LINE in text, "the health warning was dropped to make room for the summary"
    assert item.contact_phone in text


def test_the_email_slack_and_digest_all_show_the_one_sentence(fixed_clock):
    """Task L1: one sentence, composed once, so the channels cannot drift apart."""
    from spatalk.ledger.delivery import build_email, build_slack_blocks
    from spatalk.ledger.summary import summarize_item

    cfg, links = _cfg(), _links()
    item = _item(returning_client=True, practitioner="any", concern="acne")
    sentence = summarize_item(item, cfg)
    _subject, body = build_email(item, cfg, links, fixed_clock.now())
    blocks = json.dumps(build_slack_blocks(item, cfg, links, fixed_clock.now()))
    assert body.startswith(sentence)
    assert sentence in blocks
    assert "no practitioner preference" in sentence and "Returning client" in sentence


# =============================================================================================
# 5. The prompt asks once, and offers only what the clinic actually has
# =============================================================================================


def test_the_prompt_asks_each_question_once_and_takes_no_for_an_answer():
    """Global Constraints: "The assistant asks once and takes no for an answer"."""
    from spatalk.brain.prompt import build_system_prompt

    for channel in ("voice", "sms", "chat", "instagram"):
        p = build_system_prompt(_cfg(), channel, NOW).lower()
        assert "ask each of these once and take no for an answer" in p
        assert "never guess one" in p
        assert "any is a fine answer" in p


def test_the_prompt_contains_no_script_and_no_offer_wording():
    """CLAUDE.md 3: fixed wording is config. The instructions must name no price or offer."""
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    instructions = build_system_prompt(cfg, "voice", NOW).split("HOURS:")[0]
    for wording in ("$", "credit", "consultation", "discount", "free "):
        assert wording not in instructions.lower(), f"offer wording {wording!r} is in code"
    assert "$50 credit" in cfg.knowledge


def test_a_tenant_with_no_offers_is_not_told_to_mention_one():
    from spatalk.brain.prompt import build_system_prompt

    bare = _cfg().model_copy(update={"knowledge": "Skincentrix is a medspa in Mississauga."})
    instructions = build_system_prompt(bare, "voice", NOW).split("HOURS:")[0].lower()
    offers = [s for s in re.split(r"(?<=[.:])\s+", instructions) if "new-client offers" in s]
    if not offers:
        return  # nothing tells the model to mention an offer: the honest shape
    clause = " ".join(offers)
    assert any(
        guard in clause
        for guard in ("if the facts", "if there are", "if any are", "when the facts")
    ), f"unconditional offer instruction: {clause!r}"


def test_the_concern_parameter_does_not_invite_the_callers_own_words():
    from spatalk.brain.tools import build_tools

    spec = {t.name: t for t in build_tools(_cfg())}["capture_request"].properties["concern"]
    description = spec["description"].lower()
    assert "own terms" not in description
    assert "closest" in description or "from the list" in description or "one of" in description


# =============================================================================================
# 6. The migration, and the contract the portal is generated from
# =============================================================================================


def test_migration_0011_adds_and_drops_exactly_the_three_columns():
    """Reviewer brief: a migration must not drop or rename anything it did not add."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert set(functions) == {"upgrade", "downgrade"}

    def calls(fn, name):
        return [
            n
            for n in ast.walk(functions[fn])
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == name
        ]

    assert len(calls("upgrade", "add_column")) == 3
    assert not calls("upgrade", "drop_column")
    dropped = [c.args[1].value for c in calls("downgrade", "drop_column")]
    assert sorted(dropped) == ["concern", "practitioner", "returning_client"]
    assert not calls("downgrade", "add_column")
    assert all(c.args[0].value == "items" for c in calls("upgrade", "add_column"))
    assert all(c.args[0].value == "items" for c in calls("downgrade", "drop_column"))

    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "0011"' in source and 'down_revision' in source and '"0010"' in source
    assert source.count('schema="runtime"') == 6


def test_the_migration_widths_are_the_widths_the_models_declare():
    from spatalk.models import Item

    source = MIGRATION.read_text(encoding="utf-8")
    assert "sa.String(length=80)" in source and "sa.String(length=40)" in source
    assert Item.__table__.c.practitioner.type.length == 80
    assert Item.__table__.c.concern.type.length == 40
    assert Item.__table__.c.returning_client.nullable is True
    assert Item.__table__.c.practitioner.nullable is True
    assert Item.__table__.c.concern.nullable is True


def test_the_committed_contract_carries_the_derived_wording_as_required_fields():
    """Task L1: "Regenerate docs/contracts/runtime-internal.openapi.json"."""
    contract = json.loads(
        (REPO / "docs" / "contracts" / "runtime-internal.openapi.json").read_text(encoding="utf-8")
    )
    item = contract["components"]["schemas"]["ItemOut"]
    for field in ("summary", "service_name", "preferred_text", "returning_client",
                  "practitioner", "concern"):
        assert field in item["properties"], field
        assert field in item["required"], f"{field} must not be optional for the portal"
    assert item["properties"]["summary"]["type"] == "string"
    assert item["properties"]["preferred_text"]["type"] == "string"


def test_the_contract_matches_the_running_models():
    """A stale contract is a portal that renders a field the runtime no longer sends."""
    from spatalk.http.internal import openapi_document

    live = openapi_document(internal_only=True)["components"]["schemas"]["ItemOut"]
    committed = json.loads(
        (REPO / "docs" / "contracts" / "runtime-internal.openapi.json").read_text(encoding="utf-8")
    )["components"]["schemas"]["ItemOut"]
    assert live == committed


async def test_the_internal_api_serves_the_sentence_and_never_a_service_id(
    sf, registry, fixed_clock
):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef, PreferredWindow
    from spatalk.conversations import start_conversation
    from spatalk.http.internal import item_out
    from spatalk.ledger.items import PgLedger

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice")
    rec = await ledger.create_item(
        ref,
        ItemDraft(
            type="new_booking",
            urgency="normal",
            service_id="mirapeel_facial",
            contact=ContactInfo(name="Dana", phone="+19055550101"),
            preferred_window=PreferredWindow(date="any", part_of_day="afternoon"),
            returning_client=False,
            practitioner="any",
            concern="pigmentation",
        ),
    )
    out = item_out(await ledger.get(rec.id), cfg)
    assert out.summary.startswith("New booking: ")
    assert out.service_name == cfg.service("mirapeel_facial").name
    assert out.preferred_text == "afternoons"
    assert out.service_id not in out.summary
    assert (out.returning_client, out.practitioner, out.concern) == (False, "any", "pigmentation")

    # A service the catalog has since dropped leaves no Service row on the card, and no id.
    orphan = await ledger.create_item(
        ref, ItemDraft(type="callback", urgency="normal", service_id="deleted_service")
    )
    dropped = item_out(await ledger.get(orphan.id), cfg)
    assert dropped.service_name is None
    assert "deleted_service" not in dropped.summary


# =============================================================================================
# 7. The portal card (Task L2), read from its sources the way gate B reads the client
# =============================================================================================


def test_the_portal_labels_speak_the_runtime_vocabulary():
    """Task L2: `clientLabel` and `practitionerLabel`, with "any" read as "No preference"."""
    source = (REPO / "portal" / "src" / "client" / "formatting.ts").read_text(encoding="utf-8")
    assert "export function clientLabel(" in source
    assert "export function practitionerLabel(" in source
    assert '"Returning client"' in source and '"New client"' in source
    assert '"No preference"' in source
    tests = (REPO / "portal" / "src" / "client" / "formatting.test.ts").read_text(encoding="utf-8")
    for case in ('clientLabel(null)', 'practitionerLabel("any")', 'practitionerLabel(null)'):
        assert case in tests, f"the null case for {case} is untested"


def test_the_request_card_shows_words_and_never_a_raw_service_id():
    """Task L2: "Service (by name) ... No raw ids, no "any any", no field shown when empty"."""
    card = (REPO / "portal" / "src" / "client" / "RequestsPage.tsx").read_text(encoding="utf-8")
    assert "service_id" not in card
    assert "item.summary" in card and "item.preferred_text" in card
    assert "clientLabel(item.returning_client)" in card
    assert "practitionerLabel(item.practitioner)" in card
    assert "item.concern" in card
    # Every optional fact is guarded, so an unasked question renders nothing at all.
    for guarded in ("clientLabel(item.returning_client) &&", "practitionerLabel(item.practitioner) &&",
                    "item.concern &&"):
        assert guarded in card, f"unguarded fact: {guarded}"


def test_the_generated_portal_client_declares_the_six_new_fields():
    client = (REPO / "portal" / "src" / "runtime" / "client.ts").read_text(encoding="utf-8")
    block = client.split("ItemOut: {", 1)[1].split("\n        };", 1)[0]
    assert "summary: string;" in block
    assert "service_name: string | null;" in block
    assert "preferred_text: string;" in block
    assert "returning_client: boolean | null;" in block
    assert "practitioner: string | null;" in block
    assert "concern: string | null;" in block
