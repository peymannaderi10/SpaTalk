"""Meta access tokens at rest.

A Meta access token is a bearer credential for somebody else's Instagram account or Facebook
Page: whoever holds it can read and send messages as that business. It is encrypted with
Fernet before it reaches a row, decrypted only in the moment a Graph call needs it, and never
logged. There is no path that writes one in the clear: with no key configured, encryption
raises rather than falling back to plaintext.

The key is ``META_TOKEN_ENCRYPTION_KEY`` (a urlsafe base64 32-byte Fernet key, e.g.
``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``).
Rotating it makes every stored token undecryptable on purpose: the tenants reconnect.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from spatalk.settings import get_settings


class TokenEncryptionError(RuntimeError):
    """No usable ``META_TOKEN_ENCRYPTION_KEY``: missing, or not a Fernet key."""


class TokenDecryptionError(RuntimeError):
    """The ciphertext was not written by this key (rotation), or it is corrupt."""


def _fernet(key: str | None) -> Fernet:
    material = key if key is not None else get_settings().meta_token_encryption_key
    if not material:
        raise TokenEncryptionError(
            "META_TOKEN_ENCRYPTION_KEY is not set; refusing to handle a Meta token in the clear"
        )
    try:
        return Fernet(material.encode() if isinstance(material, str) else material)
    except (ValueError, TypeError) as e:  # bad length, bad base64
        raise TokenEncryptionError(
            f"META_TOKEN_ENCRYPTION_KEY is not a valid Fernet key ({type(e).__name__})"
        ) from e


def encrypt_token(token: str, key: str | None = None) -> str:
    """Ciphertext for a Meta access token. Never returns the token, never logs it."""
    return _fernet(key).encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str, key: str | None = None) -> str:
    """The token back. Raises rather than returning anything when the key does not match."""
    try:
        return _fernet(key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise TokenDecryptionError(
            "stored Meta token could not be decrypted with the configured key"
        ) from e
