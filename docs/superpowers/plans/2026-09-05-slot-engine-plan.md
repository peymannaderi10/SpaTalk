# Slot Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The runtime, not the model, owns the order and wording of every request conversation, so no tracked item is ever filed without a first name and a phone number and no item field ever comes from a model argument.

**Architecture:** A pure module `spatalk/brain/flow.py` holds a per-conversation `Slots` record, a fixed `next_step()`, the per-step tool list and the per-step fixed question; `spatalk/brain/resolve.py` matches a caller's words against the tenant's lists. `Brain.turn` (text) and the voice handlers both call `flow.apply()` on every tool call, speak the fixed lines the runtime returns, and offer the model only the next step's tools. `file_request()` takes no arguments and builds the `ItemDraft` from the record.

**Tech Stack:** Python 3.12, pydantic 2, SQLAlchemy async + Alembic, Pipecat 1.8.1 (`LLMContext.set_tools`, `TTSSpeakFrame`), rapidfuzz, metaphone, pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-slot-engine-design.md` (sections numbered §N below). Research: `docs/research/research-3-deterministic-flows.md`.

## Global Constraints

- CLAUDE.md non-negotiables apply, especially 1 (structural honesty), 2 (no free text on tracked items), 3 (fixed wording is config), 6 (Pipecat 1.8 API only: `PipelineWorker`, `LLMContext`, `LLMContextAggregatorPair`).
- Spec §3 invariants: `file_request`/`send_link` absent until every required slot is filled; `ItemDraft` built only by `draft_from`; closed slots hold list values or nothing; every question is a tenant script; the model contributes at most one acknowledgement sentence, which passes `guard()`.
- Wording: every script line in spec §7 verbatim, in `spatalk/tenants/schema.py` (default), `runtime/tenants/skincentrix/scripts.yaml` and `docs/reference/tenant-config.md` — `tests/test_qa_gate_a.py` compares the three key-for-key.
- Thresholds (§5): accept ≥ 0.90, confirm 0.60–0.90, re-ask below; two misses → `practitioner_any` / `ask_service_kind`.
- Deviation from spec §6.5, decided before this plan: the voice adapter does **not** use `pipecat.flows.FlowManager`. Flows delivers the role message through `LLMUpdateSettingsFrame(system_instruction=…)`, which would move the system prompt out of the `LLMContext` where `RulesGateProcessor`, `OutputGuardProcessor` and `_finalize` expect it. The spec's own fallback (a small step-sync of our own using `LLMContext.set_tools`, a replaced step message and `TTSSpeakFrame`) is the primary implementation (Task 10).
- Commands, from `runtime/`: `uv run pytest -q <files>` (one pytest run at a time), `uv run ruff check spatalk tests scenarios`, `uv run alembic upgrade head`. Portal untouched by this plan.
- Commits: conventional messages, no trailers of any kind (founder rule). Never `--no-verify`. Do not restart the runtime, import the bundle, or edit `runtime/.env`; the founder's session does go-live (Task 13).
- Some test files have CRLF line endings (`tests/test_qa_gate_a.py`, `tests/test_tier_c.py`, `spatalk/text/service.py`); preserve each file's own ending.
- Work on branch `slot-engine` from `main`.

## File Structure

| File | Responsibility |
|---|---|
| `spatalk/brain/resolve.py` (new) | Matching a caller's words to team names, service ids, service categories; phone normalising and read-back. Pure. |
| `spatalk/brain/flow.py` (new) | `Slots`, `Step`, `next_step`, `step_question`, `step_tools`, `step_message`, `apply`, `draft_from`. Pure. |
| `spatalk/brain/tools.py` | The closed tool schemas (rewritten: slot tools in, contact/lead arguments out). |
| `spatalk/brain/prompt.py` | Static prompt loses the booking-order, offers and name/number bullets. |
| `spatalk/brain/driver.py` | `Brain.turn` takes and returns `Slots`; `dispatch_tool` is replaced by `flow.apply` + the acts it requests. |
| `spatalk/brain/tier_c.py`, `capabilities.py`, `requests.py` | `capture` takes an `ItemDraft` built by `draft_from`; `CaptureRequest`/`AppointmentChangeRequest` go. |
| `spatalk/tenants/schema.py` | New script keys; `TeamMember.services`. |
| `spatalk/models.py`, `alembic/versions/0013_flow_slots.py` | `conversations.flow` JSONB. |
| `spatalk/text/service.py` | Loads/saves `Slots` around `Brain.turn`. |
| `spatalk/voice/session.py`, `handlers.py`, `processors.py`, `pipeline.py` | Voice adapter: per-step tools and step message in the context, fixed lines spoken, clinical offer from the gate. |
| `tenants/skincentrix/scripts.yaml`, `tenant.yaml` | New scripts; `team[].services`. |
| `docs/reference/tenant-config.md`, `data-model.md`, `flows.md`, `api-surface.md` | Reference updated. |
| `scenarios/` | promptfoo scenarios per step. |

---

### Task 1: Scripts, `team[].services`, dependencies, reference doc

**Files:**
- Modify: `spatalk/tenants/schema.py` (class `Scripts` ~line 77; class `TeamMember` ~line 37; `TenantConfig` validators ~line 360)
- Modify: `tenants/skincentrix/scripts.yaml`, `tenants/skincentrix/tenant.yaml`
- Modify: `docs/reference/tenant-config.md` (the scripts list; the team section)
- Modify: `pyproject.toml` (dependencies)
- Test: `tests/test_tenant_schema_flow.py` (new), `tests/test_qa_gate_a.py` (existing key-for-key tests must pass)

**Interfaces:**
- Produces: `Scripts` fields `ask_returning, ask_offers, ask_after_offers, ask_practitioner, ask_practitioner_again, practitioner_any, practitioner_not_service, practitioner_suggest, practitioner_else, ask_service, ask_service_kind, ask_service_again, confirm_match, confirm_which, ask_name, ask_name_again, no_name, confirm_name_staff, ask_phone_same, ask_phone, confirm_phone, phone_fallback, ask_window, ask_team_note, ask_route, clinical_offer, clinical_declined` (all `str`, all with defaults); `TeamMember.services: list[str]`; `TenantConfig.team_for_service(service_id) -> list[TeamMember]`; `TenantConfig.member_does(name, service_id) -> bool`.

- [ ] **Step 1: Add the dependencies**

In `pyproject.toml` `[project] dependencies`, add `"rapidfuzz>=3.9"` and `"metaphone>=0.6"`. Run `uv pip install -e ".[dev]"`.

- [ ] **Step 2: Write the failing tests**

`tests/test_tenant_schema_flow.py`:

```python
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_every_slot_script_has_a_default_and_the_bundle_supplies_it():
    from spatalk.tenants.schema import Scripts
    keys = [
        "ask_returning", "ask_offers", "ask_after_offers", "ask_practitioner",
        "ask_practitioner_again", "practitioner_any", "practitioner_not_service",
        "practitioner_suggest", "practitioner_else", "ask_service", "ask_service_kind",
        "ask_service_again", "confirm_match", "confirm_which", "ask_name", "ask_name_again",
        "no_name", "confirm_name_staff", "ask_phone_same", "ask_phone", "confirm_phone",
        "phone_fallback", "ask_window", "ask_team_note", "ask_route", "clinical_offer",
        "clinical_declined",
    ]
    fields = Scripts.model_fields
    for key in keys:
        assert key in fields, key
        assert fields[key].default not in (None, ""), key
    cfg = _cfg()
    assert cfg.scripts.ask_name == "Could I get your first name?"
    assert cfg.scripts.confirm_match == "Did you mean {value}?"
    assert "911" not in cfg.scripts.clinical and "911" not in cfg.scripts.clinical_text


def test_team_services_are_validated_and_queryable():
    import pytest
    cfg = _cfg()
    helen = next(m for m in cfg.team if m.name.startswith("Helen"))
    assert cfg.member_does(helen.name, "hydrabrasion_facial")
    assert helen.name in [m.name for m in cfg.team_for_service("hydrabrasion_facial")]
    # An empty list means every service.
    anyone = next(m for m in cfg.team if not m.services)
    assert cfg.member_does(anyone.name, "hydrabrasion_facial")
    with pytest.raises(ValueError):
        cfg.model_copy(update={"team": [helen.model_copy(update={"services": ["no_such_service"]})]}).check_team_services()
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest -q tests/test_tenant_schema_flow.py`
Expected: FAIL — `Scripts` has no `ask_returning`; `TenantConfig` has no `member_does`.

- [ ] **Step 4: Add the script fields with the spec §7 wording**

In `Scripts` (after `clinical_declined` is easiest to keep grouped; place the block after `refuse_unavailable`):

```python
    # --- slot engine: the questions the runtime asks (slot engine design, §7) ---------
    ask_returning: str = "Have you been in to see us before?"
    ask_offers: str = "Would you like to hear our new-client offers?"
    ask_after_offers: str = "What did you have in mind?"
    ask_practitioner: str = (
        "Is there someone in particular you'd like to see, or whoever's available?"
    )
    ask_practitioner_again: str = "Sorry, who would you like to see? Anyone's fine too."
    practitioner_any: str = "No problem, I'll leave it as whoever's available."
    practitioner_not_service: str = (
        "Unfortunately {practitioner} doesn't do {service}. I can suggest someone, if you "
        "don't have anyone else in mind?"
    )
    practitioner_suggest: str = "{names} can do {service}. Would one of them work?"
    practitioner_else: str = "Who else did you have in mind?"
    ask_service: str = "What would you like to come in for?"
    ask_service_kind: str = (
        "I can run through two or three options, or {consultation} can help you pick — "
        "which would you prefer?"
    )
    ask_service_again: str = "Sorry, which treatment did you have in mind?"
    confirm_match: str = "Did you mean {value}?"
    confirm_which: str = "Did you mean {first} or {second}?"
    ask_name: str = "Could I get your first name?"
    ask_name_again: str = "Just a first name is fine — it's so the team knows who to ask for."
    no_name: str = (
        "No problem — you can reach the clinic at {phone} during opening hours. "
        "Is there anything else I can help with?"
    )
    confirm_name_staff: str = "Just to check, your first name is {name} as well?"
    ask_phone_same: str = "Is the number you're calling from the best one to reach you on?"
    ask_phone: str = "What's the best number to reach you on?"
    confirm_phone: str = "That's {digits} — is that right?"
    phone_fallback: str = "No problem, I'll use the number you're calling from."
    ask_window: str = "Which day or time of day suits you best for the visit? Any is fine."
    ask_team_note: str = "Is there anything you'd like the team to know before they call?"
    ask_route: str = (
        "I can text you the booking link now, or have the team call you to book — "
        "which do you prefer?"
    )
    clinical_offer: str = (
        "That's one for our clinical team rather than me — would you like me to have them "
        "reach out to you?"
    )
    clinical_declined: str = "No problem. Is there anything else I can help with?"
```

Change the defaults of `clinical` and `clinical_text` (they are required fields in the bundle; change the bundle wording in Step 6 to match):

- `clinical`: `I've passed that to our clinical team as an urgent request, and someone will call you back at this number as soon as possible. Is there anything else I can help with?`
- `clinical_text`: `I've passed that to our clinical team as an urgent request; someone will call you as soon as possible. Anything else I can help with?`

The `_no_completion_words` validator on `Scripts` already forbids completion words; the new lines contain none.

- [ ] **Step 5: `TeamMember.services` and the two helpers**

```python
class TeamMember(BaseModel, frozen=True):
    ...
    name: str = Field(max_length=80)
    role: str = ""
    # The services this person performs, by `services[].id`. Empty means every service
    # (slot engine design, §4.3): the "Helen doesn't do X" line needs a list to be true.
    services: list[str] = Field(default_factory=list)
```

On `TenantConfig`:

```python
    @model_validator(mode="after")
    def check_team_services(self):
        ids = {s.id for s in self.services}
        for member in self.team:
            unknown = [s for s in member.services if s not in ids]
            if unknown:
                raise ValueError(f"team member {member.name} lists unknown services {unknown}")
        return self

    def member_does(self, name: str, service_id: str) -> bool:
        member = next((m for m in self.team if m.name == name), None)
        if member is None:
            return False
        return not member.services or service_id in member.services

    def team_for_service(self, service_id: str) -> list[TeamMember]:
        return [m for m in self.team if not m.services or service_id in m.services]
```

(`model_validator` is already imported in `schema.py` if other validators use it; otherwise add `from pydantic import model_validator`.)

- [ ] **Step 6: Bundle and reference doc**

`tenants/skincentrix/scripts.yaml`: add every key from Step 4 with the same wording (the QA-gate test requires the bundle to supply every reference key), and replace the `clinical:` / `clinical_text:` lines with the new wording.

`tenants/skincentrix/tenant.yaml`: give each `team[]` entry a `services:` list from the roles the site states — nurses (Faisal Rohile, Anne Perez) get the injectables and PRP ids; aestheticians get the facials, peels, laser and express ids; anyone whose role does not say leaves it empty. Use the ids in `services.yaml`.

