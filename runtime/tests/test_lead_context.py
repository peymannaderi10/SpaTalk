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


def test_a_name_or_a_concern_wider_than_its_column_is_refused_at_import():
    """`items.practitioner` is varchar(80) and `items.concern` varchar(40) (data-model.md).

    Without the bound, a long name is accepted at import and every item that names that
    person then fails to write, losing the request mid-call. The config is the cheap place
    to say no.
    """
    from pydantic import ValidationError

    from spatalk.tenants.schema import TeamMember, TenantConfig

    assert TeamMember(name="N" * 80).name == "N" * 80
    with pytest.raises(ValidationError):
        TeamMember(name="N" * 81)

    raw = _cfg().model_dump()
    with pytest.raises(ValidationError):
        TenantConfig.model_validate({**raw, "team": [{"name": "N" * 200, "role": ""}]})
    with pytest.raises(ValidationError):
        TenantConfig.model_validate({**raw, "concerns": ["c" * 41]})
    # 40 characters is the column, so 40 characters is legal.
    assert TenantConfig.model_validate({**raw, "concerns": ["c" * 40]}).concerns == ["c" * 40]


def test_a_medical_word_cannot_be_configured_as_a_cosmetic_concern():
    """Global Constraints: "Health stays out of the fields", enforced rather than trusted.

    A tenant who adds "rosacea" turns a condition into a closed value the ledger will write
    to `items.concern`, where nothing treats it as clinical detail. The shipped defaults are
    cosmetic and must keep loading.
    """
    from pydantic import ValidationError

    from spatalk.tenants.schema import TenantConfig

    raw = _cfg().model_dump()
    for medical in ("rosacea", "pregnancy", "Botox", "scarring", "sensitive skin"):
        with pytest.raises(ValidationError):
            TenantConfig.model_validate({**raw, "concerns": ["pigmentation", medical]})
    # A word inside a phrase counts too: "post treatment glow" carries a clinical term.
    with pytest.raises(ValidationError):
        TenantConfig.model_validate({**raw, "concerns": ["peeling skin"]})
    assert TenantConfig.model_validate(raw).concerns == DEFAULT_CONCERNS
    assert TenantConfig.model_validate({**raw, "concerns": ["brightening"]}).concerns == [
        "brightening"
    ]


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


def test_the_preferred_window_date_is_a_closed_value_and_never_a_sentence():
    """CLAUDE.md 2: the window is written straight into JSONB, so it is the last gate.

    The date takes an ISO date, a weekday name or "any", and nothing else. It never raises:
    a rejected value must cost the preference, never the request the caller is making.
    """
    from spatalk.brain.requests import PreferredWindow

    assert PreferredWindow().date == "any"
    assert PreferredWindow(date="2026-09-24").date == "2026-09-24"
    assert PreferredWindow(date="Thursday").date == "Thursday"
    assert PreferredWindow(date="thursday").date == "Thursday"      # stored in one shape
    for free_text in (
        "whenever the burn on my arm from the laser settles down",
        "next week",
        "tomorrow-ish",
        "0000-00-00",
        "the 24th",
        "",
        "   ",
        None,
    ):
        assert PreferredWindow(date=free_text).date == "any", free_text


class _RecordingLedger:
    """A LedgerPort that keeps the drafts, so a tool call can be read end to end."""

    def __init__(self, clock):
        from spatalk.brain.ports import MemoryLedger

        self._inner = MemoryLedger(clock)
        self.drafts = []

    async def create_item(self, ref, draft):
        self.drafts.append(draft)
        return await self._inner.create_item(ref, draft)


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
    # A real date keeps the day the caller named: "Thursday" three weeks out reads as this
    # Thursday, which is how a callback gets made on the wrong day.
    assert preferred_text({"date": "2026-09-10", "part_of_day": "any"}) == "Thursday 10 September"
    assert preferred_text({"date": "2026-09-10", "part_of_day": "afternoon"}) == (
        "Thursday 10 September, afternoons"
    )
    # A weekday the caller named without a date is only a weekday.
    assert preferred_text({"date": "Thursday", "part_of_day": "any"}) == "Thursday"
    assert preferred_text({"date": "Thursday", "part_of_day": "afternoon"}) == "Thursday afternoon"
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
        "New client, no practitioner preference. Would like to come in afternoons."
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
        "Would like to come in Thursday 10 September, mornings."
    )


