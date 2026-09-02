from httpx import ASGITransport, AsyncClient


async def test_healthz_and_routes_present(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=PgLedger(sf, fixed_clock),
                          delivery=MemoryDelivery(), settings=Settings(secret_key="s"))
    app = create_app(ctx, start_background=False)
    paths = {r.path for r in app.routes}
    assert {"/healthz", "/telnyx/texml", "/ws/{token}", "/a/{token}", "/slack/interactions"} <= paths
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code == 200 and r.json()["tenants"] == ["skincentrix"]


def test_cli_imports():
    from spatalk.cli import app
    assert app is not None
