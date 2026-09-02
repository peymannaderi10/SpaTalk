from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.clock import Clock
from spatalk.models import Tenant, TenantConfigVersion, TenantNumber
from spatalk.tenants.bundle import config_from_json, config_to_json, load_bundle
from spatalk.tenants.schema import TenantConfig


class TenantRegistry:
    def __init__(self, sf: async_sessionmaker, clock: Clock, ttl_seconds: float = 30.0):
        self._sf, self._clock, self._ttl = sf, clock, ttl_seconds
        self._cache: dict[str, tuple[float, TenantConfig]] = {}

    async def import_config(self, cfg: TenantConfig, created_by: str) -> int:
        async with self._sf() as s, s.begin():
            await s.execute(
                insert(Tenant)
                .values(id=cfg.id, name=cfg.name)
                .on_conflict_do_update(index_elements=[Tenant.id], set_={"name": cfg.name})
            )
            current = await s.scalar(
                select(func.max(TenantConfigVersion.version)).where(
                    TenantConfigVersion.tenant_id == cfg.id
                )
            )
            version = (current or 0) + 1
            s.add(
                TenantConfigVersion(
                    tenant_id=cfg.id,
                    version=version,
                    config=config_to_json(cfg),
                    created_by=created_by,
                )
            )
            for n in cfg.voice_numbers:
                await self._upsert_number(s, n, cfg.id, "voice")
            if cfg.sms_from_number:
                await self._upsert_number(s, cfg.sms_from_number, cfg.id, "sms")
        # The cache is not cleared here: a write in one process cannot clear another
        # process's cache, so every reader waits out the same TTL (flows.md 7.3,
        # "registry cache expires within 30 s"). Callers that need the new version
        # immediately call invalidate().
        return version

    async def import_bundle(self, path: Path, created_by: str) -> tuple[str, int]:
        cfg = load_bundle(path)
        return cfg.id, await self.import_config(cfg, created_by)

    async def get(self, tenant_id: str) -> TenantConfig:
        hit = self._cache.get(tenant_id)
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        async with self._sf() as s:
            row = await s.scalar(
                select(TenantConfigVersion)
                .where(TenantConfigVersion.tenant_id == tenant_id)
                .order_by(TenantConfigVersion.version.desc())
                .limit(1)
            )
        if row is None:
            raise KeyError(f"unknown tenant {tenant_id}")
        cfg = config_from_json(row.config)
        self._cache[tenant_id] = (time.monotonic(), cfg)
        return cfg

    def invalidate(self, tenant_id: str) -> None:
        self._cache.pop(tenant_id, None)

    async def resolve_number(self, number: str) -> str | None:
        async with self._sf() as s:
            return await s.scalar(
                select(TenantNumber.tenant_id).where(TenantNumber.number == number)
            )

    async def add_number(self, number: str, tenant_id: str, kind: str) -> None:
        async with self._sf() as s, s.begin():
            await self._upsert_number(s, number, tenant_id, kind)

    async def list_tenants(self) -> list[str]:
        async with self._sf() as s:
            return list((await s.scalars(select(Tenant.id).order_by(Tenant.id))).all())

    @staticmethod
    async def _upsert_number(s, number: str, tenant_id: str, kind: str) -> None:
        await s.execute(
            insert(TenantNumber)
            .values(number=number, tenant_id=tenant_id, kind=kind)
            .on_conflict_do_update(
                index_elements=[TenantNumber.number],
                set_={"tenant_id": tenant_id, "kind": kind},
            )
        )