`docs/reference/tenant-config.md`: add one line per new key in the scripts list, in the `key: "wording"` form the file uses (line ~94 shows the style), change the `clinical` and `clinical_text` lines, and document `team[].services` under the team section.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest -q tests/test_tenant_schema_flow.py tests/test_qa_gate_a.py tests/test_renderer.py tests/test_structural_honesty.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock spatalk/tenants/schema.py tenants/skincentrix/scripts.yaml tenants/skincentrix/tenant.yaml docs/reference/tenant-config.md tests/test_tenant_schema_flow.py
git commit -m "feat(config): the slot engine's question scripts, team[].services, and the matching libraries"
```

---

### Task 2: Resolvers

**Files:**
- Create: `spatalk/brain/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Produces:
  - `class Match(BaseModel, frozen=True): kind: Literal["exact","confirm","which","kind","none"]; value: str | None; candidates: tuple[str, ...]`
  - `match_practitioner(said: str, cfg: TenantConfig) -> Match` — `value` is a `team[].name` or `"any"`.
  - `match_service(said: str, cfg: TenantConfig) -> Match` — `value` is a `services[].id`, or a category when `kind == "kind"`.
  - `normalise_phone(digits: str) -> str | None` — E.164 `+1NNNNNNNNNN` or `None`.
  - `spoken_digits(e164: str) -> str` (`"four one six, five five five, zero one nine nine"`), `typed_digits(e164: str) -> str` (`"416-555-0199"`).
  - `first_name_of(full: str) -> str`, `sounds_like(a: str, b: str) -> bool`.
  - Constants `ACCEPT = 0.90`, `CONFIRM = 0.60`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_exact_and_phonetic_practitioner_matches():
    from spatalk.brain.resolve import match_practitioner
    cfg = _cfg()
    assert match_practitioner("Helen", cfg).kind == "exact"
    assert match_practitioner("helen courbetis", cfg).value == "Helen Courbetis"
    m = match_practitioner("Ellen", cfg)
    assert m.kind == "confirm" and m.value == "Helen Courbetis"
    assert match_practitioner("whoever's available", cfg).value == "any"
    assert match_practitioner("no preference", cfg).value == "any"
    assert match_practitioner("xqzv", cfg).kind == "none"


def test_two_members_with_one_first_name_ask_which():
    from spatalk.brain.resolve import match_practitioner
    from spatalk.tenants.schema import TeamMember
    cfg = _cfg()
    cfg2 = cfg.model_copy(update={"team": list(cfg.team) + [TeamMember(name="Amanda Kerr")]})
    m = match_practitioner("Amanda", cfg2)
    assert m.kind == "which" and set(m.candidates) == {"Amanda Coutts", "Amanda Kerr"}


def test_service_matches_by_name_and_by_kind():
    from spatalk.brain.resolve import match_service
    cfg = _cfg()
    assert match_service("hydrabrasion", cfg).value == "hydrabrasion_facial"
    m = match_service("hydroabrasion facial", cfg)
    assert m.value == "hydrabrasion_facial" and m.kind in ("exact", "confirm")
    k = match_service("a facial", cfg)
    assert k.kind == "kind" and k.value == "facial"
    assert match_service("blorp", cfg).kind == "none"


def test_phone_normalising_and_read_back():
    from spatalk.brain.resolve import normalise_phone, spoken_digits, typed_digits
    assert normalise_phone("416 555 0199") == "+14165550199"
    assert normalise_phone("1-416-555-0199") == "+14165550199"
    assert normalise_phone("+1 (416) 555-0199") == "+14165550199"
    assert normalise_phone("555 0199") is None
    assert normalise_phone("four one six") is None
    assert spoken_digits("+14165550199") == "four one six, five five five, zero one nine nine"
    assert typed_digits("+14165550199") == "416-555-0199"


def test_sounds_like_and_first_name():
    from spatalk.brain.resolve import first_name_of, sounds_like
    assert first_name_of("Helen Courbetis") == "Helen"
    assert sounds_like("Ellen", "Helen") and not sounds_like("Dana", "Helen")
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_resolve.py`
Expected: FAIL with `ModuleNotFoundError: spatalk.brain.resolve`.

- [ ] **Step 3: Implement `spatalk/brain/resolve.py`**

```python
"""Matching a caller's words to the tenant's lists (slot engine design, §5).

Everything here is code, not model: the model passes what the caller said, these
functions decide whether it names something on a list, and only a list value is ever
stored. Thresholds are the memo's starting points; the call tests tune them.
"""
from __future__ import annotations

import re
from typing import Literal

from metaphone import doublemetaphone
from pydantic import BaseModel
from rapidfuzz import fuzz

from spatalk.tenants.schema import TenantConfig

ACCEPT = 0.90
CONFIRM = 0.60

ANY_WORDS = (
    "any", "anyone", "anybody", "whoever", "whoever's available", "no preference",
    "doesn't matter", "does not matter", "either", "no one in particular",
    "nobody in particular", "not really", "no",
)
STRIP_WORDS = ("with", "dr", "dr.", "doctor", "nurse", "the", "a", "an", "please", "to see")
DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


class Match(BaseModel, frozen=True):
    kind: Literal["exact", "confirm", "which", "kind", "none"]
    value: str | None = None
    candidates: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    words = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).split()
    return " ".join(w for w in words if w not in STRIP_WORDS)


def first_name_of(full: str) -> str:
    return (full or "").split()[0] if full else ""


def sounds_like(a: str, b: str) -> bool:
    pa, pb = doublemetaphone(a or ""), doublemetaphone(b or "")
    codes_a = {c for c in pa if c}
    codes_b = {c for c in pb if c}
    return bool(codes_a & codes_b)


def _score(said: str, candidate: str) -> float:
    return fuzz.WRatio(said, candidate.lower()) / 100.0


def _best(said: str, options: list[tuple[str, str]]) -> Match:
    """`options` are (value, label) pairs; labels are matched, values returned."""
    if not said:
        return Match(kind="none")
    exact = [v for v, label in options if _normalise(label) == said or first_name_of(_normalise(label)) == said]
    if len(exact) == 1:
        return Match(kind="exact", value=exact[0])
    if len(exact) > 1:
        return Match(kind="which", candidates=tuple(exact[:2]))
    scored = sorted(((_score(said, label), v) for v, label in options), reverse=True)
    top, value = scored[0]
    if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.02 and top >= CONFIRM:
        return Match(kind="which", candidates=(scored[0][1], scored[1][1]))
    if top >= ACCEPT:
        return Match(kind="exact", value=value)
    if top >= CONFIRM:
        return Match(kind="confirm", value=value, candidates=(value,))
    return Match(kind="none")


def match_practitioner(said: str, cfg: TenantConfig) -> Match:
    text = _normalise(said)
    if not text or text in ANY_WORDS or any(text.startswith(w) for w in ("whoever", "anyone", "anybody")):
        return Match(kind="exact", value="any")
    options = [(m.name, m.name) for m in cfg.team]
    # A single first name that sounds like exactly one team member's first name.
    phonetic = [m.name for m in cfg.team if sounds_like(text, first_name_of(m.name))]
    if len(phonetic) == 1 and _normalise(first_name_of(phonetic[0])) != text:
        return Match(kind="confirm", value=phonetic[0], candidates=(phonetic[0],))
    if len(phonetic) > 1:
        return Match(kind="which", candidates=tuple(phonetic[:2]))
    return _best(text, options)


def match_service(said: str, cfg: TenantConfig) -> Match:
    text = _normalise(said)
    if not text:
        return Match(kind="none")
    categories = sorted({s.category for s in cfg.services})
    if text in categories or text.rstrip("s") in categories:
        return Match(kind="kind", value=text if text in categories else text.rstrip("s"))
    options = [(s.id, s.name) for s in cfg.services]
    match = _best(text, options)
    if match.kind == "none":
        for cat in categories:
            if cat in text.split():
                return Match(kind="kind", value=cat)
    return match


def normalise_phone(digits: str) -> str | None:
    only = re.sub(r"\D", "", digits or "")
    if len(only) == 11 and only.startswith("1"):
        only = only[1:]
    if len(only) != 10:
        return None
    return "+1" + only


def spoken_digits(e164: str) -> str:
    n = e164[-10:]
    groups = (n[:3], n[3:6], n[6:])
    return ", ".join(" ".join(DIGIT_WORDS[int(d)] for d in g) for g in groups)


def typed_digits(e164: str) -> str:
    n = e164[-10:]
    return f"{n[:3]}-{n[3:6]}-{n[6:]}"
