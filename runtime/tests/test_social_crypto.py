"""Task D1: a Meta access token is encrypted at rest, or it is not stored at all.

Every test names the behaviour the plan lists. The interesting rules are the refusals: an
absent or malformed key raises instead of quietly writing a token in the clear, and a token
written under a rotated key fails loudly rather than decrypting to nonsense.
"""

import pytest
from cryptography.fernet import Fernet

KEY = Fernet.generate_key().decode()
ROTATED_KEY = Fernet.generate_key().decode()
TOKEN = "IGQVJXsecret-long-lived-token"


def test_encrypt_then_decrypt_round_trips_the_token():
    from spatalk.social.crypto import decrypt_token, encrypt_token

    ciphertext = encrypt_token(TOKEN, KEY)
    assert TOKEN not in ciphertext
    assert decrypt_token(ciphertext, KEY) == TOKEN


def test_the_same_token_encrypts_differently_every_time():
    from spatalk.social.crypto import encrypt_token

    assert encrypt_token(TOKEN, KEY) != encrypt_token(TOKEN, KEY)


def test_decrypting_with_a_rotated_key_raises():
    from spatalk.social.crypto import TokenDecryptionError, decrypt_token, encrypt_token

    ciphertext = encrypt_token(TOKEN, KEY)
    with pytest.raises(TokenDecryptionError):
        decrypt_token(ciphertext, ROTATED_KEY)


def test_a_corrupt_ciphertext_raises():
    from spatalk.social.crypto import TokenDecryptionError, decrypt_token

    with pytest.raises(TokenDecryptionError):
        decrypt_token("not-a-fernet-ciphertext", KEY)


def test_a_missing_key_raises_rather_than_storing_plaintext():
    from spatalk.social.crypto import TokenEncryptionError, decrypt_token, encrypt_token

    with pytest.raises(TokenEncryptionError):
        encrypt_token(TOKEN, "")
    with pytest.raises(TokenEncryptionError):
        decrypt_token("anything", "")


def test_a_malformed_key_raises():
    from spatalk.social.crypto import TokenEncryptionError, encrypt_token

    with pytest.raises(TokenEncryptionError):
        encrypt_token(TOKEN, "this-is-not-a-fernet-key")


def test_the_key_defaults_to_the_configured_setting(monkeypatch):
    from spatalk.settings import get_settings
    from spatalk.social.crypto import decrypt_token, encrypt_token

    monkeypatch.setenv("META_TOKEN_ENCRYPTION_KEY", KEY)
    get_settings.cache_clear()
    try:
        assert decrypt_token(encrypt_token(TOKEN)) == TOKEN
    finally:
        get_settings.cache_clear()
