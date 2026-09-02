import uuid
import pytest


def test_stream_token_roundtrip_and_expiry():
    from itsdangerous import SignatureExpired
    from spatalk.voice.tokens import sign_stream_token, verify_stream_token
    cid = uuid.uuid4()
    tok = sign_stream_token("s", cid, "skincentrix", "+19055550101")
    claim = verify_stream_token("s", tok)
    assert (claim.conversation_id, claim.tenant_id, claim.caller) == (cid, "skincentrix", "+19055550101")
    with pytest.raises(SignatureExpired):
        verify_stream_token("s", tok, max_age_seconds=-1)