def test_a_callback_with_nothing_set_says_nothing_it_does_not_know():
    from spatalk.ledger.summary import summarize_item

    text = summarize_item(_item(type="callback", service_id=None), _cfg())
    assert text == "Callback: Callback requested. Would like to come in any day."
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


# ----- the prompt --------------------------------------------------------------------------


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
    assert out.summary == "Callback: Callback requested. Would like to come in any day."
    assert out.preferred_text == "any day"


def test_team_members_are_a_name_a_role_and_the_services_they_do():
    from spatalk.tenants.schema import TeamMember

    member = TeamMember(name="Sabah Shaikh", role="founder, aesthetician")
    assert member.name == "Sabah Shaikh" and member.role == "founder, aesthetician"
    assert TeamMember(name="Emma Walker").role == "" and TeamMember(name="Emma Walker").services == []
    assert set(TeamMember.model_fields) == {"name", "role", "services"}
    with pytest.raises(Exception):
        member.name = "someone else"          # frozen: config is versioned, not mutated


def test_the_draft_takes_the_lead_fields_from_the_slot_record():
    """The lead fields ride from the engine's record to the draft; nothing else carries them."""
    from spatalk.brain.flow import Slots, draft_from
    from spatalk.brain.requests import BookingLinkRequest

    s = Slots(flow="new_booking", returning_client=True, practitioner="any", service_id="facial",
              first_name="Dana", phone="+19055550101", phone_confirmed=True)
    d = draft_from(s, _cfg())
    assert (d.returning_client, d.practitioner, d.concern) == (True, "any", None)
    assert set(BookingLinkRequest.model_fields) == {"service_id", "contact"}


async def test_the_engine_passes_the_lead_fields_from_the_record_to_the_ledger(fixed_clock):
    """The record is the only source: the model's tool call carries nothing about the item."""
    from uuid import uuid4

    from spatalk.brain.driver import run_tool
    from spatalk.brain.flow import Slots
    from spatalk.brain.ports import MemorySms
    from spatalk.brain.requests import ConversationRef, PreferredWindow
    from spatalk.brain.tier_c import TierCCapabilities

    ledger = _RecordingLedger(fixed_clock)
    caps = TierCCapabilities(ledger, MemorySms(), fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid4(), tenant=_cfg(), channel="voice", caller_phone="+19055550101"
    )
    slots = Slots(flow="callback", returning_client=False, offers_done=True, practitioner="any",
                  service_id="mirapeel_facial", first_name="Dana", phone="+19055550101",
                  phone_confirmed=True, preferred_window=PreferredWindow(), team_note_asked=True)
    await run_tool(caps, ref, slots, "file_request", {}, fixed_clock.now())
    assert len(ledger.drafts) == 1
    draft = ledger.drafts[0]
    assert draft.returning_client is False
    assert draft.practitioner == "any" and draft.concern is None


def test_no_tool_carries_a_lead_field_any_more():
    """The three lead values are decided by the engine from list matches, never typed by the model."""
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    for step in Step:
        for tool in step_tools(step, Slots(flow="new_booking"), cfg, "voice", transfer_enabled=True):
            assert not {"returning_client", "practitioner", "concern"} & set(tool.properties), tool.name


def test_a_tenant_with_no_team_still_takes_no_preference():
    from spatalk.brain.resolve import match_practitioner

    cfg = _cfg().model_copy(update={"team": []})
    assert match_practitioner("anyone is fine", cfg).value == "any"
    assert match_practitioner("Helen", cfg).kind == "none"


def test_the_engine_qualifies_the_caller_in_the_same_order_on_every_channel():
    from spatalk.brain.flow import Slots, Step, next_step, step_question

    cfg = _cfg()
    for channel in ("voice", "sms", "chat"):
        s = Slots(flow="new_booking")
        assert next_step(s, cfg, channel) == Step.RETURNING
        assert step_question(Step.RETURNING, s, cfg, channel) == ("ask_returning", {})
        s = s.with_(returning_client=True)
        assert step_question(next_step(s, cfg, channel), s, cfg, channel) == ("ask_practitioner", {})
        s = s.with_(practitioner="any")
        assert step_question(next_step(s, cfg, channel), s, cfg, channel) == ("ask_service", {})
    assert cfg.scripts.ask_window.endswith("Any is fine.")


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
    assert "$50 credit" in cfg.knowledge and "free virtual consultation" in cfg.knowledge
