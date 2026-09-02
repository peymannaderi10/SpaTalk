"""Per-IP rate limits at the edge of the HTTP app (operations plan, Task E8).

One runtime node, one process, one dictionary of token buckets: no Redis, no extra service
(operations plan, Global Constraints). The buckets are deliberately coarse. They are not a
defence against a distributed flood — Cloudflare and the carrier sit in front of that — they
stop one machine from walking action-link tokens, opening chat sessions or replaying a
webhook thousands of times a minute against a single small VPS.

Two properties matter:

* A caller that is limited gets `429` with `Retry-After`, never a silent drop, so a legitimate
  client can come back rather than guess.
* The paths a carrier or the edge worker uses have a much larger bin, and a request carrying
  the edge worker's shared key skips the limit entirely: the worker is the SMS front door when
  the runtime has been unreachable (text-channels plan, Task B1) and its replay burst after an
  outage must not be turned away by us.
"""

from __future__ import annotations

import hmac
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

from fastapi import FastAPI
from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

EDGE_KEY_HEADER = "x-edge-key"
# Cloudflare's own header first: on the deployed setup it is the only one the origin can
# trust, because Cloudflare rewrites it and appends to X-Forwarded-For.
CLIENT_IP_HEADERS = ("cf-connecting-ip", "x-forwarded-for")
UNKNOWN_IP = "unknown"
# Above this many live buckets the idle ones are swept, so a rotating source of addresses
# cannot grow the dictionary without bound.
MAX_BUCKETS = 10_000


@dataclass(frozen=True)
class Rule:
    """A bin: every request whose path starts with `prefix` shares one bucket per IP."""

    prefix: str
    per_minute: int
    edge_key_exempt: bool = False

    def __post_init__(self) -> None:
        # A bin of zero would divide by zero when it works out when to let the caller back
        # in; a path that must be closed is closed by not routing it, not by a limit of 0.
        if self.per_minute < 1:
            raise ValueError(f"{self.prefix}: a rate limit must allow at least one a minute")

    @property
    def refill_per_second(self) -> float:
        return self.per_minute / 60.0


# The documented limits (operations plan, Task E8). `/messenger/*` is not named there because
# the plan predates Task D3 splitting the Meta adapter in two; it is the same kind of traffic
# from the same platform as `/instagram/*` and shares its bin.
RULES: tuple[Rule, ...] = (
    Rule("/a/", 10),
    Rule("/chat/", 30),
    Rule("/widget/", 60),
    Rule("/telnyx/", 300, edge_key_exempt=True),
    Rule("/instagram/", 300, edge_key_exempt=True),
    Rule("/messenger/", 300, edge_key_exempt=True),
)


class TokenBucket:
    """`capacity` requests may arrive at once; after that, `refill_per_second` trickles in."""

    __slots__ = ("capacity", "refill_per_second", "_tokens", "_updated_at")

    def __init__(self, capacity: float, refill_per_second: float, now: datetime):
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self._tokens = float(capacity)
        self._updated_at = now

    @property
    def tokens(self) -> float:
        return self._tokens

    def _refill(self, now: datetime) -> None:
        elapsed = (now - self._updated_at).total_seconds()
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
            self._updated_at = now

    def is_full(self, now: datetime) -> bool:
        self._refill(now)
        return self._tokens >= self.capacity

    def take(self, now: datetime) -> float:
        """0.0 when the request may proceed, otherwise the seconds until the next token."""
        self._refill(now)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        return (1.0 - self._tokens) / self.refill_per_second


class IpRateLimiter:
    """The bins and their buckets. Keyed by (rule prefix, client address)."""

    def __init__(self, rules: Sequence[Rule] = RULES):
        self._rules = tuple(rules)
        self._buckets: dict[tuple[str, str], TokenBucket] = {}

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self._rules

    def rule_for(self, path: str) -> Rule | None:
        for rule in self._rules:
            if path.startswith(rule.prefix):
                return rule
        return None

    def take(self, path: str, ip: str, now: datetime) -> float:
        """0.0 when the request may proceed, otherwise the seconds until the next token."""
        rule = self.rule_for(path)
        if rule is None:
            return 0.0
        key = (rule.prefix, ip)
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= MAX_BUCKETS:
                self._sweep(now)
            bucket = TokenBucket(rule.per_minute, rule.refill_per_second, now)
            self._buckets[key] = bucket
        return bucket.take(now)

    def _sweep(self, now: datetime) -> None:
        """Forget the callers who are back at full allowance: they are indistinguishable
        from callers we have never seen."""
        idle = [key for key, bucket in self._buckets.items() if bucket.is_full(now)]
        for key in idle:
            del self._buckets[key]


def client_ip(headers: Mapping[str, str], scope_client: Iterable | None) -> str:
    """The caller's address as the proxy in front of us reports it."""
    for name in CLIENT_IP_HEADERS:
        value = headers.get(name)
        if value:
            return value.split(",")[0].strip()
    if scope_client:
        return tuple(scope_client)[0]
    return UNKNOWN_IP


def carries_edge_key(headers: Mapping[str, str], edge_shared_key: str) -> bool:
    """True only for a request that presents the configured edge worker key.

    Presence of the header is not enough: a header anyone can set would hand the larger bin
    to anyone who reads this file.
    """
    presented = headers.get(EDGE_KEY_HEADER)
    if not presented or not edge_shared_key:
        return False
    return hmac.compare_digest(presented, edge_shared_key)


def _now(request: Request) -> datetime:
    ctx = getattr(request.app.state, "ctx", None)
    clock = getattr(ctx, "clock", None)
    return clock.now() if clock is not None else datetime.now(timezone.utc)


def _edge_shared_key(request: Request) -> str:
    ctx = getattr(request.app.state, "ctx", None)
    settings = getattr(ctx, "settings", None)
    return getattr(settings, "edge_shared_key", "") or ""


def install_rate_limits(app: FastAPI, rules: Sequence[Rule] = RULES) -> None:
    """Put the limiter on `app.state` and the middleware in front of every HTTP route.

    Tests replace `app.state.rate_limiter` with a smaller rule set; the WebSocket routes are
    untouched, `/chat/ws` carries its own per-IP limits from Task B4.
    """
    app.state.rate_limiter = IpRateLimiter(rules)

    @app.middleware("http")
    async def limit_by_ip(request: Request, call_next) -> Response:
        limiter: IpRateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            return await call_next(request)
        path = request.url.path
        rule = limiter.rule_for(path)
        if rule is None:
            return await call_next(request)
        if rule.edge_key_exempt and carries_edge_key(request.headers, _edge_shared_key(request)):
            return await call_next(request)
        ip = client_ip(request.headers, request.scope.get("client"))
        wait = limiter.take(path, ip, _now(request))
        if wait > 0:
            retry_after = max(1, math.ceil(wait))
            logger.warning("rate limited {} on {} for {}s", request.client, path, retry_after)
            return JSONResponse(
                {"detail": "too many requests"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
