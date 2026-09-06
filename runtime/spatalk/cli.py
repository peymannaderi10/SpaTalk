"""Operator command line: import and export tenant bundles, map numbers, list open items."""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import re
from pathlib import Path

import httpx
import typer

from spatalk.brain.renderer import render_script
from spatalk.http.app import build_context
from spatalk.settings import get_settings
from spatalk.tenants.bundle import export_bundle

app = typer.Typer(help="spatalk runtime operations")
tenant = typer.Typer()
numbers = typer.Typer()
items = typer.Typer()
edge = typer.Typer()
texml = typer.Typer()          # carrier-side TeXML the founder pastes (operations plan, E1)
invoices = typer.Typer()       # what each provider actually billed (operations plan, E9)
cost = typer.Typer()           # metered cost against those invoices (operations plan, E9)
sms = typer.Typer()            # the SMS block list (plan F, F2)
app.add_typer(tenant, name="tenant")
app.add_typer(numbers, name="numbers")
app.add_typer(items, name="items")
app.add_typer(edge, name="edge")
app.add_typer(texml, name="texml")
app.add_typer(invoices, name="invoices")
app.add_typer(cost, name="cost")
app.add_typer(sms, name="sms")


def _ctx():
    return build_context(get_settings())


@tenant.command("import")
def tenant_import(bundle_dir: Path, by: str = "cli"):
    ctx = _ctx()
    tenant_id, version = asyncio.run(ctx.registry.import_bundle(bundle_dir, created_by=by))
    typer.echo(f"{tenant_id} -> version {version}")


@tenant.command("export")
def tenant_export(tenant_id: str, out_dir: Path):
    ctx = _ctx()
    cfg = asyncio.run(ctx.registry.get(tenant_id))
    export_bundle(cfg, out_dir)
    typer.echo(f"wrote {out_dir}")


@numbers.command("add")
def numbers_add(number: str, tenant_id: str, kind: str = "voice"):
    ctx = _ctx()
    asyncio.run(ctx.registry.add_number(number, tenant_id, kind))
    typer.echo(f"{number} -> {tenant_id} ({kind})")


@items.command("list")
def items_list(tenant_id: str):
    ctx = _ctx()
    for it in asyncio.run(ctx.ledger.list_open(tenant_id)):
        typer.echo(
            f"#{it.id} {it.state:<12} {it.urgency:<6} {it.type:<28} "
            f"due {it.due_at:%Y-%m-%d %H:%M} {it.contact_name or ''} {it.contact_phone or ''}"
        )


# --- sms block list (plan F, F2) ---------------------------------------------------------
# The work is in async functions that return (exit code, lines) so the tests can drive them on
# the test loop; the typer commands only run them and print.
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")


def _e164_or_exit(number: str) -> str:
    if not E164_RE.match(number):
        typer.echo(f"{number} is not an E.164 number (expected +1XXXXXXXXXX)")
        raise typer.Exit(1)
    return number


async def sms_block_work(ctx, tenant_id: str, number: str, created_by: str) -> tuple[int, str]:
    from spatalk.text.flood import block
    from spatalk.text.staff import staff_numbers

    cfg = await ctx.registry.get(tenant_id)
    if number in staff_numbers(cfg):
        return 1, f"{number} is a staff number for {tenant_id}; not blocked"
    await block(ctx, cfg, number, created_by=created_by)
    return 0, f"{number} blocked for {tenant_id}"


async def sms_unblock_work(ctx, tenant_id: str, number: str) -> tuple[int, str]:
    from spatalk.text.flood import unblock

    if await unblock(ctx, tenant_id, number):
        return 0, f"{number} removed from {tenant_id}'s block list"
    return 1, f"no block or mute for {number} on {tenant_id}"


async def sms_blocks_work(ctx, tenant_id: str) -> tuple[int, str]:
    from spatalk.text.flood import list_blocks

    rows = await list_blocks(ctx, tenant_id)
    if not rows:
        return 0, f"no blocked or muted numbers for {tenant_id}"
    lines = []
    for b in rows:
        until = "permanent" if b.until is None else f"until {b.until:%Y-%m-%d %H:%M %Z}"
        lines.append(
            f"{b.phone:<16} {until:<28} {b.reason:<7} by {b.created_by} "
            f"at {b.created_at:%Y-%m-%d %H:%M}"
        )
    return 0, "\n".join(lines)


def _finish(result: tuple[int, str]) -> None:
    code, text = result
    typer.echo(text)
    if code:
        raise typer.Exit(code)