```

- [ ] **Step 4: Run the tests; tune only the tests' expectations that reveal a real bug**

Run: `uv run pytest -q tests/test_resolve.py`
Expected: PASS. If "hydroabrasion facial" scores below `ACCEPT`, `kind == "confirm"` is accepted by the test; if it scores below `CONFIRM`, lower nothing — add a phonetic pass on the first word of service names the same way `match_practitioner` does, and keep the thresholds.

- [ ] **Step 5: Commit**

```bash
git add spatalk/brain/resolve.py tests/test_resolve.py
git commit -m "feat(brain): resolvers match a caller's words to the team and service lists, phone numbers normalised"
```

---

### Task 3: `Slots`, `Step`, `next_step`, `step_question`

**Files:**
- Create: `spatalk/brain/flow.py`
- Test: `tests/test_flow_order.py`

**Interfaces:**
- Produces:
  - `Flow = Literal["new_booking","callback","reschedule","cancel","question","clinical"]`
  - `class Step(str, Enum)`: `QA, RETURNING, OFFERS, PRACTITIONER, SERVICE, NAME, PHONE, WINDOW, TEAM_NOTE, ROUTE, COMPLETE`
  - `class Pending(BaseModel, frozen=True): kind: Literal["match","which","name_staff","phone","not_service","offers","route"]; slot: str; value: str | None; candidates: tuple[str, ...]`
  - `class Slots(BaseModel, frozen=True)` with fields `flow, returning_client, offers_done, practitioner, service_id, first_name, phone, phone_confirmed, preferred_window, team_note_asked, pending, misses, ended_flow` and `.with_(**changes) -> Slots`, `.miss(slot) -> Slots`.
  - `next_step(slots: Slots, cfg: TenantConfig, channel: str) -> Step`
  - `step_question(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> tuple[str, dict] | None` — a `scripts` key and fills, or `None` at `QA`/`COMPLETE`.
  - `NAME_REQUIRED_FLOWS = ("new_booking","callback","reschedule","cancel","question","clinical")`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def _walk(slots, cfg, channel, answers):
    """Apply a dict of slot values one step at a time and return the steps visited."""
    from spatalk.brain.flow import Step, next_step
    seen = []
    for _ in range(20):
        step = next_step(slots, cfg, channel)
        seen.append(step)
        if step == Step.COMPLETE:
            break
        slots = answers[step](slots)
    return seen


def test_new_client_booking_order_on_a_call():
    from spatalk.brain.flow import Slots, Step
    from spatalk.brain.requests import PreferredWindow
    cfg = _cfg()
    answers = {
        Step.RETURNING: lambda s: s.with_(returning_client=False),
        Step.OFFERS: lambda s: s.with_(offers_done=True),
        Step.SERVICE: lambda s: s.with_(service_id="hydrabrasion_facial"),
        Step.PRACTITIONER: lambda s: s.with_(practitioner="any"),
        Step.NAME: lambda s: s.with_(first_name="Dana"),
        Step.PHONE: lambda s: s.with_(phone="+19055550101", phone_confirmed=True),
        Step.WINDOW: lambda s: s.with_(preferred_window=PreferredWindow()),
        Step.TEAM_NOTE: lambda s: s.with_(team_note_asked=True),
        Step.ROUTE: lambda s: s.with_(ended_flow=True),
    }
    seen = _walk(Slots(flow="new_booking"), cfg, "voice", answers)
    assert seen == [Step.RETURNING, Step.OFFERS, Step.SERVICE, Step.PRACTITIONER, Step.NAME,
                    Step.PHONE, Step.WINDOW, Step.TEAM_NOTE, Step.ROUTE, Step.COMPLETE]


def test_returning_client_asks_practitioner_first_and_no_offers():
    from spatalk.brain.flow import Slots, Step, next_step
    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=True)
    assert next_step(s, cfg, "voice") == Step.PRACTITIONER
    s = s.with_(practitioner="Helen Courbetis")
    assert next_step(s, cfg, "voice") == Step.SERVICE


def test_sms_skips_the_phone_step_and_chat_asks_it():
    from spatalk.brain.flow import Slots, Step, next_step
    from spatalk.brain.requests import PreferredWindow
    cfg = _cfg()
    s = Slots(flow="callback", returning_client=True, practitioner="any",
              service_id="hydrabrasion_facial", first_name="Dana")
    assert next_step(s, cfg, "sms") == Step.WINDOW
    assert next_step(s, cfg, "chat") == Step.PHONE
    assert next_step(s, cfg, "voice") == Step.PHONE


def test_callback_files_without_the_route_step_and_question_needs_only_name_and_phone():
    from spatalk.brain.flow import Slots, Step, next_step
    from spatalk.brain.requests import PreferredWindow
    cfg = _cfg()
    s = Slots(flow="callback", returning_client=False, offers_done=True, practitioner="any",
              service_id="hydrabrasion_facial", first_name="Dana", phone="+1", phone_confirmed=True,
              preferred_window=PreferredWindow(), team_note_asked=True)
    assert next_step(s, cfg, "voice") == Step.COMPLETE
    q = Slots(flow="question", first_name="Dana", phone="+1", phone_confirmed=True)
    assert next_step(q, cfg, "voice") == Step.COMPLETE
    assert next_step(Slots(flow="question"), cfg, "voice") == Step.NAME


def test_step_question_keys_and_fills():
    from spatalk.brain.flow import Pending, Slots, Step, step_question
    cfg = _cfg()
    assert step_question(Step.NAME, Slots(flow="callback"), cfg, "voice") == ("ask_name", {})
    assert step_question(Step.QA, Slots(), cfg, "voice") is None
    pending = Slots(flow="new_booking", pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"))
    assert step_question(Step.PRACTITIONER, pending, cfg, "voice") == ("confirm_match", {"value": "Helen"})
    kind_q = step_question(Step.SERVICE, Slots(flow="new_booking", pending=Pending(kind="offers", slot="service_kind")), cfg, "voice")
    assert kind_q[0] == "ask_service_kind" and "consultation" in kind_q[1]["consultation"].lower()
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_flow_order.py`
Expected: FAIL — no module `spatalk.brain.flow`.

- [ ] **Step 3: Implement the record, the order and the questions**

`spatalk/brain/flow.py` (first half; Tasks 4–6 add to this file):

```python
"""The runtime owns the request conversation (slot engine design, 2026-09-05).

`Slots` is what the runtime knows about the open request. `next_step` is the fixed order.
`step_question` is the script the caller hears next. Nothing here talks to a model, a
database or a phone: the drivers do, with what these functions return.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from spatalk.brain.requests import PreferredWindow
from spatalk.brain.resolve import first_name_of, spoken_digits, typed_digits
from spatalk.tenants.schema import TenantConfig

Flow = Literal["new_booking", "callback", "reschedule", "cancel", "question", "clinical"]
NAME_REQUIRED_FLOWS = ("new_booking", "callback", "reschedule", "cancel", "question", "clinical")


class Step(str, Enum):
    QA = "qa"
    RETURNING = "returning"
    OFFERS = "offers"
    PRACTITIONER = "practitioner"
    SERVICE = "service"
    NAME = "name"
    PHONE = "phone"
    WINDOW = "window"
    TEAM_NOTE = "team_note"
    ROUTE = "route"
    COMPLETE = "complete"


class Pending(BaseModel, frozen=True):
    """A confirmation the caller owes an answer to before the slot can be filled."""

    kind: Literal["match", "which", "name_staff", "phone", "not_service", "offers", "route"]
    slot: str
    value: str | None = None
    candidates: tuple[str, ...] = ()


class Slots(BaseModel, frozen=True):
    flow: Flow | None = None
    returning_client: bool | None = None
    offers_done: bool = False
    practitioner: str | None = None
    service_id: str | None = None
    first_name: str | None = None
    phone: str | None = None
    phone_confirmed: bool = False
    preferred_window: PreferredWindow | None = None
    team_note_asked: bool = False
    pending: Pending | None = None
    misses: dict[str, int] = Field(default_factory=dict)
    ended_flow: bool = False

    def with_(self, **changes) -> "Slots":
        return self.model_copy(update=changes)

    def miss(self, slot: str) -> "Slots":
        misses = dict(self.misses)
        misses[slot] = misses.get(slot, 0) + 1
        return self.with_(misses=misses)


BOOKING_LIKE = ("new_booking", "callback")


def _phone_needed(slots: Slots, channel: str) -> bool:
    if channel == "sms":
        return False
    return not (slots.phone and slots.phone_confirmed)


def next_step(slots: Slots, cfg: TenantConfig, channel: str) -> Step:
    if slots.flow is None or slots.ended_flow:
        return Step.QA
    if slots.flow in BOOKING_LIKE:
        if slots.returning_client is None:
            return Step.RETURNING
        if slots.returning_client is False and not slots.offers_done:
            return Step.OFFERS
        if slots.returning_client:
            if slots.practitioner is None:
                return Step.PRACTITIONER
            if slots.service_id is None:
                return Step.SERVICE
        else:
            if slots.service_id is None:
                return Step.SERVICE
            if slots.practitioner is None:
                return Step.PRACTITIONER
    if not slots.first_name:
        return Step.NAME
    if _phone_needed(slots, channel):
        return Step.PHONE
    if slots.flow in ("new_booking", "callback", "reschedule") and slots.preferred_window is None:
        return Step.WINDOW
    if slots.flow in BOOKING_LIKE and not slots.team_note_asked:
        return Step.TEAM_NOTE
    if slots.flow == "new_booking" and cfg.sms_from_number and channel == "voice":
        return Step.ROUTE
    return Step.COMPLETE


def _consultation_name(cfg: TenantConfig) -> str:
    consult = next((s for s in cfg.services if s.category == "consultation"), None)
    return f"a {consult.name.lower()}" if consult else "the team can help you pick when they call"


def _short_name(full: str) -> str:
    """'Helen' for one Helen on the team; 'Amanda C.' when two share a first name."""
    return first_name_of(full)


def step_question(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> tuple[str, dict] | None:
    p = slots.pending
    if p is not None:
        if p.kind == "match":
            label = _short_name(p.value) if p.slot == "practitioner" else _service_name(cfg, p.value)
            return "confirm_match", {"value": label}
        if p.kind == "which":
            a, b = p.candidates[:2]
            if p.slot == "practitioner":
                a, b = _initialled(a, b)
            else:
                a, b = _service_name(cfg, a), _service_name(cfg, b)
            return "confirm_which", {"first": a, "second": b}
        if p.kind == "name_staff":
            return "confirm_name_staff", {"name": p.value}
        if p.kind == "phone":
            digits = spoken_digits(p.value) if channel == "voice" else typed_digits(p.value)
            return "confirm_phone", {"digits": digits}
        if p.kind == "not_service":
            return "practitioner_not_service", {
                "practitioner": _short_name(p.value),
                "service": _service_name(cfg, slots.service_id or ""),
            }
        if p.kind == "offers":
            return "ask_service_kind", {"consultation": _consultation_name(cfg)}
        if p.kind == "route":
            return "ask_route", {}
    if step == Step.RETURNING:
        return "ask_returning", {}
    if step == Step.OFFERS:
        return "ask_offers", {}
    if step == Step.PRACTITIONER:
        return ("ask_practitioner_again" if slots.misses.get("practitioner") else "ask_practitioner"), {}
    if step == Step.SERVICE:
        return ("ask_service_again" if slots.misses.get("service") else "ask_service"), {}
    if step == Step.NAME:
        return ("ask_name_again" if slots.misses.get("name") else "ask_name"), {}
    if step == Step.PHONE:
        return ("ask_phone_same" if channel == "voice" and not slots.misses.get("phone") else "ask_phone"), {}
    if step == Step.WINDOW:
        return "ask_window", {}
    if step == Step.TEAM_NOTE:
        return "ask_team_note", {}
    if step == Step.ROUTE:
        return "ask_route", {}
    return None


def _service_name(cfg: TenantConfig, service_id: str) -> str:
    s = cfg.service(service_id)
    return s.name if s else service_id


def _initialled(a: str, b: str) -> tuple[str, str]:
    fa, fb = first_name_of(a), first_name_of(b)
    if fa.lower() != fb.lower():
        return fa, fb
    return f"{fa} {a.split()[-1][0]}.", f"{fb} {b.split()[-1][0]}."
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_flow_order.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spatalk/brain/flow.py tests/test_flow_order.py
git commit -m "feat(brain): the slot record, the fixed step order and the question for each step"
```

---

### Task 4: The closed tools and `step_tools`

**Files:**
- Modify: `spatalk/brain/tools.py` (rewrite `build_tools`; keep `WINDOW`, `TRANSFER_TOOL`, `tools_schema`, `to_genai_declarations`)
- Modify: `spatalk/brain/flow.py` (add `step_tools`)
- Test: `tests/test_tools_prompt.py` (update), `tests/test_structural_honesty.py` (extend), `tests/test_flow_tools.py` (new)

**Interfaces:**
- Produces:
  - `tools.py`: `TOOL_NAMES = ("start_request","answer","choose_practitioner","choose_service","give_name","give_phone","choose_window","change_answer","file_request","send_link","escalate","end_conversation")`; `slot_tool(name: str, cfg: TenantConfig) -> FunctionSchema`; `always_tools(cfg, transfer_enabled) -> list[FunctionSchema]` (`escalate`, `end_conversation`, `transfer_to_human` when enabled); `build_tools(cfg, transfer_enabled=False)` now returns `always_tools` plus `start_request` (the `QA` set) so existing callers keep working until Tasks 8 and 10 switch them.
  - `flow.py`: `step_tools(step: Step, slots: Slots, cfg: TenantConfig, channel: str, transfer_enabled: bool = False) -> list[FunctionSchema]`.
- Consumes: `Step`, `Slots` (Task 3).

- [ ] **Step 1: Write the failing tests**

`tests/test_flow_tools.py`:

```python
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def _names(tools):
    return [t.name for t in tools]


def test_qa_offers_start_request_and_nothing_that_files():
    from spatalk.brain.flow import Slots, Step, step_tools
    names = _names(step_tools(Step.QA, Slots(), _cfg(), "voice"))
    assert "start_request" in names and "escalate" in names and "end_conversation" in names
    assert "file_request" not in names and "send_link" not in names and "give_name" not in names


def test_each_step_offers_exactly_its_slot_tool():
    from spatalk.brain.flow import Slots, Step, step_tools
    cfg = _cfg()
    s = Slots(flow="new_booking")
    expect = {
        Step.RETURNING: "answer", Step.OFFERS: "answer", Step.PRACTITIONER: "choose_practitioner",
        Step.SERVICE: "choose_service", Step.NAME: "give_name", Step.PHONE: "answer",
        Step.WINDOW: "choose_window", Step.TEAM_NOTE: "answer", Step.ROUTE: "answer",
    }
    for step, tool in expect.items():
        names = _names(step_tools(step, s, cfg, "voice"))
        assert tool in names, (step, names)
        assert "file_request" not in names or step == Step.ROUTE
        assert "change_answer" in names


def test_phone_step_offers_give_phone_once_the_caller_said_no():
    from spatalk.brain.flow import Slots, Step, step_tools
    s = Slots(flow="callback", first_name="Dana").miss("phone")
    assert "give_phone" in _names(step_tools(Step.PHONE, s, _cfg(), "voice"))
    assert "give_phone" in _names(step_tools(Step.PHONE, Slots(flow="callback", first_name="Dana"), _cfg(), "chat"))


def test_complete_offers_file_request_and_route_offers_send_link_only_with_sms():
    from spatalk.brain.flow import Slots, Step, step_tools
    cfg = _cfg()
    assert "file_request" in _names(step_tools(Step.COMPLETE, Slots(flow="callback"), cfg, "voice"))
    route = _names(step_tools(Step.ROUTE, Slots(flow="new_booking", phone="+1", phone_confirmed=True), cfg, "voice"))
    assert "send_link" in route and "file_request" in route
    no_sms = cfg.model_copy(update={"sms_from_number": None})
    assert "send_link" not in _names(step_tools(Step.ROUTE, Slots(flow="new_booking"), no_sms, "voice"))


def test_no_tool_carries_contact_lead_or_free_text_beyond_the_three_transients():
    from spatalk.brain.flow import Slots, Step, step_tools
    cfg = _cfg()
    allowed_free = {("give_name", "first_name"), ("give_phone", "digits"),
                    ("choose_practitioner", "said"), ("choose_service", "said")}
    for step in Step:
        for tool in step_tools(step, Slots(flow="new_booking"), cfg, "voice"):
            for prop, schema in tool.properties.items():
                assert prop not in ("contact", "notes", "returning_client", "concern"), (tool.name, prop)
                if schema.get("type") == "string" and "enum" not in schema:
                    assert (tool.name, prop) in allowed_free, (tool.name, prop)
```

Update `tests/test_structural_honesty.py::test_no_tool_schema_has_a_notes_parameter` to iterate `step_tools` over every `Step` instead of `build_tools` (keep its assertion), and add:

```python
def test_file_request_takes_no_arguments():
    from spatalk.brain.flow import Slots, Step, step_tools
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    tool = next(t for t in step_tools(Step.COMPLETE, Slots(flow="callback"), cfg, "voice") if t.name == "file_request")
    assert tool.properties == {} and tool.required == []
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_flow_tools.py tests/test_structural_honesty.py`
Expected: FAIL — `step_tools` undefined.

- [ ] **Step 3: Rewrite `tools.py`**

Replace `_lead_context`, `_contact` and the body of `build_tools` with:

```python
TOOL_NAMES = (
    "start_request", "answer", "choose_practitioner", "choose_service", "give_name",
    "give_phone", "choose_window", "change_answer", "file_request", "send_link",
    "escalate", "end_conversation",
)

ONLY_WHAT_THEY_SAID = " Only what the caller said in answer to the question just asked; never a guess."

SLOT_NAMES = ["returning_client", "practitioner", "service", "name", "phone", "window"]


def slot_tool(name: str, cfg: TenantConfig) -> FunctionSchema:
    if name == "start_request":
        return FunctionSchema(
            name="start_request",
            description=(
                "The caller wants something the team has to do: book, be called back, "
                "reschedule or cancel, or a question the facts do not answer. Call this the "
                "moment they say so; the system asks the questions from here."
            ),
            properties={"kind": {"type": "string", "enum": ["new_booking", "callback", "reschedule", "cancel", "question"]}},
            required=["kind"],
        )
    if name == "answer":
        return FunctionSchema(
            name="answer",
            description="The caller's yes or no to the question just asked." + ONLY_WHAT_THEY_SAID,
            properties={"value": {"type": "string", "enum": ["yes", "no", "unsure"]}},
            required=["value"],
        )
    if name == "choose_practitioner":
        return FunctionSchema(
            name="choose_practitioner",
            description="Who the caller said they would like to see, in their words, or 'anyone'." + ONLY_WHAT_THEY_SAID,
            properties={"said": {"type": "string"}},
            required=["said"],
        )
    if name == "choose_service":
        return FunctionSchema(
            name="choose_service",
            description="The treatment the caller named, in their words." + ONLY_WHAT_THEY_SAID,
            properties={"said": {"type": "string"}},
            required=["said"],
        )
    if name == "give_name":
        return FunctionSchema(
            name="give_name",
            description="The caller's first name, as they gave it." + ONLY_WHAT_THEY_SAID,
            properties={"first_name": {"type": "string"}},
            required=["first_name"],
        )
    if name == "give_phone":
        return FunctionSchema(
            name="give_phone",
            description="The phone number the caller gave, as digits." + ONLY_WHAT_THEY_SAID,
            properties={"digits": {"type": "string"}},
            required=["digits"],
        )
    if name == "choose_window":
        return FunctionSchema(
            name="choose_window",
            description="When the caller would like to come in." + ONLY_WHAT_THEY_SAID,
            properties=dict(WINDOW["properties"]),
            required=[],
        )
    if name == "change_answer":
        return FunctionSchema(
            name="change_answer",
            description="The caller changed their mind about an earlier answer. The system asks that question again.",
            properties={"slot": {"type": "string", "enum": SLOT_NAMES}},
            required=["slot"],
        )
    if name == "file_request":
        return FunctionSchema(
            name="file_request",
            description="Send the request to the team. Say nothing about it yourself; the system speaks the result.",
            properties={},
            required=[],
        )
    if name == "send_link":
        return FunctionSchema(
            name="send_link",
            description="Text the caller the booking link now. Say nothing about it yourself; the system speaks the result.",
            properties={},
            required=[],
        )
    raise ValueError(name)


def always_tools(cfg: TenantConfig, transfer_enabled: bool = False) -> list[FunctionSchema]:
    tools = [
        FunctionSchema(
            name="escalate",
            description=(... the existing escalate description, unchanged ...),
            properties={"reason": {"type": "string", "enum": ["emergency", "human_request", "clinical", "complaint", "payment", "legal", "unsure"]}},
            required=["reason"],
        ),
        FunctionSchema(
            name="end_conversation",
            description="End the call once the caller has nothing else. Say nothing yourself; the system says goodbye.",
            properties={},
            required=[],
        ),
    ]
    if transfer_enabled:
        tools.append(FunctionSchema(name=TRANSFER_TOOL, description=(... unchanged ...), properties={}, required=[]))
    return tools


def build_tools(cfg: TenantConfig, transfer_enabled: bool = False) -> list[FunctionSchema]:
    """The Q&A tool set. The per-step sets are `spatalk.brain.flow.step_tools`."""
    return [slot_tool("start_request", cfg)] + always_tools(cfg, transfer_enabled)
```

(Copy the two long descriptions verbatim from the current file where the code says "unchanged".)

- [ ] **Step 4: Add `step_tools` to `flow.py`**

```python
from spatalk.brain.tools import always_tools, slot_tool

STEP_TOOL = {
    Step.RETURNING: "answer", Step.OFFERS: "answer", Step.PRACTITIONER: "choose_practitioner",
    Step.SERVICE: "choose_service", Step.NAME: "give_name", Step.WINDOW: "choose_window",
    Step.TEAM_NOTE: "answer", Step.ROUTE: "answer",
}


def step_tools(step: Step, slots: Slots, cfg: TenantConfig, channel: str, transfer_enabled: bool = False) -> list[FunctionSchema]:
    tools: list[FunctionSchema] = []
    if step == Step.QA:
        tools.append(slot_tool("start_request", cfg))
    elif step == Step.PHONE:
        asked_same = channel == "voice" and not slots.misses.get("phone") and slots.pending is None
        tools.append(slot_tool("answer" if asked_same else "give_phone", cfg))
        if slots.pending is not None and slots.pending.kind == "phone":
            tools[-1] = slot_tool("answer", cfg)
    elif step == Step.COMPLETE:
        tools.append(slot_tool("file_request", cfg))
    else:
        tools.append(slot_tool(STEP_TOOL[step], cfg))
        if slots.pending is not None and STEP_TOOL[step] != "answer":
            tools.append(slot_tool("answer", cfg))
        if step == Step.NAME and slots.flow == "clinical" and not slots.misses.get("name"):
            tools.append(slot_tool("answer", cfg))   # the clinical offer is answered yes/no first
        if step == Step.ROUTE:
            tools.append(slot_tool("file_request", cfg))
            if cfg.sms_from_number and slots.phone and slots.phone_confirmed:
                tools.append(slot_tool("send_link", cfg))
    if step != Step.QA:
        tools.append(slot_tool("change_answer", cfg))
    return tools + always_tools(cfg, transfer_enabled)
```

Add `from pipecat.adapters.schemas.function_schema import FunctionSchema` at the top of `flow.py`.

- [ ] **Step 5: Update `tests/test_tools_prompt.py`**

Any test there that asserts `capture_request`/`send_booking_link` shapes now asserts the new names: `build_tools(cfg)` names are `["start_request", "escalate", "end_conversation"]` (plus `transfer_to_human` when enabled). Keep every assertion about "no notes parameter".

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q tests/test_flow_tools.py tests/test_structural_honesty.py tests/test_tools_prompt.py`
Expected: PASS. (`tests/test_driver.py` and `tests/test_tier_c.py` fail from here until Task 7 — expected; do not run the full suite yet.)

- [ ] **Step 7: Commit**

```bash
git add spatalk/brain/tools.py spatalk/brain/flow.py tests/test_flow_tools.py tests/test_structural_honesty.py tests/test_tools_prompt.py
git commit -m "feat(brain): closed slot tools, one per step; file_request takes no arguments"
```

---

### Task 5: `apply` — what a tool call does to the record

**Files:**
- Modify: `spatalk/brain/flow.py`
- Test: `tests/test_flow_apply.py`

**Interfaces:**
- Produces:
  - `class Applied(BaseModel, frozen=True): slots: Slots; say: tuple[tuple[str, dict], ...]; file: bool = False; send_link: bool = False; end: bool = False; ignored: bool = False`
  - `apply(slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None) -> Applied`
- Consumes: `Slots`, `Pending`, `Step`, `next_step` (Task 3); resolvers (Task 2); `cfg.member_does`, `cfg.team_for_service` (Task 1).

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def _apply(slots, name, args, channel="voice", caller="+19055550101"):
    from spatalk.brain.flow import apply
    return apply(slots, name, args, _cfg(), channel, caller)


def test_start_request_opens_a_flow_and_returning_yes_no_are_stored():
    from spatalk.brain.flow import Slots
    a = _apply(Slots(), "start_request", {"kind": "new_booking"})
    assert a.slots.flow == "new_booking" and a.say == ()
    b = _apply(a.slots, "answer", {"value": "yes"})
    assert b.slots.returning_client is True
    c = _apply(a.slots, "answer", {"value": "unsure"})
    assert c.slots.returning_client is False


def test_an_answer_lands_only_in_the_open_slot():
    from spatalk.brain.flow import Slots
    s = Slots(flow="new_booking", returning_client=True)   # open step: PRACTITIONER
    a = _apply(s, "give_name", {"first_name": "Ellen"})     # not this step's tool
    assert a.ignored and a.slots == s and a.slots.first_name is None


def test_close_practitioner_match_asks_did_you_mean_and_yes_stores_it():
    from spatalk.brain.flow import Slots
    s = Slots(flow="new_booking", returning_client=True)
    a = _apply(s, "choose_practitioner", {"said": "Ellen"})
    assert a.slots.pending is not None and a.slots.pending.kind == "match"
    assert a.slots.practitioner is None
    b = _apply(a.slots, "answer", {"value": "yes"})
    assert b.slots.practitioner == "Helen Courbetis" and b.slots.pending is None
    c = _apply(a.slots, "answer", {"value": "no"})
    assert c.slots.practitioner is None and c.slots.misses["practitioner"] == 1


def test_two_practitioner_misses_settle_on_any():
    from spatalk.brain.flow import Slots
    s = Slots(flow="new_booking", returning_client=True)
    a = _apply(s, "choose_practitioner", {"said": "xqzv"})
    assert a.slots.misses["practitioner"] == 1 and a.slots.practitioner is None
    b = _apply(a.slots, "choose_practitioner", {"said": "blorp"})
    assert b.slots.practitioner == "any" and ("practitioner_any", {}) in b.say


def test_practitioner_who_does_not_do_the_service():
    from spatalk.brain.flow import Slots
    cfg = _cfg()
    nurse = next(m for m in cfg.team if m.services and "hydrabrasion_facial" not in m.services)
    s = Slots(flow="new_booking", returning_client=False, offers_done=True, service_id="hydrabrasion_facial")
    a = _apply(s, "choose_practitioner", {"said": nurse.name})
    assert a.slots.pending.kind == "not_service" and a.slots.practitioner is None
    yes = _apply(a.slots, "answer", {"value": "yes"})
    assert yes.say[0][0] == "practitioner_suggest" and yes.slots.pending is None
    no = _apply(a.slots, "answer", {"value": "no"})
    assert no.say[0][0] == "practitioner_else"


def test_a_kind_of_treatment_offers_options_or_the_consultation():
    from spatalk.brain.flow import Slots
    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = _apply(s, "choose_service", {"said": "a facial"})
    assert a.slots.pending.kind == "offers" and a.slots.service_id is None


def test_name_sanity_against_the_practitioner_and_refusing_a_name():
    from spatalk.brain.flow import Slots
    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis", service_id="hydrabrasion_facial")
    a = _apply(s, "give_name", {"first_name": "Helen"})
    assert a.slots.pending.kind == "name_staff"
    assert _apply(a.slots, "answer", {"value": "yes"}).slots.first_name == "Helen"
    r1 = _apply(s, "give_name", {"first_name": ""})
    assert r1.slots.misses["name"] == 1 and r1.slots.first_name is None
    r2 = _apply(r1.slots, "give_name", {"first_name": ""})
    assert r2.say[0][0] == "no_name" and r2.slots.ended_flow and not r2.file


def test_phone_on_a_call_is_the_caller_id_unless_they_say_otherwise():
    from spatalk.brain.flow import Slots
    s = Slots(flow="callback", first_name="Dana")
    yes = _apply(s, "answer", {"value": "yes"})
    assert yes.slots.phone == "+19055550101" and yes.slots.phone_confirmed
    no = _apply(s, "answer", {"value": "no"})
    assert no.slots.misses["phone"] == 1
    given = _apply(no.slots, "give_phone", {"digits": "416 555 0199"})
    assert given.slots.pending.kind == "phone" and given.slots.pending.value == "+14165550199"
    ok = _apply(given.slots, "answer", {"value": "yes"})
    assert ok.slots.phone == "+14165550199" and ok.slots.phone_confirmed
    bad = _apply(no.slots, "give_phone", {"digits": "555"})
    assert bad.slots.misses["phone"] == 2 and ("phone_fallback", {}) in bad.say and bad.slots.phone == "+19055550101"


def test_sms_takes_the_sender_number_without_asking():
    from spatalk.brain.flow import Slots, Step, next_step
    s = Slots(flow="callback", first_name="Dana")
    assert next_step(s, _cfg(), "sms") == Step.WINDOW
    a = _apply(s, "choose_window", {"date": "Thursday", "part_of_day": "morning"}, channel="sms")
    assert a.slots.preferred_window.date == "Thursday"


def test_complete_files_and_route_sends_the_link():
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    done = Slots(flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
                 first_name="Dana", phone="+19055550101", phone_confirmed=True,
                 preferred_window=PreferredWindow(), team_note_asked=True)
    a = _apply(done, "file_request", {})
    assert a.file and a.slots.ended_flow
    booking = done.with_(flow="new_booking")
    link = _apply(booking, "answer", {"value": "yes"})           # ROUTE: yes = the link
    assert link.send_link and link.slots.ended_flow
    call = _apply(booking, "answer", {"value": "no"})            # ROUTE: no = the team calls
    assert call.file and call.slots.ended_flow
    early = _apply(Slots(flow="callback"), "file_request", {})
    assert early.ignored and not early.file


def test_the_record_files_itself_when_the_last_slot_lands():
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    s = Slots(flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
              first_name="Dana", phone="+19055550101", phone_confirmed=True, preferred_window=PreferredWindow())
    a = _apply(s, "answer", {"value": "no"})            # TEAM_NOTE answered: nothing left to ask
    assert a.file and a.slots.ended_flow
    sms = _apply(Slots(flow="question", phone="+14165550199", phone_confirmed=True), "give_name", {"first_name": "Dana"}, channel="sms")
    assert sms.file                                     # sms: the sender's number, nothing else to ask
    partial = _apply(Slots(flow="callback"), "answer", {"value": "yes"})   # RETURNING answered
    assert not partial.file


def test_a_second_request_keeps_the_name_and_number_but_not_the_treatment():
    from spatalk.brain.flow import Slots
    done = Slots(flow=None, returning_client=True, first_name="Dana", phone="+1", phone_confirmed=True,
                 service_id="hydrabrasion_facial", practitioner="Helen Courbetis")
    a = _apply(done, "start_request", {"kind": "callback"})
    assert a.slots.first_name == "Dana" and a.slots.phone_confirmed and a.slots.returning_client is True
    assert a.slots.service_id is None and a.slots.practitioner is None


def test_change_answer_reopens_a_step():
    from spatalk.brain.flow import Slots, Step, next_step
    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis", service_id="hydrabrasion_facial", first_name="Dana")
    a = _apply(s, "change_answer", {"slot": "service"})
    assert a.slots.service_id is None and next_step(a.slots, _cfg(), "voice") == Step.SERVICE
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_flow_apply.py`
Expected: FAIL — `apply` undefined.

- [ ] **Step 3: Implement `apply`**

Append to `flow.py`:

```python
from spatalk.brain.resolve import match_practitioner, match_service, normalise_phone, sounds_like


class Applied(BaseModel, frozen=True):
    slots: Slots
    say: tuple[tuple[str, dict], ...] = ()
    file: bool = False
    send_link: bool = False
    end: bool = False
    ignored: bool = False


def _tool_allowed(name: str, step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> bool:
    return name in {t.name for t in step_tools(step, slots, cfg, channel, transfer_enabled=True)}


def apply(slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None) -> Applied:
    return _finalize(_apply(slots, name, args, cfg, channel, caller_phone), cfg, channel)


def _apply(slots: Slots, name: str, args: dict, cfg: TenantConfig, channel: str, caller_phone: str | None) -> Applied:
    step = next_step(slots, cfg, channel)
    if name in ("escalate", "end_conversation", "transfer_to_human"):
        return Applied(slots=slots, end=(name == "end_conversation"))
    if not _tool_allowed(name, step, slots, cfg, channel):
        return Applied(slots=slots, ignored=True)
    args = args or {}
    if name == "start_request":
        kind = args.get("kind")
        if kind not in ("new_booking", "callback", "reschedule", "cancel", "question"):
            return Applied(slots=slots, ignored=True)
        return Applied(slots=_open(kind, slots, channel, caller_phone))
    if name == "change_answer":
        return Applied(slots=_reopen(slots, args.get("slot", "")))
    if name == "answer":
        return _answer(slots, step, args.get("value", "unsure"), cfg, channel, caller_phone)
    if name == "choose_practitioner":
        return _practitioner(slots, args.get("said", ""), cfg)
    if name == "choose_service":
        return _service(slots, args.get("said", ""), cfg)
    if name == "give_name":
        return _name(slots, args.get("first_name", ""), cfg)
    if name == "give_phone":
        return _phone(slots, args.get("digits", ""), caller_phone, channel)
    if name == "choose_window":
        window = PreferredWindow(date=args.get("date") or "any", part_of_day=args.get("part_of_day") or "any")
        return Applied(slots=slots.with_(preferred_window=window))
    if name == "file_request":
        return Applied(slots=slots.with_(ended_flow=True), file=True)
    if name == "send_link":
        return Applied(slots=slots.with_(ended_flow=True), send_link=True)
    return Applied(slots=slots, ignored=True)


def _open(kind: str, previous: Slots, channel: str, caller_phone: str | None) -> Slots:
    """A new flow keeps what the conversation already knows about the person, never about
    the request: the name and number asked once are not asked twice; a second request
    still gets its own treatment and practitioner."""
    on_sms = channel == "sms" and bool(caller_phone)
    return Slots(
        flow=kind,
        returning_client=previous.returning_client,
        first_name=previous.first_name,
        phone=previous.phone or (caller_phone if on_sms else None),
        phone_confirmed=previous.phone_confirmed or on_sms,
    )


open_flow = _open


def _finalize(applied: Applied, cfg: TenantConfig, channel: str) -> Applied:
    """The record files itself the moment the last required slot lands (the route step of a
    booking on a call with an SMS number is the one question asked before it)."""
    s = applied.slots
    if applied.ignored or applied.file or applied.send_link or applied.end:
        return applied
    if s.flow is None or s.ended_flow or s.pending is not None:
        return applied
    if next_step(s, cfg, channel) == Step.COMPLETE:
        return applied.model_copy(update={"slots": s.with_(ended_flow=True), "file": True})
    return applied


def _reopen(slots: Slots, slot: str) -> Slots:
    clear = {
        "returning_client": {"returning_client": None},
        "practitioner": {"practitioner": None},
        "service": {"service_id": None},
        "name": {"first_name": None},
        "phone": {"phone": None, "phone_confirmed": False},
        "window": {"preferred_window": None},
    }.get(slot)
    if clear is None:
        return slots
    misses = {k: v for k, v in slots.misses.items() if k != slot}
    return slots.with_(pending=None, misses=misses, **clear)


def _answer(slots: Slots, step: Step, value: str, cfg: TenantConfig, channel: str, caller_phone: str | None) -> Applied:
    yes = value == "yes"
    p = slots.pending
    if p is not None:
        if p.kind in ("match", "which"):
            if p.kind == "which":
                return Applied(slots=slots, ignored=True)   # "which" is answered by naming one; see _practitioner/_service
            if yes:
                field = "practitioner" if p.slot == "practitioner" else "service_id"
                return _after_slot(slots.with_(pending=None, **{field: p.value}), cfg)
            return Applied(slots=slots.with_(pending=None).miss(p.slot))
        if p.kind == "name_staff":
            if yes:
                return Applied(slots=slots.with_(pending=None, first_name=p.value))
            return Applied(slots=slots.with_(pending=None).miss("name"))
        if p.kind == "phone":
            if yes:
                return Applied(slots=slots.with_(pending=None, phone=p.value, phone_confirmed=True))
            return _phone_miss(slots.with_(pending=None), caller_phone, channel)
        if p.kind == "not_service":
            if yes:
                names = [first_name_of(m.name) for m in cfg.team_for_service(slots.service_id or "")][:3]
                fills = {"names": _join(names), "service": _service_name(cfg, slots.service_id or "")}
                return Applied(slots=slots.with_(pending=None), say=(("practitioner_suggest", fills),))
            return Applied(slots=slots.with_(pending=None), say=(("practitioner_else", {}),))
        if p.kind == "offers":
            # yes = hear options (the model lists two or three from the facts); no = the consultation
            if yes:
                return Applied(slots=slots.with_(pending=None))
            consult = next((s for s in cfg.services if s.category == "consultation"), None)
            if consult is None:
                return Applied(slots=slots.with_(pending=None))
            return _after_slot(slots.with_(pending=None, service_id=consult.id), cfg)
    if slots.flow == "clinical" and slots.first_name is None and step == Step.NAME:
        # The clinical offer: yes goes on to the name, no closes with nothing filed.
        if yes:
            return Applied(slots=slots)
        return Applied(slots=slots.with_(ended_flow=True), say=(("clinical_declined", {}),))
    if step == Step.RETURNING:
        return Applied(slots=slots.with_(returning_client=yes))
    if step == Step.OFFERS:
        return Applied(slots=slots.with_(offers_done=True), say=(("ask_after_offers", {}),) if yes else ())
    if step == Step.PHONE:
        if yes:
            return Applied(slots=slots.with_(phone=caller_phone, phone_confirmed=bool(caller_phone)))
        return Applied(slots=slots.miss("phone"))
    if step == Step.TEAM_NOTE:
        return Applied(slots=slots.with_(team_note_asked=True))
    if step == Step.ROUTE:
        if yes and cfg.sms_from_number and slots.phone_confirmed:
            return Applied(slots=slots.with_(ended_flow=True), send_link=True)
        return Applied(slots=slots.with_(ended_flow=True), file=True)
    return Applied(slots=slots, ignored=True)


def _after_slot(slots: Slots, cfg: TenantConfig) -> Applied:
    """A practitioner and a service both known: check the pairing."""
    if slots.practitioner and slots.practitioner != "any" and slots.service_id:
        if not cfg.member_does(slots.practitioner, slots.service_id):
            pending = Pending(kind="not_service", slot="practitioner", value=slots.practitioner)
            return Applied(slots=slots.with_(practitioner=None, pending=pending))
    return Applied(slots=slots)


def _practitioner(slots: Slots, said: str, cfg: TenantConfig) -> Applied:
    m = match_practitioner(said, cfg)
    if m.kind == "exact":
        return _after_slot(slots.with_(pending=None, practitioner=m.value), cfg)
    if m.kind == "confirm":
        return Applied(slots=slots.with_(pending=Pending(kind="match", slot="practitioner", value=m.value)))
    if m.kind == "which":
        return Applied(slots=slots.with_(pending=Pending(kind="which", slot="practitioner", candidates=m.candidates)))
    missed = slots.with_(pending=None).miss("practitioner")
    if missed.misses["practitioner"] >= 2:
        return Applied(slots=missed.with_(practitioner="any"), say=(("practitioner_any", {}),))
    return Applied(slots=missed)


def _service(slots: Slots, said: str, cfg: TenantConfig) -> Applied:
    m = match_service(said, cfg)
    if m.kind == "exact":
        return _after_slot(slots.with_(pending=None, service_id=m.value), cfg)
    if m.kind == "confirm":
        return Applied(slots=slots.with_(pending=Pending(kind="match", slot="service", value=m.value)))
    if m.kind == "which":
        return Applied(slots=slots.with_(pending=Pending(kind="which", slot="service", candidates=m.candidates)))
    if m.kind == "kind":
        return Applied(slots=slots.with_(pending=Pending(kind="offers", slot="service_kind", value=m.value)))
    missed = slots.with_(pending=None).miss("service")
    if missed.misses["service"] >= 2:
        return Applied(slots=missed.with_(pending=Pending(kind="offers", slot="service_kind")))
    return Applied(slots=missed)


def _name(slots: Slots, first_name: str, cfg: TenantConfig) -> Applied:
    name = " ".join((first_name or "").split())[:80]
    if not name or not any(ch.isalpha() for ch in name):
        missed = slots.miss("name")
        if missed.misses["name"] >= 2:
            return Applied(slots=missed.with_(ended_flow=True), say=(("no_name", {}),))
        return Applied(slots=missed)
    name = name.split()[0].capitalize()
    if slots.practitioner and slots.practitioner != "any" and sounds_like(name, first_name_of(slots.practitioner)):
        return Applied(slots=slots.with_(pending=Pending(kind="name_staff", slot="name", value=name)))
    return Applied(slots=slots.with_(first_name=name, pending=None))


def _phone(slots: Slots, digits: str, caller_phone: str | None, channel: str) -> Applied:
    e164 = normalise_phone(digits)
    if e164 is None:
        return _phone_miss(slots, caller_phone, channel)
    return Applied(slots=slots.with_(pending=Pending(kind="phone", slot="phone", value=e164)))


def _phone_miss(slots: Slots, caller_phone: str | None, channel: str) -> Applied:
    missed = slots.miss("phone")
    if missed.misses["phone"] >= 2 and channel == "voice" and caller_phone:
        return Applied(slots=missed.with_(phone=caller_phone, phone_confirmed=True), say=(("phone_fallback", {}),))
    return Applied(slots=missed)


def _join(names: list[str]) -> str:
    if not names:
        return "Someone on the team"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]
```

A "which" confirmation is answered by the caller naming one of the two, so the same slot tool stays offered (Task 4 offers `answer` too; `_answer` ignores it for "which", and `_practitioner`/`_service` with the chosen name resolve it — an exact first-name match against two candidates falls to `_best`, which returns `which` again only when both still tie; a surname settles it).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spatalk/brain/flow.py tests/test_flow_apply.py
git commit -m "feat(brain): apply() moves the slot record on every tool call; answers land only in the open slot"
```

---

### Task 6: `draft_from`, `step_message`, and the prompt shrink

**Files:**
- Modify: `spatalk/brain/flow.py`, `spatalk/brain/prompt.py`
- Test: `tests/test_flow_draft.py` (new), `tests/test_prompt_booking_flow.py` (update), `tests/test_structural_honesty.py` (extend)

**Interfaces:**
- Produces: `draft_from(slots: Slots, cfg: TenantConfig, urgent: bool = False, health_context: bool = False) -> ItemDraft`; `step_message(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> str`; `STEP_MARKER = "[step]"` (the message starts with it so adapters can find and replace it).
- Consumes: `ItemDraft` (`spatalk/brain/ports.py`), `ContactInfo`.

- [ ] **Step 1: Write the failing tests**

`tests/test_flow_draft.py`:

```python
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_draft_carries_only_list_values_and_the_slots_contact():
    from spatalk.brain.flow import Slots, draft_from
    from spatalk.brain.requests import PreferredWindow
    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis",
              service_id="hydrabrasion_facial", first_name="Dana", phone="+14165550199",
              phone_confirmed=True, preferred_window=PreferredWindow(date="Thursday"))
    d = draft_from(s, _cfg())
    assert d.type == "new_booking" and d.urgency == "normal"
    assert d.contact.name == "Dana" and d.contact.phone == "+14165550199" and d.contact.email is None
    assert d.practitioner == "Helen Courbetis" and d.returning_client is True
    assert d.preferred_window.date == "Thursday" and d.service_id == "hydrabrasion_facial"
    c = draft_from(Slots(flow="clinical", first_name="Dana", phone="+1", phone_confirmed=True), _cfg(), urgent=True)
    assert c.type == "escalation_clinical" and c.urgency == "urgent"


def test_step_message_names_what_is_known_and_the_tool_to_use():
    from spatalk.brain.flow import STEP_MARKER, Slots, Step, step_message
    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis")
    m = step_message(Step.SERVICE, s, _cfg(), "voice")
    assert m.startswith(STEP_MARKER) and "choose_service" in m and "Helen" in m
    assert len(m.split(". ")) <= 4
    assert "ask" not in step_message(Step.QA, Slots(), _cfg(), "voice").lower().split("start_request")[0][-20:]
```

In `tests/test_prompt_booking_flow.py`, replace the booking-order tests with:

```python
def test_the_static_prompt_no_longer_carries_the_booking_order():
    from spatalk.brain.prompt import build_system_prompt
    for channel in ("voice", "sms", "chat"):
        p = build_system_prompt(_cfg(), channel, NOW).lower()
        assert "when they want to book" not in p
        assert "ask for their first name" not in p
        assert "new-client offers" not in p
        assert "the system asks the questions" in p
```

Keep `test_the_offer_wording_stays_out_of_the_prompt` and `test_a_new_caller_is_asked_before_the_offers_are_recited` only if they still assert on the facts section; delete the assertions on prompt bullets that no longer exist.

Add to `tests/test_structural_honesty.py`:

```python
def test_item_drafts_in_the_request_path_come_only_from_draft_from():
    import ast, pathlib
    src = pathlib.Path("spatalk/brain/driver.py").read_text(encoding="utf-8")
    assert "ItemDraft(" not in src
    src = pathlib.Path("spatalk/voice/handlers.py").read_text(encoding="utf-8")
    assert "ItemDraft(" not in src
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_flow_draft.py tests/test_prompt_booking_flow.py`
Expected: FAIL.

- [ ] **Step 3: Implement `draft_from` and `step_message`**

Append to `flow.py`:

```python
from spatalk.brain.ports import ItemDraft
from spatalk.brain.requests import ContactInfo

STEP_MARKER = "[step]"

ITEM_TYPE = {
    "new_booking": "new_booking", "callback": "callback", "reschedule": "reschedule",
    "cancel": "cancel", "question": "question", "clinical": "escalation_clinical",
}


def draft_from(slots: Slots, cfg: TenantConfig, urgent: bool = False, health_context: bool = False) -> ItemDraft:
    return ItemDraft(
        type=ITEM_TYPE[slots.flow or "question"],
        urgency="urgent" if urgent or slots.flow == "clinical" else "normal",
        service_id=slots.service_id,
        contact=ContactInfo(name=slots.first_name, phone=slots.phone),
        preferred_window=slots.preferred_window or PreferredWindow(),
        health_context=health_context,
        returning_client=slots.returning_client,
        practitioner=slots.practitioner,
        concern=None,
    )


def step_message(step: Step, slots: Slots, cfg: TenantConfig, channel: str) -> str:
    if step == Step.QA:
        return (
            f"{STEP_MARKER} No request is open. Answer questions from the facts. The moment the "
            "caller wants to book, be called back, reschedule, cancel, or asks something the "
            "facts do not answer, call start_request; the system asks the questions from there."
        )
    known = []
    if slots.returning_client is not None:
        known.append("returning client" if slots.returning_client else "new client")
    if slots.practitioner:
        known.append("wants to see " + (slots.practitioner if slots.practitioner != "any" else "anyone"))
    if slots.service_id:
        known.append("treatment " + _service_name(cfg, slots.service_id))
    if slots.first_name:
        known.append("first name " + slots.first_name)
    known_text = ("Known: " + ", ".join(known) + ". ") if known else ""
    tool = {t.name for t in step_tools(step, slots, cfg, channel)}
    slot_tool_name = next((n for n in ("answer", "choose_practitioner", "choose_service", "give_name", "give_phone", "choose_window", "file_request") if n in tool), "answer")
    if step == Step.COMPLETE:
        return f"{STEP_MARKER} {known_text}Everything is collected. Call file_request now. Say nothing about the result."
    if slots.pending is not None and slots.pending.kind == "offers":
        return (
            f"{STEP_MARKER} {known_text}The caller named a kind of treatment. The system just offered two or "
            "three options or a consultation. If they want options, name two or three from the facts "
            "with prices in one breath and then wait; when they choose one, call choose_service."
        )
    return (
        f"{STEP_MARKER} {known_text}The system has just asked the caller a question. Put their answer in "
        f"{slot_tool_name}. Do not ask a question yourself; one short acknowledgement at most."
    )
```

- [ ] **Step 4: Shrink the prompt**

In `prompt.py` `build_system_prompt`, delete the "WHEN THEY WANT TO BOOK" block and the bullets that begin "If they say they want to book", "When they describe a concern", "When they name a kind of treatment", "Once they have chosen", "When the team is going to call them back", "Ask once whether there is anything", "On the tool call, fill", "With the name and number in hand", "Never file a booking", and the general bullet "Ask for the caller's name and best number in one question when you need them". Delete the `name_ask` block. Add one bullet in the general rules:

`- A request for the team (a booking, a callback, a change, a question the facts do not answer) is handled by the system: call start_request and the system asks the questions. Never ask for a name or a number yourself.`

Keep every other bullet (tone, prices aloud, "how's it going", the booking-link rule, "use the name once", "never list more than three options").

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q tests/test_flow_draft.py tests/test_prompt_booking_flow.py tests/test_structural_honesty.py tests/test_tools_prompt.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add spatalk/brain/flow.py spatalk/brain/prompt.py tests/test_flow_draft.py tests/test_prompt_booking_flow.py tests/test_structural_honesty.py
git commit -m "feat(brain): the item draft comes from the slot record; the static prompt hands the booking flow to the system"
```

---

### Task 7: `Brain.turn` on the engine (text driver)

**Files:**
- Modify: `spatalk/brain/driver.py` (`dispatch_tool`, `TurnResult`, `Brain.turn`), `spatalk/brain/tier_c.py`, `spatalk/brain/capabilities.py`, `spatalk/brain/requests.py`
- Test: `tests/test_driver.py` (rewrite the tool tests), `tests/test_tier_c.py` (update), `tests/test_driver_flow.py` (new)

**Interfaces:**
- Produces:
  - `Capabilities.capture(self, ref: ConversationRef, draft: ItemDraft) -> Outcome` (was `CaptureRequest`); `request_appointment_change` removed; `send_booking_link(ref, req: BookingLinkRequest)` unchanged; `escalate` unchanged.
  - `TurnResult.slots: Slots` (new field, default `Slots()`), `TurnResult.said: list[str]` (the fixed lines spoken this turn, for tests).
  - `Brain.turn(self, ref, history, user_text, slots: Slots | None = None) -> TurnResult`.
  - `run_tool(caps, ref, slots, name, args, now) -> tuple[Slots, list[str], Outcome | None, bool]` replaces `dispatch_tool` (returns new slots, spoken lines, outcome, ended).
- Consumes: everything from Tasks 3–6.

- [ ] **Step 1: Write the failing tests**

`tests/test_driver_flow.py`:

```python
import uuid
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _world(fixed_clock, responses, channel="voice", caller="+19055550101"):
    from spatalk.brain.driver import Brain, FakeLLM
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    ledger, sms = MemoryLedger(fixed_clock), MemorySms()
    caps = TierCCapabilities(ledger=ledger, sms=sms, clock=fixed_clock)
    llm = FakeLLM(responses)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel=channel, caller_phone=caller)
    return Brain(llm, caps, fixed_clock), ref, ledger, llm, cfg


def _call(name, **args):
    from spatalk.brain.driver import LLMResponse, ToolCall
    return LLMResponse(text=None, tool_calls=[ToolCall(name, args)])


async def test_a_callback_on_sms_walks_the_order_and_files_with_name_and_number(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.flow import Slots
    responses = [
        _call("start_request", kind="callback"),
        _call("answer", value="yes"),
        _call("choose_practitioner", said="Helen"),
        _call("choose_service", said="hydrabrasion"),
        _call("give_name", first_name="Dana"),
        _call("choose_window", date="Thursday", part_of_day="any"),
        _call("answer", value="no"),
    ]
    brain, ref, ledger, llm, cfg = _world(fixed_clock, responses, channel="sms", caller="+14165550199")
    slots, history = Slots(), []
    texts = ["I'd like someone to call me", "yes", "Helen", "the hydrabrasion", "Dana", "Thursday", "no"]
    replies = []
    for text in texts:
        r = await brain.turn(ref, history, text, slots)
        slots = r.slots
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": r.reply}]
        replies.append(r.reply)
    assert replies[0] == cfg.scripts.ask_returning
    assert replies[1] == cfg.scripts.ask_practitioner
    assert replies[2] == cfg.scripts.ask_service
    assert replies[3] == cfg.scripts.ask_name
    assert replies[4] == cfg.scripts.ask_window            # sms: no phone step
    assert replies[5] == cfg.scripts.ask_team_note
    assert replies[6].startswith("I've sent that to the team as a request")   # filed itself on the last answer
    item = ledger.items[0]
    assert item.type == "callback" and item.contact.name == "Dana" and item.contact.phone == "+14165550199"
    assert item.practitioner == "Helen Courbetis" and item.returning_client is True
    # The model was offered only the step's tools each turn.
    offered = [[t.name for t in tools] for (_, _, tools) in llm.calls_with_tools]
    assert all("file_request" not in names for names in offered)   # never needed: the record filed itself


async def test_the_model_cannot_file_early_or_put_a_name_in_the_wrong_slot(fixed_clock):
    from spatalk.brain.flow import Slots
    brain, ref, ledger, llm, cfg = _world(fixed_clock, [_call("file_request"), _call("give_name", first_name="Ellen")])
    r1 = await brain.turn(ref, [], "book me in", Slots(flow="new_booking"))
    assert ledger.items == [] and r1.reply == cfg.scripts.ask_returning
    r2 = await brain.turn(ref, [], "Ellen", r1.slots)
    assert r2.slots.first_name is None and r2.reply == cfg.scripts.ask_returning


async def test_a_side_question_is_answered_then_the_open_question_is_asked_again(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.flow import Slots
    brain, ref, ledger, llm, cfg = _world(fixed_clock, [LLMResponse(text="The Classic facial is $125.", tool_calls=[])])
    r = await brain.turn(ref, [], "how much is the classic facial?", Slots(flow="new_booking", returning_client=True))
    assert r.reply == "The Classic facial is $125. " + cfg.scripts.ask_practitioner


async def test_the_acknowledgement_is_one_sentence_and_the_question_is_the_script(fixed_clock):
    from spatalk.brain.driver import LLMResponse, ToolCall
    from spatalk.brain.flow import Slots
    resp = LLMResponse(text="Lovely, welcome back! I'm sure the team will be thrilled to see you again.",
                       tool_calls=[ToolCall("answer", {"value": "yes"})])
    brain, ref, ledger, llm, cfg = _world(fixed_clock, [resp])
    r = await brain.turn(ref, [], "yes", Slots(flow="new_booking"))
    assert r.reply == "Lovely, welcome back! " + cfg.scripts.ask_practitioner


async def test_clinical_gate_offers_first_and_files_only_on_yes(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.flow import Slots
    brain, ref, ledger, llm, cfg = _world(fixed_clock, [
        _call("answer", value="yes"), _call("give_name", first_name="Dana"), _call("answer", value="yes"),
    ])
    r = await brain.turn(ref, [], "I have a rash after my peel", Slots())
    assert r.reply == cfg.scripts.clinical_offer and ledger.items == [] and not r.ended and r.gate_reason == "clinical"
    r = await brain.turn(ref, [], "yes please", r.slots)
    assert r.reply == cfg.scripts.ask_name
    r = await brain.turn(ref, [], "Dana", r.slots)
    assert r.reply == cfg.scripts.ask_phone_same
    r = await brain.turn(ref, [], "yes", r.slots)
    assert r.reply.startswith("I've passed that to our clinical team")
    assert ledger.items[0].type == "escalation_clinical" and ledger.items[0].urgency == "urgent"
    assert ledger.items[0].contact.name == "Dana"


async def test_an_emergency_still_files_at_once(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.flow import Slots
    brain, ref, ledger, llm, cfg = _world(fixed_clock, [LLMResponse(text="x", tool_calls=[])])
    r = await brain.turn(ref, [], "I can't breathe", Slots())
    assert "911" in r.reply and ledger.items[0].type == "escalation_emergency" and r.ended
```

`FakeLLM` gains `calls_with_tools: list[tuple[str, list[dict], list]]` (append `(system, history, tools)` in `complete`) — keep `calls` as it is.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_driver_flow.py`
Expected: FAIL — `Brain.turn` takes no `slots`.

- [ ] **Step 3: Change `Capabilities` and Tier C**

`capabilities.py`: `async def capture(self, ref: ConversationRef, draft: ItemDraft) -> Outcome: ...`; delete `request_appointment_change`. Import `ItemDraft` from `spatalk.brain.ports`.

`tier_c.py`: replace `capture` and delete `request_appointment_change`, `NAME_REQUIRED`, `_named`:

```python
    async def capture(self, ref: ConversationRef, draft: ItemDraft) -> Captured | Refused:
        # The last line of defence for CLAUDE.md 2 and the slot engine's invariant: a booking,
        # callback or change with no first name is refused before anything is written.
        if draft.type in NAME_REQUIRED_TYPES and not (draft.contact.name or "").strip():
            return Refused(reason="no_name")
        return await self._capture(ref, _with_caller_draft(ref, draft))
```

with `NAME_REQUIRED_TYPES = frozenset({"new_booking", "callback", "reschedule", "cancel"})` and

```python
def _with_caller_draft(ref: ConversationRef, draft: ItemDraft) -> ItemDraft:
    if draft.contact.phone is None and ref.caller_phone:
        return draft.model_copy(update={"contact": draft.contact.model_copy(update={"phone": ref.caller_phone})})
    return draft
```

`escalate` keeps building its own `ItemDraft` for the gate paths (`escalation_<reason>`, urgent); `send_booking_link` unchanged. The guard's blocked-claim path in `driver.py` (`caps.capture(ref, CaptureRequest(kind="question"))`) becomes `caps.capture(ref, draft_from(Slots(flow="question"), cfg))` — a question needs no name in Tier C, so it still files.

`requests.py`: delete `CaptureRequest`, `AppointmentChangeRequest`, `CaptureKind`, `ChangeKind`, `LeadContext` (move the docstring's rule to `ItemDraft`). `BookingLinkRequest` becomes `class BookingLinkRequest(BaseModel, frozen=True): service_id: str; contact: ContactInfo = ContactInfo()`.

- [ ] **Step 4: Rewrite the driver's tool path and turn**

Replace `_contact`, `_lead`, `_window`, `dispatch_tool` with:

```python
async def run_tool(
    caps: Capabilities, ref: ConversationRef, slots: Slots, name: str, args: dict, now: datetime
) -> tuple[Slots, list[str], Outcome | None, bool]:
    """One tool call through the engine. Returns (slots, spoken lines, outcome, ended).

    Spoken lines are tenant scripts, never model text. A tool the step did not offer is
    ignored: nothing is said and nothing is written.
    """
    cfg = ref.tenant
    applied = apply(slots, name, args or {}, cfg, ref.channel, ref.caller_phone)
    if applied.ignored:
        logger.warning("tool {} ignored at this step with args {}", name, args)
        return slots, [], None, False
    spoken = [render_script(key, cfg, now, urgent=False, **fills) for key, fills in applied.say]
    outcome: Outcome | None = None
    ended = applied.end
    try:
        if name == "escalate":
            outcome = await caps.escalate(ref, EscalateRequest(reason=args.get("reason", "unsure")))
            spoken.append(render(outcome, cfg, now, channel=ref.channel))
            ended = True
        elif name == "end_conversation":
            spoken.append(render_script("goodbye", cfg, now, urgent=False))
        elif applied.file:
            outcome = await caps.capture(ref, draft_from(applied.slots, cfg, health_context=ref.health_context))
            spoken.append(render(outcome, cfg, now, channel=ref.channel))
        elif applied.send_link:
            outcome = await caps.send_booking_link(
                ref, BookingLinkRequest(service_id=applied.slots.service_id or "", contact=ContactInfo(name=applied.slots.first_name, phone=applied.slots.phone))
            )
            spoken.append(render(outcome, cfg, now, channel=ref.channel))
    except (ValueError, TypeError) as e:
        logger.warning("tool {} rejected args {}: {}", name, args, e)
        return slots, [], None, False
    except Exception as e:  # noqa: BLE001  ledger, SMS or database failure: nothing was saved
        logger.exception("tool {} failed: {}", name, e)
        outcome = Refused(reason="unavailable")
        spoken.append(render(outcome, cfg, now, channel=ref.channel))
    return applied.slots, spoken, outcome, ended
```

`TurnResult` gains `slots: Slots = field(default_factory=Slots)` and `said: list[str] = field(default_factory=list)`.

`Brain.turn`:

```python
    async def turn(self, ref, history, user_text, slots: Slots | None = None) -> TurnResult:
        cfg, now = ref.tenant, self._clock.now()
        slots = slots or Slots()
        if health_context_mentioned(user_text, cfg) and not ref.health_context:
            ref = ref.model_copy(update={"health_context": True})
        gate = rules_gate(user_text, cfg)
        if gate and gate.reason != "clinical":
            out = await self._caps.escalate(ref, EscalateRequest(reason=gate.reason))
            return TurnResult(reply=render(out, cfg, now, channel=ref.channel), band=3, gate_reason=gate.reason,
                              tool_calls=["escalate"], outcomes=[out], ended=True,
                              health_context=ref.health_context, slots=slots)
        if gate:  # clinical: offer first, file on yes (slot engine design, §4.2)
            opened = open_flow("clinical", slots, ref.channel, ref.caller_phone)
            return TurnResult(reply=render_script("clinical_offer", cfg, now, urgent=False), band=3,
                              gate_reason="clinical", health_context=ref.health_context, slots=opened)
        step = next_step(slots, cfg, ref.channel)
        resp = await self._llm.complete(
            build_system_prompt(cfg, ref.channel, now),
            history + [{"role": "system", "content": step_message(step, slots, cfg, ref.channel)},
                       {"role": "user", "content": user_text}],
            step_tools(step, slots, cfg, ref.channel),
        )
        said: list[str] = []
        outcomes: list[Outcome] = []
        names: list[str] = []
        ended, band = False, 1
        for tc in resp.tool_calls:
            names.append(tc.name)
            slots, spoken, out, did_end = await run_tool(self._caps, ref, slots, tc.name, tc.arguments, now)
            said.extend(spoken)
            if out is not None:
                outcomes.append(out)
                if isinstance(out, Captured):
                    band = 3 if out.item_type.startswith("escalation_") else max(band, 2)
            ended = ended or did_end
        ack, blocked = "", False
        if resp.text:
            g = guard(resp.text, any(isinstance(o, Completed) for o in outcomes), cfg, replacement="")
            if g.blocked:
                blocked = True
                try:
                    out = await self._caps.capture(ref, draft_from(Slots(flow="question"), cfg))
                    said.insert(0, render_script("cannot_complete", cfg, now, urgent=False))
                except Exception as e:  # noqa: BLE001
                    logger.exception("guard could not file the blocked claim: {}", e)
                    out = Refused(reason="unavailable")
                    said.insert(0, render(out, cfg, now, channel=ref.channel))
                outcomes.append(out)
                band = max(band, 2)
                logger.warning("guard blocked model text ({}): {!r}", g.matched, resp.text)
            else:
                ack = first_sentence(g.text) if names else g.text
        question = ""
        if not ended and not said:
            q = step_question(next_step(slots, cfg, ref.channel), slots, cfg, ref.channel)
            if q is not None:
                question = render_script(q[0], cfg, now, urgent=False, **q[1])
        elif not ended and said and slots.flow and not slots.ended_flow:
            q = step_question(next_step(slots, cfg, ref.channel), slots, cfg, ref.channel)
            if q is not None:
                question = render_script(q[0], cfg, now, urgent=False, **q[1])
        if slots.ended_flow:
            slots = slots.with_(flow=None, ended_flow=False)
        reply = " ".join(p for p in [ack, *said, question] if p).strip()
        return TurnResult(reply=reply, band=band, gate_reason=None, tool_calls=names, outcomes=outcomes,
                          guard_blocked=blocked, ended=ended, health_context=ref.health_context,
                          slots=slots, said=said)
```

with, at module level:

```python
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def first_sentence(text: str) -> str:
    """One acknowledgement at most (slot engine design, §3 invariant 4)."""
    parts = _SENTENCE_END.split(text.strip(), maxsplit=1)
    return parts[0] if parts else ""
```

`open_flow` is exported by `flow.py` (Task 5) and keeps the name and number the conversation already has. The clinical yes/no lives in `apply` (Task 5). When a clinical flow files, `draft_from` sets urgency `urgent` and the renderer speaks the tenant's `clinical` script because Tier C's `_capture` returns `Captured(item_type="escalation_clinical")`.

- [ ] **Step 5: Update `tests/test_driver.py` and `tests/test_tier_c.py`**

`test_driver.py`: rewrite `test_tool_call_reply_is_rendered_not_generated` to open a `cancel` flow with the slots filled and call `file_request`; the reply starts with "I've sent that to the team as a request" and the item type is `cancel`. Replace every `ToolCall("capture_request", …)` / `ToolCall("request_appointment_change", …)` with a `Slots` that has the fields filled and a `file_request` call. `test_rules_gate_short_circuits_without_llm` now expects `r.reply == cfg.scripts.clinical_offer`, `ledger.items == []`, `not r.ended`, `r.gate_reason == "clinical"`.

`test_tier_c.py`: `caps.capture(_ref(cfg), ItemDraft(type="callback", urgency="normal", service_id="facial", contact=ContactInfo(name="Dana")))`; delete `test_appointment_change_is_captured_not_completed` and `test_appointment_change_without_a_first_name_is_refused`; rewrite `test_booking_or_callback_without_a_first_name_is_refused_before_anything_is_written` against `ItemDraft` types `new_booking`, `callback`, `reschedule`, `cancel` (refused) and `question` (captured).

- [ ] **Step 6: Run the brain suites**

Run: `uv run pytest -q tests/test_driver.py tests/test_driver_flow.py tests/test_tier_c.py tests/test_renderer.py tests/test_guard.py tests/test_structural_honesty.py tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_lead_context.py tests/test_qa_gate_a.py`
Expected: PASS. `tests/test_lead_context.py` and `tests/test_qa_gate_a.py` scenarios that built `CaptureRequest`s are rewritten the same way as `test_driver.py` (slots filled + `file_request`); the ledger's null-and-log rule for a practitioner not on the team is now exercised through `draft_from` with a hand-built `Slots(practitioner="Nobody Real")`.

- [ ] **Step 7: Commit**

```bash
git add spatalk/brain tests/test_driver.py tests/test_driver_flow.py tests/test_tier_c.py tests/test_lead_context.py tests/test_qa_gate_a.py
git commit -m "feat(brain): Brain.turn runs the slot engine; file_request builds the item from the record; clinical offers first"
```

---

### Task 8: Migration and the text service

**Files:**
- Create: `alembic/versions/0013_flow_slots.py`
- Modify: `spatalk/models.py` (class `Conversation`), `spatalk/text/service.py` (`handle_inbound`, `_finish_turn`), `docs/reference/data-model.md`
- Test: `tests/test_text_service.py` (fixture `ctx`, helpers `_service(ctx, llm)` and `_inbound(svc, text, msg_id, sender=CALLER)`), `tests/test_contract_snapshot.py` (must still pass)

**Interfaces:**
- Produces: `Conversation.flow: Mapped[dict | None]` (JSONB); the text service passes `Slots.model_validate(conv.flow)` into `Brain.turn` and writes `turn.slots.model_dump(mode="json")` back.

- [ ] **Step 1: Write the failing test**

In `tests/test_text_service.py`, using its `ctx` fixture and helpers:

```python
async def test_the_slot_record_survives_between_texts(ctx, sf):
    from sqlalchemy import select
    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall
    from spatalk.models import Conversation
    llm = FakeLLM([
        LLMResponse(text=None, tool_calls=[ToolCall("start_request", {"kind": "callback"})]),
        LLMResponse(text=None, tool_calls=[ToolCall("answer", {"value": "yes"})]),
    ])
    svc = _service(ctx, llm)
    await _inbound(svc, "call me please", "m1")
    second = await _inbound(svc, "yes", "m2")
    async with sf() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == second.conversation_id))
    assert conv.flow["flow"] == "callback" and conv.flow["returning_client"] is True
    cfg = await ctx.registry.get("skincentrix")
    assert second.replies[0] == cfg.scripts.ask_practitioner
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest -q tests/test_text_service.py::test_the_slot_record_survives_between_texts`
Expected: FAIL — `Conversation` has no `flow`.

- [ ] **Step 3: Migration and model**

`alembic/versions/0013_flow_slots.py`:

```python
"""flow: the slot engine's record on conversations (slot engine design, §6.3)

What the runtime knows about the open request: which flow, which slots are filled, which
confirmation is pending. Written after every turn on every channel so a dropped call or a
text thread resumed within its window picks up at the open step. Nullable: most
conversations never open a request. Nothing here is free text; the values are the closed
ones the item will carry. Nulled with the transcript by the retention job.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("flow", postgresql.JSONB(), nullable=True), schema="runtime")


def downgrade() -> None:
    op.drop_column("conversations", "flow", schema="runtime")
```

`models.py`, class `Conversation`, after `stage_ms`: `flow: Mapped[dict | None] = mapped_column(JSONB, nullable=True)`.

Add `flow` to the retention job's null list where it nulls `notes` (`spatalk/ops/retention.py`; grep `notes=None`).

`docs/reference/data-model.md`: in the conversations section, add `flow jsonb null — the slot engine's record (slot engine design §6.3); nulled with the transcript`.

- [ ] **Step 4: The text service**

In `handle_inbound`, replace the `Brain(...).turn(...)` call:

```python
        slots = Slots.model_validate(conv.flow) if conv.flow else Slots()
        turn = await Brain(self._llm, caps, ctx.clock).turn(ref, await self.history(conv.id), text, slots)
```

and in `_finish_turn`, add `values["flow"] = turn.slots.model_dump(mode="json")`. Import `Slots` from `spatalk.brain.flow`. Note `Brain.turn`'s history is the stored transcript; the step message is added by `turn` itself and is never stored as a message.

- [ ] **Step 5: Run**

Run: `uv run alembic upgrade head` (against the dev database named in `.env`, as the repo's CLAUDE.md says after model changes), then `uv run pytest -q tests/test_text_service.py tests/test_textback.py tests/test_takeover.py tests/test_contract_snapshot.py tests/test_call_notes.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0013_flow_slots.py spatalk/models.py spatalk/text/service.py spatalk/ops/retention.py docs/reference/data-model.md tests/test_text_service.py
git commit -m "feat(text): the slot record lives on the conversation and follows the thread between texts"
```

---

### Task 9: Voice session and handlers

**Files:**
- Modify: `spatalk/voice/session.py`, `spatalk/voice/handlers.py`, `spatalk/voice/pipeline.py`
- Create: `spatalk/voice/steps.py`
- Test: `tests/test_voice_handlers.py` (exists with one test, `test_handler_speaks_rendered_text_and_disables_llm_rerun`, written against `capture_request`: rewrite it as a `file_request` on filled slots, then add the tests below)

**Interfaces:**
- Produces:
  - `VoiceSession.slots: Slots` (default `Slots()`), `VoiceSession.tool_called_this_turn: bool`.
  - `steps.sync_context(session) -> None`: replaces the `[step]` system message in `session.context` and calls `session.context.set_tools(ToolsSchema(standard_tools=step_tools(...)))`.
  - `steps.next_question(session, now) -> str | None`: the rendered question for the open step, or `None`.
  - `handlers.register_tool_handlers(llm, session)` registers every name in `TOOL_NAMES` (+ transfer) to one handler that calls `run_tool`, speaks, re-syncs.
- Consumes: `run_tool`, `Slots`, `step_tools`, `step_message`, `step_question`, `STEP_MARKER`.

- [ ] **Step 1: Write the failing tests**

```python
import uuid
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _session(fixed_clock):
    from pipecat.processors.aggregators.llm_context import LLMContext
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.prompt import build_system_prompt
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.brain.tools import tools_schema
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession
    cfg = load_bundle(BUNDLE)
    ledger = MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    s = VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock)
    s.context = LLMContext(messages=[{"role": "system", "content": build_system_prompt(cfg, "voice", fixed_clock.now())}], tools=tools_schema(cfg))
    return s, ledger


class _Params:
    def __init__(self, name, args, llm):
        self.function_name, self.arguments, self.llm = name, args, llm
        self.results = []

    async def result_callback(self, result, properties=None):
        self.results.append((result, properties))


class _LLM:
    def __init__(self):
        self.frames = []

    async def push_frame(self, frame, direction=None):
        self.frames.append(frame)


def _spoken(llm):
    from pipecat.frames.frames import TTSSpeakFrame
    return [f.text for f in llm.frames if isinstance(f, TTSSpeakFrame)]


async def test_sync_context_puts_one_step_message_and_the_step_tools_in_the_context(fixed_clock):
    from spatalk.brain.flow import STEP_MARKER, Slots
    from spatalk.voice.steps import sync_context
    s, _ = _session(fixed_clock)
    sync_context(s)
    s.slots = Slots(flow="new_booking", returning_client=True)
    sync_context(s)
    steps = [m for m in s.context.messages if m.get("role") == "system" and str(m.get("content", "")).startswith(STEP_MARKER)]
    assert len(steps) == 1 and "choose_practitioner" in steps[0]["content"]
    names = [t.name for t in s.context.tools.standard_tools]
    assert "choose_practitioner" in names and "file_request" not in names


async def test_a_slot_tool_speaks_the_next_question_and_never_runs_the_llm(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler
    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    params = _Params("answer", {"value": "yes"}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [s.cfg.scripts.ask_practitioner]
    assert s.slots.returning_client is True and s.tool_called_this_turn
    assert params.results[0][1].run_llm is False


async def test_file_request_speaks_the_outcome_and_the_item_has_the_slots_contact(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    from spatalk.voice.handlers import _make_handler
    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
                    first_name="Dana", phone="+19055550101", phone_confirmed=True,
                    preferred_window=PreferredWindow(), team_note_asked=True)
    llm = _LLM()
    await _make_handler(s)(_Params("file_request", {}, llm))
    assert _spoken(llm)[0].startswith("I've sent that to the team as a request")
    assert ledger.items[0].contact.name == "Dana" and s.band == 2 and s.slots.flow is None


async def test_a_tool_the_step_did_not_offer_is_ignored_and_the_question_repeated(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler
    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    await _make_handler(s)(_Params("give_name", {"first_name": "Ellen"}, llm))
    assert s.slots.first_name is None and ledger.items == []
    assert _spoken(llm) == [s.cfg.scripts.ask_returning]
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_voice_handlers.py`
Expected: FAIL — no `spatalk.voice.steps`.

- [ ] **Step 3: Session fields and `steps.py`**

`session.py`: add `slots: Slots = field(default_factory=Slots)` and `tool_called_this_turn: bool = False` (import `Slots` from `spatalk.brain.flow`).

`spatalk/voice/steps.py`:

```python
"""Keeping the call's LLM context on the open step (slot engine design, §6.5).

