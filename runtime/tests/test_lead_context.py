"""Lead context: the three closed fields, the one-line summary and the qualification step.

Founder decision 2026-09-03, after the first live demo calls: a request that says only
"Wants to book" is not a lead. A request must say whether the caller is new, what they want
or the concern behind it, whether they asked for a practitioner, and when they would like to
be called back. Every one of those is a closed value drawn from the tenant config, so the
"no free text on tracked items" rule (CLAUDE.md non-negotiable 2) still holds with nine
fields instead of six.

Nothing here calls a provider or a model: the summary is deterministic string composition
over columns and fixed labels, which is the whole point of it living in the runtime.
"""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
DEFAULT_CONCERNS = [
    "pigmentation",
    "acne",
    "ageing",
    "dryness",
    "hair removal",
    "hair loss",
    "body contouring",
    "skin tightening",
    "tattoo removal",
    "glow",
    "other",
]


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _item(**over):
    """An `items` row as the delivery and summary code sees it: attributes, no session."""
    base = dict(
        id=7,
        tenant_id="skincentrix",
        conversation_id=None,
        type="new_booking",
        urgency="normal",
        service_id="mirapeel_facial",
        contact_name="Dana",
        contact_phone="+19055550101",
        contact_email=None,
        preferred_window={"date": "any", "part_of_day": "any"},
        channel="voice",
        health_context=False,
        returning_client=None,
        practitioner=None,
        concern=None,
        state="open",
        owner="info@skincentrix.com",
        escalated_at=None,
        acknowledged_at=None,
        acknowledged_by=None,
        resolved_at=None,
        resolved_by=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ----- the tenant config: who the clinic's people are, and what a concern may be ------------


def test_team_members_are_a_name_and_a_role_and_nothing_else():
    from spatalk.tenants.schema import TeamMember

    member = TeamMember(name="Sabah Shaikh", role="founder, aesthetician")
    assert member.name == "Sabah Shaikh" and member.role == "founder, aesthetician"
    assert TeamMember(name="Emma Walker").role == ""
    assert set(TeamMember.model_fields) == {"name", "role"}
    with pytest.raises(Exception):
        member.name = "someone else"          # frozen: config is versioned, not mutated


def test_a_tenant_starts_with_no_team_and_the_default_cosmetic_concerns():
    from spatalk.tenants.schema import TenantConfig

    assert TenantConfig.model_fields["team"].get_default(call_default_factory=True) == []
    assert (
        TenantConfig.model_fields["concerns"].get_default(call_default_factory=True)
        == DEFAULT_CONCERNS
    )


def test_the_skincentrix_bundle_names_the_eleven_people_on_the_site():
    cfg = _cfg()
    assert [m.name for m in cfg.team] == [
        "Sabah Shaikh",
        "Amanda Coutts",
        "Faisal Rohile",
        "Anne Perez",
        "Ruru Ahlam",
        "Helen Courbetis",
        "Alexandra Debski",
        "Sanober Ijaz",
        "Mariam Khaizaran",
        "Hala Saeed",
        "Emma Walker",
    ]
    assert cfg.team[0].role and cfg.team[2].role      # roles where the site states one
    assert cfg.concerns == DEFAULT_CONCERNS


# ----- the draft and the request objects ---------------------------------------------------


def test_the_draft_carries_the_three_closed_fields_and_still_no_free_text():
    from spatalk.brain.ports import ItemDraft

    assert set(ItemDraft.model_fields) == {
        "type",
        "urgency",
        "service_id",
        "contact",
        "preferred_window",
        "health_context",
        "returning_client",
        "practitioner",
        "concern",
    }
    draft = ItemDraft(type="new_booking", urgency="normal")
    assert (draft.returning_client, draft.practitioner, draft.concern) == (None, None, None)
    filled = ItemDraft(
        type="new_booking",
        urgency="normal",
        returning_client=False,
        practitioner="Sabah Shaikh",
        concern="pigmentation",
    )
    assert filled.returning_client is False and filled.practitioner == "Sabah Shaikh"


def test_capture_and_booking_link_requests_carry_the_lead_fields():
    from spatalk.brain.requests import BookingLinkRequest, CaptureRequest

    req = CaptureRequest(
        kind="new_booking", returning_client=True, practitioner="any", concern="acne"
    )
    assert (req.returning_client, req.practitioner, req.concern) == (True, "any", "acne")
    link = BookingLinkRequest(service_id="facial", concern="glow", returning_client=False)
    assert link.concern == "glow" and link.returning_client is False
    assert link.practitioner is None


class _RecordingLedger:
    """A LedgerPort that keeps the drafts, so a tool call can be read end to end."""

    def __init__(self, clock):
        from spatalk.brain.ports import MemoryLedger

        self._inner = MemoryLedger(clock)
        self.drafts = []

    async def create_item(self, ref, draft):
        self.drafts.append(draft)
        return await self._inner.create_item(ref, draft)


async def test_the_driver_passes_the_lead_fields_from_a_tool_call_to_the_ledger(fixed_clock):
    """A model tool call is a dict; the three fields must survive the trip to the draft."""
    from uuid import uuid4

    from spatalk.brain.driver import dispatch_tool
    from spatalk.brain.ports import MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities

    ledger = _RecordingLedger(fixed_clock)
    caps = TierCCapabilities(ledger, MemorySms(), fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid4(), tenant=_cfg(), channel="voice", caller_phone="+19055550101"
    )
    await dispatch_tool(
        caps,
        ref,
        "capture_request",
        {
            "kind": "new_booking",
            "service_id": "mirapeel_facial",
            "contact": {"name": "Dana"},
            "returning_client": False,
            "practitioner": "any",
            "concern": "pigmentation",
        },
        fixed_clock.now(),
    )
    assert len(ledger.drafts) == 1
    draft = ledger.drafts[0]
    assert draft.returning_client is False
    assert draft.practitioner == "any" and draft.concern == "pigmentation"


# ----- the ledger: closed values only ------------------------------------------------------


async def test_the_ledger_stores_the_lead_fields(sf, registry, fixed_clock):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
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
            returning_client=False,
            practitioner="Sabah Shaikh",
            concern="pigmentation",
        ),
    )
    row = await ledger.get(rec.id)
    assert row.returning_client is False
    assert row.practitioner == "Sabah Shaikh" and row.concern == "pigmentation"


