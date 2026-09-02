import pytest


def test_sign_and_verify_roundtrip():
    from spatalk.ledger.links import sign_action, verify_action
    tok = sign_action("s3cret", 42, "ack", "skincentrix")
    claim = verify_action("s3cret", tok)
    assert (claim.item_id, claim.action, claim.tenant_id) == (42, "ack", "skincentrix")


def test_tampered_or_wrong_secret_fails():
    from itsdangerous import BadSignature
    from spatalk.ledger.links import sign_action, verify_action
    tok = sign_action("s3cret", 42, "ack", "skincentrix")
    with pytest.raises(BadSignature):
        verify_action("other", tok)
    with pytest.raises(BadSignature):
        verify_action("s3cret", tok[:-3] + "abc")