The spec's fallback, chosen up front: Pipecat Flows would move the system prompt onto the
LLM service's settings, and this pipeline keeps it as the first context message where the
gate, the guard and the transcript expect it. So the step is synced by hand: one `[step]`
system message, replaced each time, and the step's tools set on the context.
"""
from __future__ import annotations

from datetime import datetime

from pipecat.adapters.schemas.tools_schema import ToolsSchema

from spatalk.brain.flow import STEP_MARKER, next_step, step_message, step_question, step_tools
from spatalk.brain.renderer import render_script
from spatalk.voice.session import VoiceSession


def sync_context(session: VoiceSession) -> None:
    ctx = session.context
    if ctx is None:
        return
    step = next_step(session.slots, session.cfg, "voice")
    kept = [m for m in ctx.messages if not (m.get("role") == "system" and str(m.get("content", "")).startswith(STEP_MARKER))]
    kept.append({"role": "system", "content": step_message(step, session.slots, session.cfg, "voice")})
    ctx.set_messages(kept)
    ctx.set_tools(ToolsSchema(standard_tools=step_tools(step, session.slots, session.cfg, "voice", session.transfer_enabled)))


def next_question(session: VoiceSession, now: datetime) -> str | None:
    if session.slots.flow is None or session.slots.ended_flow:
        return None
    q = step_question(next_step(session.slots, session.cfg, "voice"), session.slots, session.cfg, "voice")
    if q is None:
        return None
    return render_script(q[0], session.cfg, now, urgent=False, **q[1])
```

If `LLMContext.messages` returns copies whose dicts are the originals, `set_messages(kept)` is still correct; if `set_messages` rejects a list containing the system prompt, keep the first message and rebuild the rest (check `llm_context.py:377`).

- [ ] **Step 4: The handler**

`handlers.py`: `register_tool_handlers` registers every name in `TOOL_NAMES` (imported from `spatalk.brain.tools`) plus the transfer tool as before. `_make_handler` becomes:

```python
def _make_handler(session: VoiceSession):
    async def handler(params: FunctionCallParams):
        now = session.clock.now()
        session.tool_called_this_turn = True
        slots, spoken, outcome, ended = await run_tool(
            session.caps, session.ref, session.slots, params.function_name, dict(params.arguments or {}), now
        )
        session.slots = slots
        if isinstance(outcome, Completed):
            session.has_completed = True
        if isinstance(outcome, Captured):
            session.band = 3 if outcome.item_type.startswith("escalation_") else max(session.band, 2)
        if session.slots.ended_flow:
            session.slots = session.slots.with_(flow=None, ended_flow=False)
        question = None if ended else next_question(session, now)
        lines = spoken + ([question] if question else [])
        if not lines and not ended:
            q = next_question(session, now)
            lines = [q] if q else []
        sync_context(session)
        for text in lines:
            await params.llm.push_frame(TTSSpeakFrame(text=text, append_to_context=True))
        await params.result_callback(
            {"spoken": bool(lines), "outcome": outcome.kind if outcome else "none"},
            properties=FunctionCallResultProperties(run_llm=False),
        )
        if ended:
            session.ended = True
            if session.worker is not None:
                await session.worker.queue_frames([EndFrame()])

    return handler
```

Import `run_tool` from `spatalk.brain.driver` (replacing `dispatch_tool`) and `next_question`, `sync_context` from `spatalk.voice.steps`.

`pipeline.py`: after `session.context = context`, call `sync_context(session)` so the call starts in the `QA` step with `start_request` offered; keep `tools=tools_schema(cfg, transfer_enabled=can_transfer)` in the `LLMContext(...)` constructor (it is replaced by the sync).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q tests/test_voice_handlers.py tests/test_voice_processors.py`
Expected: PASS (processors tests still pass; the gate change is Task 10).

- [ ] **Step 6: Commit**

```bash
git add spatalk/voice/session.py spatalk/voice/steps.py spatalk/voice/handlers.py spatalk/voice/pipeline.py tests/test_voice_handlers.py
git commit -m "feat(voice): the call's context follows the open step; slot tools speak the next fixed question"
```

---

### Task 10: Voice — the clinical offer from the gate, and the re-ask after a side answer

**Files:**
- Modify: `spatalk/voice/processors.py` (`RulesGateProcessor`, `OutputGuardProcessor`)
- Test: `tests/test_voice_processors.py`

**Interfaces:**
- Produces: on a non-emergency clinical match the gate sets `session.slots = Slots(flow="clinical")`, speaks `clinical_offer`, syncs the context and does not end the call; on every other reason it behaves as today. `OutputGuardProcessor` pushes the open step's question after the model's spoken text when no tool was called this turn (`session.tool_called_this_turn` reset at each `LLMFullResponseStartFrame`).
- Consumes: `sync_context`, `next_question` (Task 9).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_voice_processors.py` (use its `_session` helper and the frame-capturing pattern the file already uses for the gate tests):

```python
async def test_clinical_gate_offers_and_keeps_the_call_open(fixed_clock):
    from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from spatalk.voice.processors import RulesGateProcessor
    session, ledger = _session(fixed_clock)
    session.context = LLMContext(messages=[{"role": "system", "content": "x"}])
    proc = RulesGateProcessor(session)
    pushed = []
    proc.push_frame = _capture(pushed)              # the file's existing helper for stubbing push_frame
    await proc.process_frame(TranscriptionFrame(text="I have a rash after my peel", user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)
    spoken = [f.text for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert spoken == [session.cfg.scripts.clinical_offer]
    assert ledger.items == [] and not session.ended and session.slots.flow == "clinical"
    assert session.context.messages[-2]["content"] == "I have a rash after my peel"   # the utterance, then the step message


async def test_emergency_gate_is_unchanged(fixed_clock):
    from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from spatalk.voice.processors import RulesGateProcessor
    session, ledger = _session(fixed_clock)
    session.context = LLMContext(messages=[{"role": "system", "content": "x"}])
    proc = RulesGateProcessor(session)
    pushed = []
    proc.push_frame = _capture(pushed)
    await proc.process_frame(TranscriptionFrame(text="I can't breathe", user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)
    spoken = [f.text for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert len(spoken) == 1 and "911" in spoken[0]
    assert ledger.items[0].type == "escalation_emergency" and session.ended and session.slots.flow is None


async def test_the_open_question_follows_a_side_answer(fixed_clock):
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, TextFrame, TTSSpeakFrame
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor
    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=True)
    proc = OutputGuardProcessor(session)
    pushed = []
    proc.push_frame = _capture(pushed)
    await proc.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(TextFrame(text="The Classic facial is $125."), FrameDirection.DOWNSTREAM)
    await proc.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    spoken = [f.text for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert spoken[-1] == session.cfg.scripts.ask_practitioner
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest -q tests/test_voice_processors.py`
Expected: the three new tests FAIL.

- [ ] **Step 3: The gate**

In `RulesGateProcessor.process_frame`, inside `if gate:` and after the `add_message` of the caller's text, branch:

```python
                if gate.reason == "clinical":
                    self._s.slots = Slots(flow="clinical")
                    sync_context(self._s)
                    await self.push_frame(
                        TTSSpeakFrame(text=render_script("clinical_offer", self._s.cfg, now, urgent=False), append_to_context=True)
                    )
                    logger.info("rules gate: clinical ({!r}) -> offer", gate.matched)
                    return
```

leaving the existing escalate-and-end path for every other reason. Import `Slots`, `sync_context`, `render_script`.

- [ ] **Step 4: The re-ask**

In `OutputGuardProcessor`: on `LLMFullResponseStartFrame` set `self._s.tool_called_this_turn = False`; on `LLMFullResponseEndFrame` (after passing it through), if `not self._s.tool_called_this_turn and not self._s.ended`, compute `q = next_question(self._s, self._s.clock.now())` and, when not `None`, `await self.push_frame(TTSSpeakFrame(text=q, append_to_context=True))`. Read the processor's existing handling of the start/end frames first — it already tracks a turn for the guard — and add to it rather than around it.

- [ ] **Step 5: Run the voice suites**

Run: `uv run pytest -q tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_voice_turns.py tests/test_voice_echo.py tests/test_voice_filler.py tests/test_voice_transfer.py`
Expected: PASS (adjust only an assertion on the initial tool list, if one exists).

- [ ] **Step 6: Commit**

```bash
git add spatalk/voice/processors.py tests/test_voice_processors.py
git commit -m "feat(voice): the clinical gate offers first; the open question follows a side answer"
```

---

### Task 11: Full suite, lint, and the reference docs

**Files:**
- Modify: `docs/reference/flows.md` (the booking, callback and clinical flows now list the steps of §4), `docs/reference/api-surface.md` (the tool list, if documented), `docs/reference/tenant-config.md` (already done in Task 1; verify), `docs/roadmap.md` (a line under built)
- Test: whole suite

- [ ] **Step 1: Run everything**

Run: `uv run ruff check spatalk tests scenarios` then `uv run pytest -q` on a fresh scratch database (one DB per run; see `docs/reports/2026-09-03-demo-day-state.md`).
Expected: all green. Fix any remaining test that built a `CaptureRequest` the same way as Task 7 Step 5.

- [ ] **Step 2: Docs**

`flows.md`: rewrite the step lists for "new booking", "callback", "reschedule/cancel", "question", "clinical" to the §4 order, naming the script for each step. `api-surface.md`: replace the tool list with §6.2's table. `roadmap.md`: "Slot engine: runtime-owned request conversations (2026-09-05)" under built.

- [ ] **Step 3: Commit**

```bash
git add docs/reference/flows.md docs/reference/api-surface.md docs/roadmap.md
git commit -m "docs(reference): the request flows as the slot engine runs them"
```

---

### Task 12: promptfoo scenarios for the QA gate

**Files:**
- Modify: `scenarios/promptfooconfig.yaml` and the scenario files it references (read `scenarios/README.md` or the config header first for the harness's provider shape — `tests/test_scenarios_provider.py` tests the provider)
- Test: `tests/test_scenarios_provider.py`

- [ ] **Step 1: Add one scenario per step**

For each of: returning yes/no; offers yes/no; "Helen" / "Ellen" / "whoever"; "hydrabrasion" / "a facial"; a name / a refusal; phone yes / a new number; a window; the route; the clinical offer yes / no. Each scenario's assertions check the reply *equals* the script for the next step (the provider renders the tenant's scripts) and that the item, when filed, has `contact.name` and `contact.phone`. Do **not** run promptfoo (paid); the founder's QA gate does.

- [ ] **Step 2: Provider test**

Run: `uv run pytest -q tests/test_scenarios_provider.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add scenarios
git commit -m "test(scenarios): one promptfoo scenario per slot step for the QA gate"
```

---

### Task 13: Task report and handoff (founder's session does the rest)

- [ ] **Step 1: Write `docs/reports/tasks/slot-engine.md`** in the ENGINEER.md format: what changed per task, tests seen failing then passing with counts, the deviation from spec §6.5 (no `FlowManager`) and any other, and the go-live checklist below for the founder's session.

- [ ] **Step 2: Commit**

```bash
git add docs/reports/tasks/slot-engine.md
git commit -m "docs(report): slot engine"
```

- [ ] **Step 3: Go-live checklist (the founder's session, not the executor)**

1. `git merge slot-engine` into `main`, push.
2. `uv run alembic upgrade head` on the dev database.
3. `spatalk tenant import tenants/skincentrix` → config v23.
4. `restart-runtime.sh` (refuses during a live call).
5. promptfoo run on Gemini 3.5 Flash-Lite, Gemini 3.1 Flash-Lite, gpt-4.1-nano (one paid run each).
6. Founder call tests (spec §8 checklist); live DB check: `SELECT count(*) FROM runtime.items WHERE created_at > <go-live> AND (contact_name IS NULL OR contact_phone IS NULL)` must be 0.
7. `LLM_MODEL` to the shootout winner, as its own change.
