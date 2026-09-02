from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.models import Job

Handler = Callable[[dict, "JobContext"], Awaitable[None]]
_HANDLERS: dict[str, Handler] = {}


@dataclass
class JobContext:
    """App-wide dependencies. Also passed to voice calls (needs sms) and HTTP routes."""

    sf: async_sessionmaker
    clock: Any
    registry: Any
    ledger: Any
    delivery: Any
    settings: Any
    sms: Any = None
    # Text channels (text-channels plan, Task B2): the LLM client the shared
    # TextConversationService drives. Voice builds its own inside the Pipecat pipeline.
    llm: Any = None


def register_handler(kind: str):
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return deco


async def enqueue(
    sf: async_sessionmaker, kind: str, payload: dict, run_at: datetime | None = None
) -> int:
    async with sf() as s, s.begin():
        job = Job(kind=kind, payload=payload, **({"run_at": run_at} if run_at else {}))
        s.add(job)
        await s.flush()
        return job.id


async def get_job(sf: async_sessionmaker, job_id: int) -> Job | None:
    async with sf() as s:
        return await s.get(Job, job_id)


# A job enqueued without an explicit `run_at` is due immediately: both `run_at` and
# `created_at` default to the database's `now()`, which is the same transaction timestamp,
# so `run_at = created_at` marks "never scheduled". Anything scheduled for later carries an
# explicit `run_at` and becomes due only when the application clock reaches it.
CLAIM_SQL = text("""
    SELECT id FROM runtime.jobs
    WHERE state = 'queued' AND (run_at <= :now OR run_at = created_at)
    ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED
""")


async def run_once(sf: async_sessionmaker, ctx: JobContext, limit: int = 10) -> int:
    now = ctx.clock.now()
    processed = 0
    async with sf() as s, s.begin():
        ids = [r[0] for r in (await s.execute(CLAIM_SQL, {"now": now, "limit": limit})).all()]
        jobs = list((await s.scalars(select(Job).where(Job.id.in_(ids)))).all()) if ids else []
        for job in jobs:
            processed += 1
            handler = _HANDLERS.get(job.kind)
            try:
                if handler is None:
                    raise RuntimeError(f"no handler for {job.kind}")
                await handler(job.payload, ctx)
                job.state = "done"
            except Exception as e:  # noqa: BLE001
                job.attempts += 1
                job.last_error = f"{type(e).__name__}: {e}"[:2000]
                if job.attempts >= job.max_attempts:
                    job.state = "dead"
                    logger.error("job {} {} dead: {}", job.id, job.kind, job.last_error)
                else:
                    job.run_at = now + timedelta(seconds=30 * (2**job.attempts))
    return processed


async def run_worker_forever(
    sf: async_sessionmaker, ctx: JobContext, poll_seconds: float = 2.0
) -> None:
    while True:
        try:
            n = await run_once(sf, ctx)
        except Exception as e:  # noqa: BLE001
            logger.exception("worker loop error: {}", e)
            n = 0
        await asyncio.sleep(0.05 if n else poll_seconds)
