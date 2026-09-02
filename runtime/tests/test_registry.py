from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


async def test_import_creates_version_and_resolves_numbers(sf, fixed_clock):
    from spatalk.tenants.registry import TenantRegistry
    reg = TenantRegistry(sf, fixed_clock)
    tenant_id, version = await reg.import_bundle(BUNDLE, created_by="test")
    assert (tenant_id, version) == ("skincentrix", 1)
    _, version2 = await reg.import_bundle(BUNDLE, created_by="test")
    assert version2 == 2
    await reg.add_number("+19055550100", "skincentrix", "voice")
    assert await reg.resolve_number("+19055550100") == "skincentrix"
    assert await reg.resolve_number("+10000000000") is None


async def test_get_returns_latest_config_and_caches(sf, fixed_clock):
    from spatalk.tenants.registry import TenantRegistry
    reg = TenantRegistry(sf, fixed_clock)
    await reg.import_bundle(BUNDLE, created_by="test")
    cfg = await reg.get("skincentrix")
    assert cfg.name == "Skincentrix"
    changed = cfg.model_copy(update={"name": "Skincentrix Beauty Bar"})
    await reg.import_config(changed, created_by="test")
    assert (await reg.get("skincentrix")).name == "Skincentrix"          # cached
    reg.invalidate("skincentrix")
    assert (await reg.get("skincentrix")).name == "Skincentrix Beauty Bar"