@sms.command("block")
def sms_block(tenant_id: str, number: str):
    """Block a number for this tenant for good: its texts are stored, never answered."""
    number = _e164_or_exit(number)
    _finish(asyncio.run(sms_block_work(_ctx(), tenant_id, number, f"cli:{getpass.getuser()}")))


@sms.command("unblock")
def sms_unblock(tenant_id: str, number: str):
    """Lift a block or a flood mute on a number."""
    number = _e164_or_exit(number)
    _finish(asyncio.run(sms_unblock_work(_ctx(), tenant_id, number)))


@sms.command("blocks")
def sms_blocks(tenant_id: str):
    """List the numbers this tenant is not answering by SMS, and why."""
    _finish(asyncio.run(sms_blocks_work(_ctx(), tenant_id)))


@app.command()
def openapi(internal: bool = True, out: str = ""):
    """Print the runtime's OpenAPI document (default: only the portal's `/internal` API).

    `docs/contracts/runtime-internal.openapi.json` is this output; the portal generates its
    typed client from that file, so regenerating it is how a contract change is declared.
    """
    from spatalk.http.internal import openapi_document

    document = json.dumps(openapi_document(internal_only=internal), indent=2) + "\n"
    if out:
        Path(out).write_text(document, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(document, nl=False)


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Run the runtime.

    `.env` is exported into the process first, because the delivery job reads a staff
    number by environment-variable name, and a key whose value is a note stops the start:
    both are 2026-09-05 demo findings (`spatalk.settings.export_env_file`, `comment_valued`).
    """
    import uvicorn

    from spatalk.settings import comment_valued, export_env_file

    export_env_file()
    noted = comment_valued(os.environ)
    if noted:
        typer.echo(
            "refusing to start: "
            + ", ".join(noted)
            + " hold a note where a value goes (`KEY=   # note` is read as the note). "
            "Put the note on its own line above the key and start again."
        )
        raise typer.Exit(code=2)
    uvicorn.run("spatalk.http.app:create_default_app", host=host, port=port, factory=True)


# --- edge worker (text-channels plan, Task B6) --------------------------------
# The worker answers an SMS when this runtime is unreachable, so the wording it answers
# with has to be in its KV before the outage, not fetched during one. `sync-texts` is what
# puts it there: one entry per tenant that has an SMS number, carrying that tenant's own
# `scripts.offline_reply` and nothing generated.

TENANT_TEXTS_PATH = "/admin/tenant-texts"
BLOCKED_NUMBERS_PATH = "/admin/blocked-numbers"


async def collect_tenant_texts(ctx) -> dict[str, dict[str, str]]:
    """`{<inbound E.164>: {tenant_id, from, text}}` for every tenant with an SMS number."""
    now = ctx.clock.now()
    texts: dict[str, dict[str, str]] = {}
    for tenant_id in await ctx.registry.list_tenants():
        cfg = await ctx.registry.get(tenant_id)
        if not cfg.sms_from_number:
            continue
        texts[cfg.sms_from_number] = {
            "tenant_id": cfg.id,
            "from": cfg.sms_from_number,
            "text": render_script("offline_reply", cfg, now, urgent=False),
        }
    return texts


async def sync_tenant_texts(
    ctx, worker_url: str, key: str, http: httpx.AsyncClient | None = None
) -> dict[str, dict[str, str]]:
    """Push the offline wording to the worker's admin endpoint. Returns what was pushed."""
    if not key:
        raise ValueError(
            "no EDGE_SHARED_KEY: the worker's admin endpoint refuses an unauthenticated push"
        )
    texts = await collect_tenant_texts(ctx)
    if not texts:
        return {}
    client = http or httpx.AsyncClient(timeout=10)
    try:
        response = await client.put(
            worker_url.rstrip("/") + TENANT_TEXTS_PATH,
            json=texts,
            headers={"X-Edge-Key": key},
        )
        response.raise_for_status()
    finally:
        if http is None:
            await client.aclose()
    return texts


async def collect_blocked_numbers(ctx) -> list[str]:
    """Every permanently blocked number across tenants (plan F, F3).

    Flood mutes are left out on purpose: they expire on their own, and they only matter
    while the runtime is up to enforce them. The worker needs the blocks that must hold
    even during an outage.
    """
    from spatalk.text.flood import list_blocks

    numbers: set[str] = set()
    for tenant_id in await ctx.registry.list_tenants():
        for row in await list_blocks(ctx, tenant_id):
            if row.until is None:
                numbers.add(row.phone)
    return sorted(numbers)


async def sync_blocked_numbers(
    ctx, worker_url: str, key: str, http: httpx.AsyncClient | None = None
) -> list[str]:
    """Replace the worker's block list with ours. Pushed even when empty, so it prunes."""
    if not key:
        raise ValueError(
            "no EDGE_SHARED_KEY: the worker's admin endpoint refuses an unauthenticated push"
        )
    numbers = await collect_blocked_numbers(ctx)
    client = http or httpx.AsyncClient(timeout=10)
    try:
        response = await client.put(
            worker_url.rstrip("/") + BLOCKED_NUMBERS_PATH,
            json={"numbers": numbers},
            headers={"X-Edge-Key": key},
        )
        response.raise_for_status()
    finally:
        if http is None:
            await client.aclose()
    return numbers


@edge.command("sync-texts")
def edge_sync_texts(worker_url: str, key: str = "", dry_run: bool = False):
    """Send every tenant's offline auto-reply, and the permanent SMS block list, to the worker."""
    settings = get_settings()
    ctx = build_context(settings)
    edge_key = key or settings.edge_shared_key

    async def go() -> tuple[dict[str, dict[str, str]], list[str]]:
        if dry_run:
            return await collect_tenant_texts(ctx), await collect_blocked_numbers(ctx)
        texts = await sync_tenant_texts(ctx, worker_url, edge_key)
        blocked = await sync_blocked_numbers(ctx, worker_url, edge_key)
        return texts, blocked

    texts, blocked = asyncio.run(go())
    verb = "collected" if dry_run else "synced"
    for number, entry in texts.items():
        typer.echo(f"{number} -> {entry['tenant_id']}: {entry['text']}")
    typer.echo(f"{len(texts)} number(s) {verb}")
    for number in blocked:
        typer.echo(f"blocked {number}")
    typer.echo(f"{len(blocked)} blocked number(s) {verb}")


# --- carrier failover (operations plan, Task E1) ------------------------------
# When Telnyx cannot reach this runtime at all, it falls back to a TeXML Bin it hosts
# itself. The wording still has to be the tenant's own `scripts.failover`, so it is printed
# from the live config here and pasted into Telnyx by hand: `docs/runbooks/failover.md`.


@texml.command("failover-bin")
def texml_failover_bin(tenant_id: str):
    """Print the TeXML Bin body to paste as the TeXML application's Failover URL."""
    from spatalk.voice.texml import failover_bin

    ctx = _ctx()
    cfg = asyncio.run(ctx.registry.get(tenant_id))
    typer.echo(failover_bin(cfg, ctx.clock.now()))


# --- monthly cost reconciliation (operations plan, Task E9) -------------------
# The metered estimate is a model built on published prices, two of which the research
# could not verify. The invoice is the fact, and it arrives as an email to a human, so a
# human types it in: `spatalk invoices add telnyx 2026-08 41.50`. `cost report` then puts
# the two side by side and prints the drift.


@invoices.command("add")
def invoices_add(provider: str, month: str, amount_cad: float):
    """Record what one provider billed for one month, in Canadian dollars."""
    from spatalk.ops import cost_report as ops_cost

    ctx = _ctx()
    asyncio.run(ops_cost.add_invoice(ctx.sf, provider, month, amount_cad, now=ctx.clock.now()))
    typer.echo(f"{provider} {month}: CA${amount_cad:,.2f}")


@cost.command("report")
def cost_report_cmd(month: str):
    """Print the month's metered cost per provider and per tenant against the invoices."""
    from spatalk.ops import cost_report as ops_cost

    ctx = _ctx()
    report = asyncio.run(ops_cost.cost_report(ctx, month))
    for provider in ops_cost.providers_by_drift(report):
        drift = report["drift_pct"][provider]
        estimated = ops_cost.format_cad(report["per_provider_estimate"][provider])
        invoiced = ops_cost.format_cad(report["invoices"][provider])
        typer.echo(
            f"{provider:<20} estimated {estimated:>14}  invoiced {invoiced:>14}"
            + (f"  drift {drift:+.1f}%" if drift is not None else "")
        )
    for tenant_id, costs in sorted(report["per_tenant"].items()):
        typer.echo(
            f"{tenant_id:<20} cost {ops_cost.format_cad(costs['total']):>14}"
            f"  price {ops_cost.format_cad(report['price_cad']):>14}"
            f"  margin {report['per_tenant_margin_pct'][tenant_id]:.2f}%"
        )
