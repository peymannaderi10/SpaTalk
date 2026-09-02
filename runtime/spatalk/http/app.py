"""Application assembly: one place that wires ports to routes and background tasks."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, WebSocket
from loguru import logger

from spatalk import jobs
from spatalk.clock import SystemClock
from spatalk.db import make_engine, make_session_factory
from spatalk.http import actions, internal, slack, slack_events
from spatalk.http.ratelimit import install_rate_limits
from spatalk.ledger.delivery import make_delivery, schedule_item_delivery
from spatalk.ledger.items import PgLedger
from spatalk.ledger.scheduler import run_scheduler_forever
from spatalk.ops import alerts  # monitoring and error reporting (operations plan, Task E7)
from spatalk.settings import Settings, get_settings
from spatalk.social import instagram as social_instagram
from spatalk.social import messenger as social_messenger
from spatalk.sms import TelnyxSms
from spatalk.tenants.registry import TenantRegistry
from spatalk.text import chat as text_chat
from spatalk.text import sms as text_sms
from spatalk.text.service import make_text_llm
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
        # Slack bot when a token is configured, incoming webhook otherwise (Task B5).
        delivery=make_delivery(settings),
        settings=settings,
        sms=TelnyxSms(settings.telnyx_api_key),
        # Text channels (Task B2): the shared TextConversationService drives this client.
        llm=make_text_llm(settings),
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
    # --- monitoring and error reporting (operations plan, Task E7) ---
    # Both are no-ops unless configured: LOG_FORMAT=json switches loguru to one JSON object
    # per line, SENTRY_DSN turns on error reporting with the PII scrubbers attached. Some
    # tests build the app purely to inspect its routes and pass no context at all.
    if getattr(ctx, "settings", None) is not None:
        alerts.configure_logging(ctx.settings)
        alerts.init_sentry(ctx.settings)
    # --- end monitoring ---
    # --- security hardening (operations plan, Task E8) ---
    # In front of every HTTP route, before any router: per-IP token buckets, 429 with
    # Retry-After. `/healthz`, `/internal/*` and the media socket are not in any bin.
    install_rate_limits(app)
    # --- end security hardening ---
    attach_router(app, texml.router)
    attach_router(app, actions.router)
    attach_router(app, slack.router)
    attach_router(app, slack_events.router)  # human takeover (Task B5)
    attach_router(app, text_sms.router)   # text channels (Task B2)
    attach_router(app, text_chat.router)  # web chat widget (Task B4)
    attach_router(app, internal.router)   # the portal's only way in (portal plan, Task C3)
    attach_router(app, social_instagram.router)  # instagram (instagram plan, Task D2)
    attach_router(app, social_messenger.router)  # facebook page (instagram plan, Task D3)

    @app.get("/healthz")
    async def healthz():
        """Unauthenticated: the uptime monitor and the deploy check both read it.

        It says what is running and what configuration each tenant is on; it never
        exposes a caller, a transcript or a key.

        The queue and scheduler fields are the operations plan's Task E7: an uptime monitor
        that only checks the port cannot tell a serving process from a working one, so it
        keyword-matches `"ok":true` and `"dead_jobs":0` here instead.
        """
        return {
            "ok": True,
            "tenants": await ctx.registry.list_tenants(),
            "config_versions": await internal.config_versions(ctx.sf),
            "commit": ctx.settings.git_commit,
            # --- monitoring (operations plan, Task E7) ---
            **await alerts.health_snapshot(ctx),
        }

    @app.websocket("/ws/{token}")
    async def media(websocket: WebSocket, token: str):
        await run_call(websocket, token, ctx)

    return app


def create_default_app() -> FastAPI:
    return create_app(build_context(get_settings()))
