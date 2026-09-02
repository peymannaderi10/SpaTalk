"""Signed, short-lived claims for the Telnyx media WebSocket.

The TeXML response is public in the sense that anything Telnyx can reach could try to
open the socket. The token is what proves which conversation and tenant the audio
belongs to, and it expires in five minutes (spec: `WS /ws/{token}`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from itsdangerous import URLSafeTimedSerializer

SALT = "media-stream"


@dataclass(frozen=True)
class StreamClaim:
    conversation_id: uuid.UUID
    tenant_id: str
    caller: str | None


def sign_stream_token(
    secret: str, conversation_id: uuid.UUID, tenant_id: str, caller: str | None
) -> str:
    return URLSafeTimedSerializer(secret, salt=SALT).dumps(
        {"c": str(conversation_id), "t": tenant_id, "f": caller}
    )


def verify_stream_token(secret: str, token: str, max_age_seconds: int = 300) -> StreamClaim:
    d = URLSafeTimedSerializer(secret, salt=SALT).loads(token, max_age=max_age_seconds)
    return StreamClaim(
        conversation_id=uuid.UUID(d["c"]), tenant_id=d["t"], caller=d.get("f")
    )