async def test_the_ledger_nulls_a_practitioner_or_concern_the_tenant_does_not_have(
    sf, registry, fixed_clock
):
    """An enum the model invented is dropped, never stored: the column is closed vocabulary."""
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice")
    rec = await ledger.create_item(
        ref,
        ItemDraft(
            type="callback",
            urgency="normal",
            practitioner="Dr Nobody",
            concern="wants a discount",
        ),
    )
    row = await ledger.get(rec.id)
    assert row.practitioner is None and row.concern is None

    # "any" is a real answer ("no preference"), not an unknown name, so it survives.
    kept = await ledger.create_item(
        ref, ItemDraft(type="callback", urgency="normal", practitioner="any")
    )
    assert (await ledger.get(kept.id)).practitioner == "any"


# ----- the summary -------------------------------------------------------------------------


def test_preferred_text_reads_like_a_person_wrote_it_and_never_says_any_any():
    from spatalk.ledger.summary import preferred_text

    assert preferred_text({"date": "any", "part_of_day": "any"}) == "any day"
    assert preferred_text({"date": "2026-09-10", "part_of_day": "any"}) == "Thursday"
    assert preferred_text({"date": "2026-09-10", "part_of_day": "afternoon"}) == (
        "Thursday afternoon"
    )
    assert preferred_text({"date": "any", "part_of_day": "morning"}) == "mornings"
    assert preferred_text({"date": "any", "part_of_day": "evening"}) == "evenings"
    assert preferred_text({}) == "any day"
    assert preferred_text(None) == "any day"
    # A date the model mangled is not a date; it never reaches a staff phone as one.
    assert preferred_text({"date": "next week", "part_of_day": "any"}) == "any day"
    for window in ({}, None, {"date": "any", "part_of_day": "any"}):
        assert "any any" not in preferred_text(window)


def test_service_name_falls_back_to_the_type_label_when_there_is_no_service():
    from spatalk.ledger.summary import service_name

    cfg = _cfg()
    assert service_name(_item(), cfg) == "Mirapeel facial with LED, microcurrent and cupping"
    assert service_name(_item(service_id=None, type="callback"), cfg) == "Callback requested"
    # A service id the tenant dropped from the catalog is not a name.
    assert service_name(_item(service_id="gone", type="callback"), cfg) == "Callback requested"


