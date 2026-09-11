async def test_the_calls_signals_are_stored_with_it(sf, registry):
    """One row a call, counts and a capped tail. It is the only rung-0 artefact that outlives
    the process, and phase C's trouble score reads nothing else (model-words memo, §6)."""
    from sqlalchemy import select

    from spatalk.conversations import end_conversation, start_conversation
    from spatalk.models import Conversation
    from spatalk.ops.signals import SignalLog

    cid = await start_conversation(sf, "skincentrix", "voice", "call-sig", "+19055550101")
    log = SignalLog()
    log.next_turn()
    log.record("repeat", script="ask_service")
    log.record("tool_rejected", reason="not_offered", tool="give_name")
    await end_conversation(sf, cid, band=2, latency_ms=[900], signals=log.as_json())
    async with sf() as s:
        conv = (
            await s.scalars(select(Conversation).where(Conversation.id == cid))
        ).one()
        assert conv.signals["counts"] == {"repeat": 1, "tool_rejected": 1, "bargein_repeat": 0}
        assert conv.signals["turns"] == 1
        assert all(set(x["detail"]) <= {"script", "reason", "tool"} for x in conv.signals["signals"])


async def test_conversation_lifecycle_and_usage(sf, registry):
    from spatalk.conversations import (append_message, end_conversation, get_transcript,
                                       record_usage, start_conversation)
    cid = await start_conversation(sf, "skincentrix", "voice", "call-1", "+19055550101")
    await append_message(sf, cid, "user", "hi")
    await append_message(sf, cid, "assistant", "hello")
    await record_usage(sf, "skincentrix", cid, "voice", "soniox", "stt_seconds", 42.5)
    await end_conversation(sf, cid, band=1, latency_ms=[610, 720])
    msgs = await get_transcript(sf, cid)
    assert [m.role for m in msgs] == ["user", "assistant"]
