"""Operator command line: import and export tenant bundles, map numbers, list open items."""

from __future__ import annotations

import asyncio
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
app.add_typer(tenant, name="tenant")
app.add_typer(numbers, name="numbers")
app.add_typer(items, name="items")
app.add_typer(edge, name="edge")


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
