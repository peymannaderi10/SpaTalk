"""Meta webhook payloads in, one flat event type out.

Meta delivers several unrelated shapes on one endpoint: a comment arrives under
``entry[].changes[]``, a direct message under ``entry[].messaging[]``, and the same
``messaging`` array also carries echoes of our own sends, postbacks and read receipts. The
adapters should not each learn that; they get a list of :class:`SocialEvent`, which says what
kind of thing happened, who it came from, which account it was aimed at, and the id that
deduplicates it.

Signature verification lives here too, because both webhook routers need exactly the same
check and neither owns the other's module.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal

EventKind = Literal["comment", "message", "postback", "read", "echo"]

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="

# The kinds an adapter actually answers. The rest are recorded and ignored (plan D2 step 7).
ACTIONABLE: tuple[EventKind, ...] = ("message", "comment")


@dataclass(frozen=True)
class SocialEvent:
    """One thing that happened on a connected Meta account.

    ``tenant_external_id`` is the account the event was delivered for (the Instagram user id
    or the Page id), which is how the webhook finds the tenant. ``event_id`` is the comment
    id or the message ``mid``: the dedup key, and the primary key of ``meta_events``.
    """

    kind: EventKind
    tenant_external_id: str
    sender_id: str
    event_id: str
    text: str = ""
    comment_id: str | None = None
    media_id: str | None = None
    timestamp: datetime | None = None
    # The only piece of contact information Instagram gives us for a commenter. A direct
    # message carries no username, so it stays empty there and the sender id stands in.
    username: str = ""

    def to_payload(self) -> dict:
        """JSON for the job queue. Datetimes go out as ISO strings and come back as UTC."""
        return {
            "kind": self.kind,
            "tenant_external_id": self.tenant_external_id,
            "sender_id": self.sender_id,
            "event_id": self.event_id,
            "text": self.text,
            "comment_id": self.comment_id,
            "media_id": self.media_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "username": self.username,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "SocialEvent":
        stamp = payload.get("timestamp")
        return cls(
            kind=payload["kind"],
            tenant_external_id=str(payload["tenant_external_id"]),
            sender_id=str(payload["sender_id"]),
            event_id=str(payload["event_id"]),
            text=payload.get("text") or "",
            comment_id=payload.get("comment_id"),
            media_id=payload.get("media_id"),
            timestamp=datetime.fromisoformat(stamp) if stamp else None,
            username=payload.get("username") or "",
        )


def verify_meta_signature(raw_body: bytes, header: str, secrets: Iterable[str]) -> bool:
    """HMAC-SHA256 of the raw body against each app secret, compared in constant time.

    Both app secrets are tried because one runtime fronts both the Instagram app and the
    Facebook app, and Meta signs with whichever app delivered the event.
    """
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False  # an absent or unprefixed signature header is never valid
    provided = header[len(SIGNATURE_PREFIX) :]
    accepted = False
    for secret in secrets:
        if not secret:
            continue
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        # No early return: every configured secret is compared, so the time this takes does
        # not depend on which one matched.
        accepted |= hmac.compare_digest(expected, provided)
    return accepted


def _utc(seconds: float | None) -> datetime | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(float(seconds), tz=timezone.utc)


def _comment_event(entry_id: str, value: dict, entry_time: float | None) -> SocialEvent | None:
    comment_id = value.get("id")
    author = value.get("from") or {}
    if not comment_id or not author.get("id"):
        return None
    return SocialEvent(
        kind="comment",
        tenant_external_id=entry_id,
        sender_id=str(author["id"]),
        event_id=str(comment_id),
        text=value.get("text") or "",
        comment_id=str(comment_id),
        media_id=str((value.get("media") or {}).get("id") or "") or None,
        timestamp=_utc(entry_time),
        username=str(author.get("username") or ""),
    )


def _messaging_event(entry_id: str, item: dict) -> SocialEvent | None:
    sender = str((item.get("sender") or {}).get("id") or "")
    if not sender:
        return None
    # Meta sends messaging timestamps in milliseconds and entry times in seconds.
    stamp = item.get("timestamp")
    at = _utc(float(stamp) / 1000.0) if stamp is not None else None
    if "message" in item:
        message = item["message"] or {}
        mid = str(message.get("mid") or "")
        if not mid:
            return None
        return SocialEvent(
            kind="echo" if message.get("is_echo") else "message",
            tenant_external_id=entry_id,
            sender_id=sender,
            event_id=mid,
            text=message.get("text") or "",
            timestamp=at,
        )
    if "postback" in item:
        postback = item["postback"] or {}
        return SocialEvent(
            kind="postback",
            tenant_external_id=entry_id,
            sender_id=sender,
            event_id=str(postback.get("mid") or ""),
            text=str(postback.get("payload") or postback.get("title") or ""),
            timestamp=at,
        )
    if "read" in item:
        read = item["read"] or {}
        return SocialEvent(
            kind="read",
            tenant_external_id=entry_id,
            sender_id=sender,
            event_id=str(read.get("mid") or ""),
            timestamp=at,
        )
    return None


# --- facebook page feed (instagram plan, Task D3) ---
def _page_comment_event(
    entry_id: str, value: dict, entry_time: float | None
) -> SocialEvent | None:
    """A comment on a Page post.

    A Page's ``feed`` field carries everything that happens on the Page's own timeline:
    likes, shares, status edits, comments added, comments deleted. Only a comment somebody
    just wrote is something to answer, so anything else produces no event at all — it is not
    even recorded, because there is nothing an adapter would ever do with it.
    """
    if value.get("item") != "comment" or value.get("verb") != "add":
        return None
    comment_id = value.get("comment_id")
    author = value.get("from") or {}
    if not comment_id or not author.get("id"):
        return None
    return SocialEvent(
        kind="comment",
        tenant_external_id=entry_id,
        sender_id=str(author["id"]),
        event_id=str(comment_id),
        text=value.get("message") or "",
        comment_id=str(comment_id),
        # A Page comment hangs off a post, which is this channel's equivalent of a media id.
        media_id=str(value.get("post_id") or "") or None,
        timestamp=_utc(value.get("created_time") or entry_time),
        # Facebook gives a display name where Instagram gives a username. Either way it is
        # the only piece of contact information the platform hands us for a commenter.
        username=str(author.get("name") or ""),
    )


def _parse(
    body: dict, expected_object: str, comment_field: str, comment_builder
) -> list[SocialEvent]:
    if not isinstance(body, dict) or body.get("object") != expected_object:
        return []
    events: list[SocialEvent] = []
    for entry in body.get("entry") or []:
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        entry_time = entry.get("time")
        for change in entry.get("changes") or []:
            if change.get("field") != comment_field:
                continue
            event = comment_builder(entry_id, change.get("value") or {}, entry_time)
            if event is not None:
                events.append(event)
        for item in entry.get("messaging") or []:
            event = _messaging_event(entry_id, item)
            if event is not None and event.event_id:
                events.append(event)
    return events


def parse_instagram_payload(body: dict) -> list[SocialEvent]:
    """Comments and direct messages on a connected Instagram Business account."""
    return _parse(body, "instagram", "comments", _comment_event)


def parse_messenger_payload(body: dict) -> list[SocialEvent]:
    """Messages and feed comments on a connected Facebook Page (instagram plan, Task D3).

    The ``messaging`` array is byte-identical to Instagram's, so it is parsed by the same
    code; only the comment shape differs, because a Page delivers comments under ``feed``.
    """
    return _parse(body, "page", "feed", _page_comment_event)
