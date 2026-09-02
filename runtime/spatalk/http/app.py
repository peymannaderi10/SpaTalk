"""Application assembly: one place that wires ports to routes and background tasks."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, WebSocket
from loguru import logger

from spatalk import jobs
from spatalk.clock import SystemClock
from spatalk.db import make_engine, make_session_factory
from spatalk.http import actions, slack
from spatalk.ledger.delivery import HttpSlackEmailDelivery, schedule_item_delivery
from spatalk.ledger.items import PgLedger
from spatalk.ledger.scheduler import run_scheduler_forever
from spatalk.settings import Settings, get_settings
from spatalk.sms import TelnyxSms
from spatalk.tenants.registry import TenantRegistry
from spatalk.voice import texml
from spatalk.voice.pipeline import run_call


def build_context(settings: Settings) -> jobs.JobContext:
    """The production wiring. Tests build a JobContext with memory ports instead."""
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    clock = SystemClock()

    async def on_created(item, cfg):
        await schedule_item_delivery(sf, item, cfg)

    return jobs.JobContext(
        sf=sf,
        clock=clock,
        registry=TenantRegistry(sf, clock),
        ledger=PgLedger(sf, clock, on_created=on_created),
        delivery=HttpSlackEmailDelivery(settings),
        settings=settings,
        sms=TelnyxSms(settings.telnyx_api_key),
    )


def attach_router(app: FastAPI, router: APIRouter) -> None:
    """Put a router's real routes on the app.

    FastAPI 0.141 made `include_router` lazy: it appends one opaque `_IncludedRouter`
    to `app.routes` instead of the routes themselves, so `/telnyx/texml`, `/a/{token}`
    and `/slack/interactions` become invisible to anything that inspects `app.routes`
    (the route test here, and any operational route dump). None of our routers carry a
    prefix, tags or dependencies, so attaching the already-built routes is equivalent.
    """
    app.router.routes.extend(router.routes)
    mark_changed = getattr(app.router, "_mark_routes_changed", None)
    if mark_changed is not None:
        mark_changed()


def create_app(ctx: jobs.JobContext, start_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks: list[asyncio.Task] = []
        if start_background:
            tasks = [
                asyncio.create_task(jobs.run_worker_forever(ctx.sf, ctx)),
                asyncio.create_task(run_scheduler_forever(ctx)),
            ]
            logger.info("background worker and scheduler started")
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="spatalk runtime", lifespan=lifespan)
    app.state.ctx = ctx
    attach_router(app, texml.router)
    attach_router(app, actions.router)
    attach_router(app, slack.router)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "tenants": await ctx.registry.list_tenants()}

    @app.websocket("/ws/{token}")
    async def media(websocket: WebSocket, token: str):
        await run_call(websocket, token, ctx)

    return app


def create_default_app() -> FastAPI:
    return create_app(build_context(get_settings()))
