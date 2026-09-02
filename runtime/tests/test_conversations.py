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
