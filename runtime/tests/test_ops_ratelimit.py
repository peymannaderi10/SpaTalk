"""Task E8: per-IP rate limits, security headers on the action pages, and the CI scanners.

The limiter is in-process on purpose (one runtime node, no Redis: operations plan, Global
Constraints). These tests pin the documented limits, the refill arithmetic, the headers the
confirm page must carry, and the fact that CI actually runs the three scanners.
"""

from __future__ import annotations

import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
GITLEAKS = ROOT / ".gitleaks.toml"
PIP_AUDIT_IGNORE = RUNTIME / ".pip-audit-ignore"
NPM_AUDIT_ALLOW = ROOT / ".github" / "npm-audit-allow.json"

T0 = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


# --- the bucket ---------------------------------------------------------------------------


def test_the_token_bucket_refills_at_the_rule_rate():
    from spatalk.http.ratelimit import TokenBucket

    # Ten a minute is one token every six seconds.
    bucket = TokenBucket(capacity=10, refill_per_second=10 / 60, now=T0)
    for _ in range(10):
        assert bucket.take(T0) == 0.0
    wait = bucket.take(T0)
    assert wait == pytest.approx(6.0, abs=0.01)

    # Part of the way there is still too early, and the wait shrinks as time passes.
    assert bucket.take(T0 + timedelta(seconds=2)) == pytest.approx(4.0, abs=0.01)
    assert bucket.take(T0 + timedelta(seconds=6)) == 0.0
    # That token is spent; the next one is six seconds after it.
    assert bucket.take(T0 + timedelta(seconds=6)) == pytest.approx(6.0, abs=0.01)


def test_a_quiet_hour_does_not_bank_more_than_the_capacity():
    from spatalk.http.ratelimit import TokenBucket

    bucket = TokenBucket(capacity=10, refill_per_second=10 / 60, now=T0)
    later = T0 + timedelta(hours=1)
    allowed = sum(1 for _ in range(50) if bucket.take(later) == 0.0)
    assert allowed == 10


def test_the_documented_limits_are_the_ones_the_app_installs():
    from spatalk.http.ratelimit import RULES, IpRateLimiter

    per_minute = {rule.prefix: rule.per_minute for rule in RULES}
    assert per_minute["/a/"] == 10
    assert per_minute["/chat/"] == 30
    assert per_minute["/widget/"] == 60
    assert per_minute["/telnyx/"] == 300
    assert per_minute["/instagram/"] == 300

    exempt = {rule.prefix for rule in RULES if rule.edge_key_exempt}
    assert {"/telnyx/", "/instagram/"} <= exempt
    assert not ({"/a/", "/chat/", "/widget/"} & exempt), "a browser path must never be exempt"

    limiter = IpRateLimiter()
    assert limiter.rule_for("/a/abc").per_minute == 10
    assert limiter.rule_for("/chat/fallback").per_minute == 30
    assert limiter.rule_for("/widget/skincentrix/config").per_minute == 60
    # Everything else is unlimited: /healthz is what the uptime monitor polls, /internal/* is
    # the portal on a shared key, and /ws/{token} carries a signed five-minute token.
    for path in ("/healthz", "/internal/tenants", "/ws/tok", "/slack/interactions"):
        assert limiter.rule_for(path) is None


