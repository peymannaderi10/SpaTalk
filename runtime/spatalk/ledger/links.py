from __future__ import annotations

from dataclasses import dataclass

from itsdangerous import URLSafeTimedSerializer

SALT = "item-action"


@dataclass(frozen=True)
class ActionClaim:
    item_id: int
    action: str
    tenant_id: str


def sign_action(secret: str, item_id: int, action: str, tenant_id: str) -> str:
    return URLSafeTimedSerializer(secret, salt=SALT).dumps(
        {"i": item_id, "a": action, "t": tenant_id}
    )


def verify_action(secret: str, token: str, max_age_seconds: int = 7 * 86400) -> ActionClaim:
    d = URLSafeTimedSerializer(secret, salt=SALT).loads(token, max_age=max_age_seconds)
    return ActionClaim(item_id=int(d["i"]), action=str(d["a"]), tenant_id=str(d["t"]))
