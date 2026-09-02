"""Operator command line: import and export tenant bundles, map numbers, list open items."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from spatalk.http.app import build_context
from spatalk.settings import get_settings
from spatalk.tenants.bundle import export_bundle

app = typer.Typer(help="spatalk runtime operations")
tenant = typer.Typer()
numbers = typer.Typer()
items = typer.Typer()
app.add_typer(tenant, name="tenant")
app.add_typer(numbers, name="numbers")
app.add_typer(items, name="items")


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
