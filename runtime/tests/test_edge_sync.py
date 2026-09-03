"""Task B6: `spatalk edge sync-texts` and the edge worker's CI job.

The Cloudflare worker answers a text when the runtime is unreachable, so the wording it
answers with cannot come from the runtime at that moment: it has to be in the worker's KV
before the outage. This command is what puts it there — one entry per tenant that has an
SMS number, carrying that tenant's own `scripts.offline_reply`, pushed to the worker's
`PUT /admin/tenant-texts` with `EDGE_SHARED_KEY`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKER_URL = "https://sms.example.workers.dev"
EDGE_KEY = "edge-shared-key"
SMS_FROM = "+18885550100"

OFFLINE = (
    "Thanks for texting Skincentrix. We'll reply shortly. "
    "To book now: https://skincentrix.janeapp.com/locations/skincentrix"
)


@pytest.fixture
async def ctx(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.settings import Settings

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=None,
        delivery=MemoryDelivery(),
        settings=Settings(_env_file=None, secret_key="s3cret", edge_shared_key=EDGE_KEY),
    )


async def _take_the_tenants_sms_number_away(registry):
    """The bundle carries a messaging number since S1, so "no number" is now said aloud."""
    await _give_the_tenant_an_sms_number(registry, None)


async def _give_the_tenant_an_sms_number(registry, number: str | None = SMS_FROM):
    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": number}), "test")
    registry.invalidate("skincentrix")


def _recording_client(status: int = 200):
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"ok": status == 200, "count": 1})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


# --- what gets pushed ---------------------------------------------------------


async def test_the_payload_carries_one_entry_per_tenant_with_an_sms_number(ctx, registry):
    from spatalk.cli import collect_tenant_texts

    await _give_the_tenant_an_sms_number(registry)
    payload = await collect_tenant_texts(ctx)
    assert payload == {
        SMS_FROM: {"tenant_id": "skincentrix", "from": SMS_FROM, "text": OFFLINE}
    }


async def test_a_tenant_without_an_sms_number_is_skipped(ctx, registry):
    from spatalk.cli import collect_tenant_texts

    await _take_the_tenants_sms_number_away(registry)
    assert await collect_tenant_texts(ctx) == {}


async def test_the_text_is_the_tenants_offline_reply_script_rendered(ctx, registry):
    from spatalk.cli import collect_tenant_texts

    await _give_the_tenant_an_sms_number(registry)
    cfg = await registry.get("skincentrix")
    text = (await collect_tenant_texts(ctx))[SMS_FROM]["text"]
    assert text == cfg.scripts.offline_reply.format(
        name=cfg.name, booking_url=cfg.booking_url_default
    )
    assert "{" not in text and cfg.name in text


# --- the push -----------------------------------------------------------------


async def test_sync_puts_the_payload_to_the_worker_admin_endpoint_with_the_edge_key(ctx, registry):
    from spatalk.cli import sync_tenant_texts

    await _give_the_tenant_an_sms_number(registry)
    http, seen = _recording_client()
    async with http:
        pushed = await sync_tenant_texts(ctx, WORKER_URL, EDGE_KEY, http=http)
    assert list(pushed) == [SMS_FROM]
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "PUT"
    assert str(request.url) == f"{WORKER_URL}/admin/tenant-texts"
    assert request.headers["X-Edge-Key"] == EDGE_KEY
    assert json.loads(request.content.decode()) == pushed


async def test_sync_trims_a_trailing_slash_from_the_worker_url(ctx, registry):
    from spatalk.cli import sync_tenant_texts

    await _give_the_tenant_an_sms_number(registry)
    http, seen = _recording_client()
    async with http:
        await sync_tenant_texts(ctx, WORKER_URL + "/", EDGE_KEY, http=http)
    assert str(seen[0].url) == f"{WORKER_URL}/admin/tenant-texts"


async def test_sync_refuses_without_an_edge_key(ctx, registry):
    from spatalk.cli import sync_tenant_texts

    await _give_the_tenant_an_sms_number(registry)
    http, seen = _recording_client()
    async with http:
        with pytest.raises(ValueError, match="EDGE_SHARED_KEY"):
            await sync_tenant_texts(ctx, WORKER_URL, "", http=http)
    assert seen == [], "nothing may be pushed unauthenticated"


async def test_sync_raises_when_the_worker_rejects_the_push(ctx, registry):
    from spatalk.cli import sync_tenant_texts

    await _give_the_tenant_an_sms_number(registry)
    http, _seen = _recording_client(status=401)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await sync_tenant_texts(ctx, WORKER_URL, EDGE_KEY, http=http)


async def test_sync_sends_nothing_when_no_tenant_has_an_sms_number(ctx, registry):
    from spatalk.cli import sync_tenant_texts

    await _take_the_tenants_sms_number_away(registry)
    http, seen = _recording_client()
    async with http:
        assert await sync_tenant_texts(ctx, WORKER_URL, EDGE_KEY, http=http) == {}
    assert seen == []


def test_the_cli_exposes_edge_sync_texts():
    from typer.testing import CliRunner

    from spatalk.cli import app

    result = CliRunner().invoke(app, ["edge", "sync-texts", "--help"])
    assert result.exit_code == 0
    assert "sync-texts" in result.output


# --- CI runs the worker's own tests -------------------------------------------


def test_ci_runs_the_edge_worker_tests():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    jobs = workflow["jobs"]
    assert "edge" in jobs, "the edge worker has no CI job"
    edge = jobs["edge"]
    runs = " ".join(step.get("run", "") for step in edge["steps"])
    assert "npm ci" in runs and "npm test" in runs
    node = [s for s in edge["steps"] if str(s.get("uses", "")).startswith("actions/setup-node")]
    assert node, "the edge job needs a node runtime"
    assert str(node[0]["with"]["node-version"]) == "22"
    working = [s.get("working-directory") for s in edge["steps"] if "run" in s]
    assert all(w == "edge/sms-worker" for w in working if w is not None)


# --- the permanent block list rides along (plan F, F3) --------------------------


async def test_only_permanent_blocks_are_collected_for_the_worker(ctx, registry, fixed_clock):
    from datetime import timedelta

    from spatalk.cli import collect_blocked_numbers
    from spatalk.text.flood import block, mute

    cfg = await registry.get("skincentrix")
    await block(ctx, cfg, "+19055550188", "cli:test")
    await mute(
        ctx, cfg, "+19055550189", fixed_clock.now() + timedelta(hours=1), "flood", "system:flood"
    )
    assert await collect_blocked_numbers(ctx) == ["+19055550188"]


async def test_sync_pushes_the_block_list_even_when_empty_so_the_worker_prunes(ctx, registry):
    from spatalk.cli import sync_blocked_numbers

    http, seen = _recording_client()
    async with http:
        pushed = await sync_blocked_numbers(ctx, WORKER_URL, EDGE_KEY, http=http)
    assert pushed == [] and len(seen) == 1
    request = seen[0]
    assert request.method == "PUT"
    assert str(request.url) == f"{WORKER_URL}/admin/blocked-numbers"
    assert request.headers["X-Edge-Key"] == EDGE_KEY
    assert json.loads(request.content.decode()) == {"numbers": []}