def test_the_client_ip_prefers_the_cloudflare_header():
    from spatalk.http.ratelimit import client_ip

    assert client_ip({"cf-connecting-ip": "203.0.113.7"}, ("10.0.0.1", 5)) == "203.0.113.7"
    assert client_ip({"x-forwarded-for": "203.0.113.8, 10.0.0.9"}, ("10.0.0.1", 5)) == "203.0.113.8"
    assert client_ip(
        {"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "198.51.100.1"}, ("10.0.0.1", 5)
    ) == "203.0.113.7"
    assert client_ip({}, ("10.0.0.1", 5)) == "10.0.0.1"
    assert client_ip({}, None) == "unknown"


# --- the app ------------------------------------------------------------------------------


@pytest.fixture
async def client(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    settings = Settings(
        _env_file=None,
        public_base_url="https://api.test",
        secret_key="s3cret",
        edge_shared_key="edge-key",
    )
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c, app, fixed_clock


async def test_a_confirm_page_is_limited_at_ten_a_minute_and_then_recovers(client):
    c, _app, clock = client
    for _ in range(10):
        assert (await c.get("/a/not-a-token")).status_code == 404
    r = await c.get("/a/not-a-token")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1

    # One token every six seconds, so the eleventh caller is served six seconds later.
    clock.advance(seconds=6)
    assert (await c.get("/a/not-a-token")).status_code == 404
    assert (await c.get("/a/not-a-token")).status_code == 429


async def test_a_limited_caller_does_not_shut_out_the_rest_of_the_internet(client):
    c, _app, _clock = client
    for _ in range(11):
        await c.get("/a/not-a-token")
    assert (await c.get("/a/not-a-token")).status_code == 429
    other = await c.get("/a/not-a-token", headers={"CF-Connecting-IP": "203.0.113.7"})
    assert other.status_code == 404


async def test_the_edge_worker_key_lifts_the_webhook_limit(client):
    c, app, _clock = client
    from spatalk.http.ratelimit import IpRateLimiter, Rule

    # The real bin is 300/min; two makes the same point in three requests.
    app.state.rate_limiter = IpRateLimiter([Rule("/telnyx/", 2, edge_key_exempt=True)])
    assert (await c.post("/telnyx/texml")).status_code != 429
    assert (await c.post("/telnyx/texml")).status_code != 429
    assert (await c.post("/telnyx/texml")).status_code == 429

    edge = {"X-Edge-Key": "edge-key"}
    for _ in range(5):
        assert (await c.post("/telnyx/texml", headers=edge)).status_code != 429


async def test_a_wrong_edge_key_is_still_rate_limited(client):
    c, app, _clock = client
    from spatalk.http.ratelimit import IpRateLimiter, Rule

    app.state.rate_limiter = IpRateLimiter([Rule("/telnyx/", 2, edge_key_exempt=True)])
    wrong = {"X-Edge-Key": "not-the-edge-key"}
    await c.post("/telnyx/texml", headers=wrong)
    await c.post("/telnyx/texml", headers=wrong)
    assert (await c.post("/telnyx/texml", headers=wrong)).status_code == 429


async def test_the_uptime_monitor_is_never_rate_limited(client):
    c, _app, _clock = client
    for _ in range(20):
        assert (await c.get("/healthz")).status_code == 200


async def test_the_action_pages_carry_a_locked_down_csp_and_no_referrer(client, sf, registry):
    c, app, _clock = client
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.links import sign_action

    ctx = app.state.ctx
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ref = ConversationRef(
        conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    item = await ctx.ledger.create_item(
        ref, ItemDraft(type="callback", urgency="normal", contact=ContactInfo(name="Dana"))
    )
    token = sign_action(ctx.settings.secret_key, item.id, "ack", "skincentrix")

    expected = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
    page = await c.get(f"/a/{token}")
    assert page.status_code == 200
    assert page.headers["content-security-policy"] == expected
    assert page.headers["referrer-policy"] == "no-referrer"

    done = await c.post(f"/a/{token}", data={"actor": "dana@clinic"})
    assert done.status_code == 200
    assert done.headers["content-security-policy"] == expected
    assert done.headers["referrer-policy"] == "no-referrer"


# --- the scanners in CI --------------------------------------------------------------------


def _security_job() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "security" in workflow["jobs"], "CI has no secret and dependency scanning job"
    return workflow["jobs"]["security"]


def test_ci_scans_for_leaked_secrets():
    job = _security_job()
    runs = " ".join(step.get("run", "") for step in job["steps"])
    uses = " ".join(str(step.get("uses", "")) for step in job["steps"])
    assert "gitleaks" in runs or "gitleaks" in uses
    assert ".gitleaks.toml" in runs, "the scan must use the committed configuration"
    # Detecting a secret that was committed and then removed needs the history, and the
    # default checkout depth is one commit.
    checkout = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout and str(checkout[0].get("with", {}).get("fetch-depth")) == "0"


def test_ci_audits_the_python_and_node_dependencies():
    job = _security_job()
    runs = " ".join(step.get("run", "") for step in job["steps"])
    assert "pip-audit" in runs
    assert ".pip-audit-ignore" in runs, "accepted findings live in the allowlist file"
    # The npm gate wraps `npm audit` with the allowlist, and both node projects go through it.
    assert "npm-audit-gate.mjs portal" in runs
    assert "npm-audit-gate.mjs edge/sms-worker" in runs


def test_the_gitleaks_configuration_extends_the_defaults_and_explains_every_exception():
    config = tomllib.loads(GITLEAKS.read_text(encoding="utf-8"))
    assert config["extend"]["useDefault"] is True, "the default rule set is the floor"
    allowlists = config.get("allowlists") or (
        [config["allowlist"]] if "allowlist" in config else []
    )
    assert allowlists, "no allowlist means the two known fixtures fail every push"
    for entry in allowlists:
        assert entry.get("description"), "an exception without a reason is a hole"


def test_every_accepted_dependency_finding_carries_a_reason():
    lines = PIP_AUDIT_IGNORE.read_text(encoding="utf-8").splitlines()
    ids = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    assert ids, "the nltk advisory has no fix yet and must be listed explicitly"
    for advisory in ids:
        assert advisory.split("-")[0] in {"PYSEC", "GHSA", "CVE"}, advisory
    # Every id is introduced by a comment block, so nobody can add one silently.
    for index, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("#"):
            assert index > 0 and lines[index - 1].strip().startswith("#"), line

    allow = json.loads(NPM_AUDIT_ALLOW.read_text(encoding="utf-8"))
    assert allow["advisories"], "the Wasp build tree ships four high advisories today"
    for entry in allow["advisories"]:
        assert entry["id"] and entry["package"] and entry["reason"]
