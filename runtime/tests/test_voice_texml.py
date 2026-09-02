import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.settings import Settings
    from spatalk.voice.texml import router
    app = FastAPI()
    app.include_router(router)
    app.state.ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=None, delivery=None,
                                    settings=Settings(secret_key="s", media_ws_host="media.test"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c


async def test_texml_returns_stream_for_known_number(client, sf):
    from sqlalchemy import select
    from spatalk.models import Conversation
    r = await client.post("/telnyx/texml", data={"From": "+19055550101", "To": "+19055550100", "CallSid": "abc"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert '<Stream url="wss://media.test/ws/' in r.text and 'bidirectionalMode="rtp"' in r.text
    async with sf() as s:
        conv = (await s.scalars(select(Conversation))).one()
    assert conv.tenant_id == "skincentrix" and conv.caller == "+19055550101" and conv.external_ref == "abc"


async def test_texml_unknown_number_hangs_up(client):
    r = await client.post("/telnyx/texml", data={"From": "+1", "To": "+10000000000", "CallSid": "x"})
    assert r.status_code == 200 and "<Hangup" in r.text
