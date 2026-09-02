"""Per-stage latency budgets, the daily report and the SLO check (operations plan, E5).

Spec §10 weakness 3 is that a voice front desk is only as good as its silences: the brief's
S7 budget is 800 ms from the caller finishing to the assistant starting, and a call that
misses it is a call the customer thinks has dropped. A single turn number cannot be acted
on, though — "it was slow" is not a decision. The stage split is: the observer tags every
TTFB reading with the processor that produced it, `_finalize` stores the call's per-stage
p95, and the daily check names the stage that blew its budget and the swap that fixes it.

What this suite pins:

* the stage mapping is by service, not by position, so swapping Soniox for Deepgram Flux
  (or Google for OpenAI, Task E6) keeps reporting the same three stages;
* `stage_ms` is written by the pipeline's own `_finalize`, not by a reporting job, so the
  reading survives retention nulling the transcript;
* an SLO breach names one stage and one suggested fix, and dedups like every other alert;
* the nightly voice evals are skipped, loudly, when the provider keys are absent — a green
  tick on a job that ran nothing is the failure mode being avoided.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path


import yaml
from sqlalchemy import select

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent
WORKFLOW = ROOT / ".github" / "workflows" / "nightly-voice-evals.yml"
VOICE_SCENARIOS = RUNTIME / "scenarios" / "voice"

# 2026-09-01 in America/Toronto (EDT, UTC-4) runs 04:00 UTC that day to 04:00 UTC the next.
DAY = date(2026, 9, 1)
# 14:00 in Toronto: inside the local day.
MIDDAY = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
# 23:00 in Toronto on the day before: outside it.
TOO_EARLY = datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)
# The 05:00 UTC run that reports on the day above.
NOW = datetime(2026, 9, 2, 5, 0, tzinfo=timezone.utc)

OPS_EMAIL = "ops@example.test"


def _settings(**kw):
    from spatalk.settings import Settings

    return Settings(_env_file=None, secret_key="s", ops_email=OPS_EMAIL, **kw)


def _clock(at=NOW):
    from spatalk.clock import FixedClock

    return FixedClock(at)


def _ctx(sf, registry, clock=None, settings=None):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    clock = clock or _clock()
    return jobs.JobContext(
        sf=sf,
        clock=clock,
        registry=registry,
        ledger=PgLedger(sf, clock),
        delivery=MemoryDelivery(),
        settings=settings or _settings(),
        sms=MemorySms(),
    )


async def _call(
    sf,
    *,
    tenant_id="skincentrix",
    started_at=MIDDAY,
    latency_ms=(500,),
    stage_ms=None,
):
    """One finished voice call with its recorded turn latencies and stage p95s."""
    from spatalk.models import Conversation

    async with sf() as s, s.begin():
        c = Conversation(
            tenant_id=tenant_id,
            channel="voice",
            external_ref=f"v3:{uuid.uuid4()}",
            caller="+19055550101",
            band=1,
            latency_ms=list(latency_ms),
            stage_ms=stage_ms,
            started_at=started_at,
            ended_at=started_at,
        )
        s.add(c)
        await s.flush()
        return c.id


async def _second_tenant(registry, tenant_id="otherclinic"):
    cfg = await registry.get("skincentrix")
    other = cfg.model_copy(
        update={
            "id": tenant_id,
            "name": "Other Clinic",
            "voice_numbers": [],
            "sms_from_number": None,
        }
    )
    await registry.import_config(other, created_by="test")
    return other


def _metrics_frame(*readings):
    """A Pipecat `MetricsFrame` of TTFB readings: (processor name, seconds)."""
    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import TTFBMetricsData

    return MetricsFrame(
        data=[TTFBMetricsData(processor=name, value=value) for name, value in readings]
    )


async def _push(observer, frame):
    from pipecat.observers.base_observer import FramePushed
    from pipecat.processors.frame_processor import FrameDirection

    await observer.on_push_frame(
        FramePushed(
            source=None,
            destination=None,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
        )
    )


def _voice_session(clock, cfg=None, conversation_id=None):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession

    cfg = cfg or load_bundle(RUNTIME / "tenants" / "skincentrix")
    caps = TierCCapabilities(ledger=MemoryLedger(clock), sms=MemorySms(), clock=clock)
    ref = ConversationRef(
        conversation_id=conversation_id or uuid.uuid4(),
        tenant=cfg,
        channel="voice",
        caller_phone="+19055550101",
    )
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=clock)


# --- the budgets ------------------------------------------------------------------------


def test_the_budgets_are_the_briefs_numbers():
    from spatalk.ops.latency import BUDGETS_MS

    assert BUDGETS_MS == {"stt": 300, "llm": 450, "tts": 200, "turn": 800}


# --- the observer -----------------------------------------------------------------------


async def test_the_observer_maps_each_service_to_its_stage(fixed_clock):
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)

    await _push(
        observer,
        _metrics_frame(
            ("SonioxSTTService#0", 0.22),
            ("GoogleLLMService#0", 0.41),
            ("InworldTTSService#0", 0.18),
        ),
    )

    assert session.stage_ttfb_ms == {"stt": [220], "llm": [410], "tts": [180]}


async def test_the_observer_accumulates_one_reading_per_turn_per_stage(fixed_clock):
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)

    for value in (0.4, 0.6):
        await _push(observer, _metrics_frame(("GoogleLLMService#0", value)))

    assert session.stage_ttfb_ms["llm"] == [400, 600]
    assert session.stage_ttfb_ms["stt"] == [] and session.stage_ttfb_ms["tts"] == []


async def test_a_ttfb_reading_from_something_that_is_not_a_stage_is_ignored(fixed_clock):
    """Only the three vendor stages are budgeted; our own processors are not."""
    from spatalk.voice.observers import UsageObserver

    session = _voice_session(fixed_clock)
    observer = UsageObserver(session)

    await _push(observer, _metrics_frame(("OutputGuardProcessor#0", 0.9)))

    assert session.stage_ttfb_ms == {"stt": [], "llm": [], "tts": []}


def test_the_stage_mapping_follows_the_vendor_swaps_not_the_pipeline_position():
    """Every service `make_stt`, `make_tts` and `make_llm` can return maps to a stage."""
    from spatalk.voice.observers import stage_for_processor

    assert stage_for_processor("SonioxSTTService#0") == "stt"
    assert stage_for_processor("DeepgramFluxSTTService#0") == "stt"
    assert stage_for_processor("GoogleLLMService#0") == "llm"
    assert stage_for_processor("OpenAILLMService#0") == "llm"
    assert stage_for_processor("InworldTTSService#0") == "tts"
    assert stage_for_processor("DeepgramTTSService#0") == "tts"
    assert stage_for_processor("RulesGateProcessor#0") is None


def test_an_stt_service_is_never_read_as_a_tts_one():
    """"STTService" contains the substring "TTS"; a naive mapping puts STT in the TTS bin."""
    from spatalk.voice.observers import stage_for_processor

    assert stage_for_processor("SomeVendorSTTService#3") == "stt"
    assert stage_for_processor("SomeVendorTTSService#3") == "tts"


# --- the call's own p95 -----------------------------------------------------------------


def test_p95_takes_the_worst_of_the_tail_not_the_average():
    from spatalk.ops.latency import p95

    assert p95([100]) == 100
    assert p95(list(range(1, 101))) == 96
    assert p95([]) is None


def test_the_calls_stage_p95_drops_a_stage_that_never_reported(fixed_clock):
    from spatalk.ops.latency import session_stage_ms

    session = _voice_session(fixed_clock)
    session.stage_ttfb_ms["stt"] = [200, 260, 900]
    session.stage_ttfb_ms["llm"] = [400]

    assert session_stage_ms(session) == {"stt": 900, "llm": 400}


async def test_the_end_of_a_call_stores_the_stage_p95_on_the_conversation(sf, registry):
    """`_finalize` writes it, so the reading outlives the transcript retention deletes."""
    from spatalk.conversations import start_conversation
    from spatalk.models import Conversation
    from spatalk.voice.pipeline import _finalize

    class _StubContext:
        messages = [{"role": "assistant", "content": "Hi there."}]

    ctx = _ctx(sf, registry)
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "v3:call-1", "+19055550101")
    session = _voice_session(ctx.clock, cfg=cfg, conversation_id=cid)
    session.started_at = datetime.now(timezone.utc)
    session.latencies_ms = [700, 900]
    session.stage_ttfb_ms = {"stt": [210], "llm": [480], "tts": [190]}

    await _finalize(ctx, session, _StubContext())

    async with sf() as s:
        row = await s.get(Conversation, cid)
    assert row.stage_ms == {"stt": 210, "llm": 480, "tts": 190}
    assert row.latency_ms == [700, 900]


# --- the daily report -------------------------------------------------------------------


async def test_the_daily_report_computes_the_tenants_turn_percentiles(sf, registry):
    from spatalk.ops.latency import daily_latency

    await _call(sf, latency_ms=[100, 200, 300, 400])
    await _call(sf, latency_ms=[500, 600, 700, 800])

    rows = await daily_latency(_ctx(sf, registry), DAY)

    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == "skincentrix"
    assert row["turns"] == 8
    assert row["p50"] == 500 and row["p95"] == 800


async def test_the_daily_report_reads_the_tenants_local_day(sf, registry):
    from spatalk.ops.latency import daily_latency

    await _call(sf, latency_ms=[400], started_at=MIDDAY)
    await _call(sf, latency_ms=[9000], started_at=TOO_EARLY)

    rows = await daily_latency(_ctx(sf, registry), DAY)

    assert rows[0]["turns"] == 1 and rows[0]["p95"] == 400


async def test_the_daily_report_is_per_tenant(sf, registry):
    from spatalk.ops.latency import daily_latency

    await _second_tenant(registry)
    await _call(sf, tenant_id="skincentrix", latency_ms=[300])
    await _call(sf, tenant_id="otherclinic", latency_ms=[1500])

    rows = {r["tenant_id"]: r for r in await daily_latency(_ctx(sf, registry), DAY)}

    assert rows["skincentrix"]["p95"] == 300 and rows["skincentrix"]["over_budget"] == []
    assert rows["otherclinic"]["p95"] == 1500 and rows["otherclinic"]["over_budget"] == ["turn"]


async def test_the_daily_report_aggregates_the_stage_p95_across_calls(sf, registry):
    from spatalk.ops.latency import daily_latency

    await _call(sf, latency_ms=[400], stage_ms={"stt": 200, "llm": 300, "tts": 150})
    await _call(sf, latency_ms=[500], stage_ms={"stt": 280, "llm": 900, "tts": 190})

    rows = await daily_latency(_ctx(sf, registry), DAY)

    assert rows[0]["stage_p95"] == {"stt": 280, "llm": 900, "tts": 190}
    assert rows[0]["over_budget"] == ["llm"]


async def test_a_day_with_no_calls_reports_nothing_rather_than_a_zero_p95(sf, registry):
    from spatalk.ops.latency import daily_latency

    assert await daily_latency(_ctx(sf, registry), DAY) == []


# --- the SLO check ----------------------------------------------------------------------


async def test_a_stage_over_its_budget_alerts_and_names_the_stage_and_the_fix(sf, registry):
    from spatalk.models import AlertLog
    from spatalk.ops.latency import check_slo

    await _call(sf, latency_ms=[400], stage_ms={"stt": 200, "llm": 900, "tts": 150})
    ctx = _ctx(sf, registry)

    raised = await check_slo(ctx, DAY)

    assert [(a.tenant_id, a.stage) for a in raised] == [("skincentrix", "llm")]
    assert raised[0].p95_ms == 900 and raised[0].budget_ms == 450
    assert "llm" in raised[0].subject
    assert "flash-lite" in raised[0].body.lower()
    async with sf() as s:
        keys = [r.key for r in (await s.scalars(select(AlertLog))).all()]
    assert keys == [f"slo:llm:skincentrix:{DAY.isoformat()}"]
    assert len(ctx.delivery.emails) == 1


async def test_a_turn_over_budget_with_every_stage_inside_it_still_alerts(sf, registry):
    from spatalk.ops.latency import check_slo

    await _call(sf, latency_ms=[1200], stage_ms={"stt": 200, "llm": 300, "tts": 150})

    raised = await check_slo(_ctx(sf, registry), DAY)

    assert [a.stage for a in raised] == ["turn"]
    assert raised[0].p95_ms == 1200 and raised[0].budget_ms == 800


async def test_a_day_inside_every_budget_raises_nothing(sf, registry):
    from spatalk.ops.latency import check_slo

    await _call(sf, latency_ms=[600], stage_ms={"stt": 200, "llm": 300, "tts": 150})
    ctx = _ctx(sf, registry)

    assert await check_slo(ctx, DAY) == []
    assert ctx.delivery.emails == []


async def test_the_same_breach_alerts_once_inside_the_dedup_window(sf, registry):
    from spatalk.ops.latency import check_slo

    await _call(sf, latency_ms=[400], stage_ms={"stt": 900, "llm": 300, "tts": 150})
    ctx = _ctx(sf, registry)

    assert len(await check_slo(ctx, DAY)) == 1
    assert await check_slo(ctx, DAY) == []
    assert len(ctx.delivery.emails) == 1


async def test_every_breached_stage_gets_its_own_alert(sf, registry):
    from spatalk.ops.latency import check_slo

    await _call(sf, latency_ms=[1500], stage_ms={"stt": 900, "llm": 900, "tts": 900})

    raised = await check_slo(_ctx(sf, registry), DAY)

    assert [a.stage for a in raised] == ["turn", "stt", "llm", "tts"]


# --- the scheduled run ------------------------------------------------------------------


async def test_the_run_records_an_ops_run_row_even_on_a_quiet_day(sf, registry):
    from spatalk.models import OpsRun
    from spatalk.ops.latency import RUN_KIND, run_latency_report

    await run_latency_report(_ctx(sf, registry), DAY)

    async with sf() as s:
        runs = list((await s.scalars(select(OpsRun))).all())
    assert len(runs) == 1
    assert runs[0].kind == RUN_KIND and runs[0].ok is True
    assert runs[0].summary["day"] == DAY.isoformat() and runs[0].summary["tenants"] == []


async def test_the_run_reports_yesterday_by_default_and_alerts_on_it(sf, registry):
    from spatalk.models import AlertLog
    from spatalk.ops.latency import run_latency_report

    await _call(sf, latency_ms=[1500])

    report = await run_latency_report(_ctx(sf, registry))

    assert report["day"] == DAY.isoformat()
    async with sf() as s:
        assert [r.key for r in (await s.scalars(select(AlertLog))).all()] == [
            f"slo:turn:skincentrix:{DAY.isoformat()}"
        ]


async def test_the_scheduler_queues_the_report_once_a_day(sf, registry):
    from spatalk.ledger.scheduler import ensure_daily_latency_scheduled
    from spatalk.models import Job
    from spatalk.ops.latency import RUN_KIND

    ctx = _ctx(sf, registry, clock=_clock(datetime(2026, 9, 2, 5, 30, tzinfo=timezone.utc)))

    assert await ensure_daily_latency_scheduled(ctx) is True
    assert await ensure_daily_latency_scheduled(ctx) is False
    async with sf() as s:
        jobs_queued = list((await s.scalars(select(Job).where(Job.kind == RUN_KIND))).all())
    assert len(jobs_queued) == 1


async def test_the_scheduler_waits_for_the_hour(sf, registry):
    from spatalk.ledger.scheduler import ensure_daily_latency_scheduled

    ctx = _ctx(sf, registry, clock=_clock(datetime(2026, 9, 2, 4, 30, tzinfo=timezone.utc)))

    assert await ensure_daily_latency_scheduled(ctx) is False


async def test_the_job_handler_is_registered_under_its_kind(sf, registry):
    from spatalk import jobs
    from spatalk.models import OpsRun
    from spatalk.ops.latency import RUN_KIND

    ctx = _ctx(sf, registry)
    await jobs.enqueue(sf, RUN_KIND, {"day": DAY.isoformat()})

    assert await jobs.run_once(sf, ctx) == 1
    async with sf() as s:
        assert (await s.scalars(select(OpsRun))).one().kind == RUN_KIND


# --- the printed table ------------------------------------------------------------------


def test_the_table_names_the_stage_that_is_over_budget():
    from spatalk.ops.latency import latency_table

    text = latency_table(
        [
            {
                "day": "2026-09-01",
                "tenant_id": "skincentrix",
                "conversations": 2,
                "turns": 8,
                "p50": 500,
                "p95": 900,
                "stage_p95": {"stt": 200, "llm": 900, "tts": 150},
                "over_budget": ["turn", "llm"],
            }
        ]
    )

    assert "skincentrix" in text and "2026-09-01" in text
    assert "900" in text and "llm" in text


def test_the_report_script_takes_a_days_window():
    """`scripts/latency_report.py --days 7` is the founder's command; it must parse."""
    import ast

    source = (RUNTIME / "scripts" / "latency_report.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "--days" in source
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "main" in functions


# --- the nightly voice evals ------------------------------------------------------------


def test_the_voice_scenarios_are_real_pipecat_scenarios():
    files = sorted(VOICE_SCENARIOS.glob("*.yaml"))
    assert files, "no voice eval scenarios"
    for path in files:
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert scenario["name"], f"{path.name} has no name"
        assert scenario["turns"], f"{path.name} has no turns"
        for turn in scenario["turns"]:
            assert "user" in turn and turn["expect"], f"{path.name} has a turn with no expectation"


def test_a_voice_scenario_measures_the_turn_budget():
    """At least one scenario asserts the 800 ms budget, or the evals measure nothing."""
    from spatalk.ops.latency import BUDGETS_MS

    budgets = []
    for path in sorted(VOICE_SCENARIOS.glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        for turn in scenario["turns"]:
            budgets += [e["within_ms"] for e in turn["expect"] if "within_ms" in e]
    assert budgets, "no scenario carries a within_ms latency budget"
    assert BUDGETS_MS["turn"] in budgets


def test_the_nightly_eval_workflow_is_skipped_without_the_provider_keys():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["voice-evals"]
    # The keys are lifted to the job environment: the `secrets` context is not available
    # in a step-level `if` (the same reason ci.yml lifts GOOGLE_API_KEY).
    assert set(job["env"]) >= {"GOOGLE_API_KEY", "SONIOX_API_KEY", "INWORLD_API_KEY"}
    for name in ("GOOGLE_API_KEY", "SONIOX_API_KEY", "INWORLD_API_KEY"):
        assert job["env"][name] == "${{ secrets.%s }}" % name
    steps = job["steps"]
    guarded = [s for s in steps if "eval run" in str(s.get("run", ""))]
    assert guarded, "the workflow never runs the evals"
    for step in guarded:
        assert "env.GOOGLE_API_KEY != ''" in step["if"]
        assert "-a" in step["run"] or "--audio" in step["run"]
        assert "scenarios/voice" in step["run"]
    notices = [s for s in steps if "::notice" in str(s.get("run", ""))]
    assert notices, "a skipped run must say so"
    assert any("== ''" in s["if"] for s in notices)


def test_the_nightly_eval_workflow_runs_nightly():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads a bare `on:` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert "schedule" in triggers and triggers["schedule"][0]["cron"]
    assert "workflow_dispatch" in triggers


def test_no_provider_key_is_committed_in_the_eval_assets():
    committed = [WORKFLOW, *sorted(VOICE_SCENARIOS.glob("*.yaml"))]
    committed += sorted(VOICE_SCENARIOS.glob("*.py")) + sorted(VOICE_SCENARIOS.glob("*.md"))
    for path in committed:
        text = path.read_text(encoding="utf-8")
        assert "sk-" not in text and "AIza" not in text


# --- the bot the harness drives ---------------------------------------------------------


def _pipeline_elements(path: Path) -> list[str]:
    """The processors passed to `Pipeline([...])` in a module, in order, as written."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "Pipeline"
            and node.args
            and isinstance(node.args[0], ast.List)
        ):
            return [ast.unparse(e) for e in node.args[0].elts]
    raise AssertionError(f"no Pipeline([...]) in {path.name}")


def test_the_eval_bot_runs_the_production_pipeline_in_the_production_order():
    """An eval measuring a different pipeline measures nothing about production."""
    production = _pipeline_elements(RUNTIME / "spatalk" / "voice" / "pipeline.py")
    evaluated = _pipeline_elements(VOICE_SCENARIOS / "eval_bot.py")

    # The RTVI processor is the harness's only addition: it is how the bot is heard.
    assert [e for e in evaluated if e != "rtvi"] == production
    assert evaluated[1] == "rtvi"


def test_the_eval_bot_is_what_the_workflow_spawns():
    import ast

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "scenarios/voice/eval_bot.py -t eval --port" in workflow
    tree = ast.parse((VOICE_SCENARIOS / "eval_bot.py").read_text(encoding="utf-8"))
    entry = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "bot"]
    assert entry and [a.arg for a in entry[0].args.args] == ["runner_args"]


def test_the_eval_bot_needs_no_database_and_files_nothing_real():
    """It runs on memory ports: a scenario must never reach a clinic's ledger."""
    source = (VOICE_SCENARIOS / "eval_bot.py").read_text(encoding="utf-8")
    assert "MemoryLedger" in source and "MemorySms" in source
    assert "PgLedger" not in source and "make_session_factory" not in source