def test_a_new_booking_with_everything_set_reads_as_one_sentence():
    from spatalk.ledger.summary import summarize_item

    cfg = _cfg()
    text = summarize_item(
        _item(
            service_id="mirapeel_facial",
            concern="pigmentation",
            returning_client=False,
            practitioner="any",
            preferred_window={"date": "any", "part_of_day": "afternoon"},
        ),
        cfg,
    )
    assert text == (
        "New booking: Mirapeel facial with LED, microcurrent and cupping for pigmentation. "
        "New client, no practitioner preference. Callback afternoons."
    )


def test_a_returning_caller_who_asked_for_someone_says_so():
    from spatalk.ledger.summary import summarize_item

    text = summarize_item(
        _item(
            service_id="prp_face",
            returning_client=True,
            practitioner="Faisal Rohile",
            preferred_window={"date": "2026-09-10", "part_of_day": "morning"},
        ),
        _cfg(),
    )
    assert text == (
        "New booking: Full face PRP. Returning client, would like Faisal Rohile. "
        "Callback Thursday morning."
    )


def test_a_callback_with_nothing_set_says_nothing_it_does_not_know():
    from spatalk.ledger.summary import summarize_item

    text = summarize_item(_item(type="callback", service_id=None), _cfg())
    assert text == "Callback: Callback requested. Callback any day."
    assert "None" not in text and "any any" not in text


def test_a_send_link_item_names_the_service_and_promises_no_callback():
    from spatalk.ledger.summary import summarize_item

    text = summarize_item(_item(type="send_link", service_id="facial"), _cfg())
    assert text == "Send booking link: Facial."
    assert "Callback" not in text


def test_an_escalation_says_what_it_is_without_repeating_itself():
    from spatalk.ledger.summary import summarize_item

    cfg = _cfg()
    clinical = summarize_item(_item(type="escalation_clinical", service_id=None), cfg)
    assert clinical == "CLINICAL question."
    complaint = summarize_item(
        _item(type="escalation_complaint", service_id=None, returning_client=True), cfg
    )
    assert complaint == "COMPLAINT. Returning client."
    assert "None" not in complaint


def test_the_summary_never_leaks_a_raw_id_or_a_none():
    from spatalk.ledger.summary import summarize_item

    cfg = _cfg()
    for kwargs in (
        {},
        {"type": "callback", "service_id": None},
        {"type": "reschedule", "service_id": None, "concern": "acne"},
        {"type": "cancel", "service_id": "facial", "returning_client": True},
        {"type": "escalation_unsure", "service_id": None},
    ):
        text = summarize_item(_item(**kwargs), cfg)
        assert "None" not in text and "any any" not in text
        assert "mirapeel_facial" not in text and "_" not in text
        assert text.endswith(".")


# ----- the tools the model sees ------------------------------------------------------------


def test_the_lead_fields_are_closed_enums_on_both_booking_tools():
    from spatalk.brain.tools import build_tools

    cfg = _cfg()
    names = ["any"] + [m.name for m in cfg.team]
    for tool_name in ("capture_request", "send_booking_link"):
        tool = next(t for t in build_tools(cfg) if t.name == tool_name)
        assert tool.properties["practitioner"]["enum"] == names
        assert tool.properties["concern"]["enum"] == cfg.concerns
        assert tool.properties["returning_client"]["type"] == "boolean"
        for field in ("returning_client", "practitioner", "concern"):
            assert field not in tool.required


def test_a_tenant_with_no_team_still_offers_no_preference():
    from spatalk.brain.tools import build_tools

    cfg = _cfg().model_copy(update={"team": []})
    tool = next(t for t in build_tools(cfg) if t.name == "capture_request")
    assert tool.properties["practitioner"]["enum"] == ["any"]


# ----- the prompt --------------------------------------------------------------------------


def test_the_prompt_qualifies_the_caller_before_it_books_on_voice_and_on_text():
    from datetime import datetime, timezone

    from spatalk.brain.prompt import build_system_prompt

    now = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)
    for channel in ("voice", "sms", "chat"):
        p = build_system_prompt(_cfg(), channel, now).lower()
        assert "ask whether they have been in to see us before" in p
        assert "new-client offers listed in the facts" in p
        assert "what they have in mind" in p
        assert "someone in particular they would like to see" in p
        assert "which day or time of day suits them best" in p
        assert "any is a fine answer" in p
        assert "never guess" in p


