"""Operator command line: import and export tenant bundles, map numbers, list open items."""

from __future__ import annotations

import asyncio
import json
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
app.add_typer(tenant, name="tenant")
app.add_typer(numbers, name="numbers")
app.add_typer(items, name="items")
app.add_typer(edge, name="edge")
app.add_typer(texml, name="texml")
app.add_typer(invoices, name="invoices")
app.add_typer(cost, name="cost")


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
    import uvicorn

    uvicorn.run("spatalk.http.app:create_default_app", host=host, port=port, factory=True)


# --- edge worker (text-channels plan, Task B6) --------------------------------
# The worker answers an SMS when this runtime is unreachable, so the wording it answers
# with has to be in its KV before the outage, not fetched during one. `sync-texts` is what
# puts it there: one entry per tenant that has an SMS number, carrying that tenant's own
# `scripts.offline_reply` and nothing generated.

TENANT_TEXTS_PATH = "/admin/tenant-texts"


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


@edge.command("sync-texts")
def edge_sync_texts(worker_url: str, key: str = "", dry_run: bool = False):
    """Send every tenant's offline auto-reply to the SMS worker's KV."""
    settings = get_settings()
    ctx = build_context(settings)
    if dry_run:
        texts = asyncio.run(collect_tenant_texts(ctx))
    else:
        texts = asyncio.run(sync_tenant_texts(ctx, worker_url, key or settings.edge_shared_key))
    for number, entry in texts.items():
        typer.echo(f"{number} -> {entry['tenant_id']}: {entry['text']}")
    typer.echo(f"{len(texts)} number(s) {'collected' if dry_run else 'synced'}")


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