def test_the_prompt_leaves_the_offer_wording_in_the_knowledge_file():
    from datetime import datetime, timezone

    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    now = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)
    p = build_system_prompt(cfg, "voice", now)
    # The instructions are everything before the catalog and the facts; the credit and the
    # consultation are facts about this clinic, not wording written into code.
    instructions = p.split("HOURS:")[0]
    assert "$50" not in instructions and "virtual consultation" not in instructions.lower()
    assert "new-client offers listed in the facts" in instructions
    assert "$50 credit" in cfg.knowledge and "free virtual consultation" in cfg.knowledge


# ----- delivery ----------------------------------------------------------------------------


def _links():
    from spatalk.ledger.delivery import ActionLinks
    from spatalk.ledger.links import sign_action

    ack = sign_action("s", 7, "ack", "skincentrix")
    res = sign_action("s", 7, "resolve", "skincentrix")
    return ActionLinks("https://a/ack", "https://a/res", "https://api.test/a/tok7", ack, res)


def test_the_staff_sms_carries_the_summary_instead_of_a_bare_type_label(fixed_clock):
    from spatalk.ledger.delivery import build_sms_text
    from spatalk.ledger.summary import summarize_item

    cfg, links = _cfg(), _links()
    item = _item(
        due_at=fixed_clock.now() + timedelta(hours=3),
        concern="pigmentation",
        returning_client=False,
        practitioner="any",
        preferred_window={"date": "any", "part_of_day": "afternoon"},
    )
    text = build_sms_text(item, cfg, links, fixed_clock.now())
    assert summarize_item(item, cfg) in text
    assert "via voice" in text and "Who: Dana +19055550101" in text
    assert text.endswith("Transcript: https://api.test/a/tok7")


def test_the_sms_still_fits_three_segments_with_a_long_service_and_a_long_name(fixed_clock):
    from spatalk.ledger.delivery import SMS_STAFF_LIMIT, build_sms_text, sms_segments

    cfg, links = _cfg(), _links()
    text = build_sms_text(
        _item(
            due_at=fixed_clock.now() + timedelta(hours=3),
            contact_name="Dana " + "Wollaston" * 60,
            concern="pigmentation",
            returning_client=False,
            practitioner="Alexandra Debski",
            health_context=True,
        ),
        cfg,
        links,
        fixed_clock.now(),
    )
    assert sms_segments(text) <= 3 and len(text) <= SMS_STAFF_LIMIT
    assert text.endswith("Transcript: https://api.test/a/tok7")


def test_the_email_and_slack_bodies_open_with_the_summary(fixed_clock):
    from spatalk.ledger.delivery import build_email, build_slack_blocks
    from spatalk.ledger.summary import summarize_item

    cfg, links = _cfg(), _links()
    item = _item(
        due_at=fixed_clock.now() + timedelta(hours=3),
        concern="acne",
        returning_client=True,
        practitioner="Amanda Coutts",
    )
    summary = summarize_item(item, cfg)
    _subject, body = build_email(item, cfg, links, fixed_clock.now())
    assert body.startswith(summary)
    blocks = build_slack_blocks(item, cfg, links, fixed_clock.now())
    assert blocks[1]["text"]["text"].startswith(summary)


# ----- the internal API --------------------------------------------------------------------


def test_item_out_serialises_the_lead_fields_and_the_derived_wording(fixed_clock):
    from spatalk.http.internal import ItemOut, item_out
    from spatalk.ledger.summary import summarize_item

    cfg = _cfg()
    item = _item(
        due_at=fixed_clock.now() + timedelta(hours=3),
        created_at=fixed_clock.now(),
        concern="pigmentation",
        returning_client=False,
        practitioner="any",
        preferred_window={"date": "any", "part_of_day": "afternoon"},
    )
    out = item_out(item, cfg)
    assert isinstance(out, ItemOut)
    body = out.model_dump()
    assert body["summary"] == summarize_item(item, cfg)
    assert body["service_name"] == "Mirapeel facial with LED, microcurrent and cupping"
    assert body["preferred_text"] == "afternoons"
    assert body["returning_client"] is False
    assert body["practitioner"] == "any" and body["concern"] == "pigmentation"


def test_item_out_leaves_service_name_empty_when_there_is_no_service(fixed_clock):
    from spatalk.http.internal import item_out

    out = item_out(
        _item(
            type="callback",
            service_id=None,
            due_at=fixed_clock.now() + timedelta(hours=3),
            created_at=fixed_clock.now(),
        ),
        _cfg(),
    )
    assert out.service_name is None
    assert out.summary == "Callback: Callback requested. Callback any day."
    assert out.preferred_text == "any day"
