"""The Graph API seam.

Every Meta HTTP call in the runtime goes through a :class:`GraphClient`, for two reasons:
tests never touch the network (:class:`FakeGraphClient` answers from a fixture table and
records what was asked for), and the vendor stays swappable by construction rather than by
rewrite (CLAUDE.md non-negotiable 4).

Errors are one type, :class:`GraphError`, carrying the status and the response body. Its
``retryable`` flag is the rule the event jobs follow: 429 and 5xx come back later, every
other 4xx is a dead letter with the body in ``last_error``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

import httpx
from loguru import logger

TokenGetter = Callable[[], "str | None | Awaitable[str | None]"]


class GraphError(RuntimeError):
    """A non-2xx answer from Meta. The body is kept for the job's ``last_error``."""

    def __init__(self, status_code: int, body: str = ""):
        super().__init__(f"graph {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body

    @property
    def retryable(self) -> bool:
        """Rate limiting and Meta's own failures are worth another attempt; 4xx is not."""
        return self.status_code == 429 or self.status_code >= 500


class GraphClient(Protocol):
    async def get(self, path: str, params: dict | None = None) -> dict: ...

    async def post(
        self,
        path: str,
        json: dict | None = None,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict: ...

    # --- instagram plan, Task D4: disconnecting unsubscribes, which Meta spells DELETE ---
    async def delete(self, path: str, params: dict | None = None) -> dict: ...


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class HttpGraphClient:
    """The real client. One base host (``graph.instagram.com``, ``graph.facebook.com``).

    ``token_getter`` supplies the bearer token for calls that need one; it may be sync or
    async, and may return None (the OAuth exchanges carry their token as a parameter and
    need no header). The token is never logged: log lines carry the path and the status.
    """

    def __init__(
        self,
        base_url: str,
        token_getter: TokenGetter | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._token_getter = token_getter
        self._client = client
        self._timeout = timeout

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(
        self,
        path: str,
        json: dict | None = None,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        return await self._request("POST", path, params=params, json=json, data=data)

    # --- instagram plan, Task D4 ---
    async def delete(self, path: str, params: dict | None = None) -> dict:
        return await self._request("DELETE", path, params=params)

    async def _headers(self) -> dict[str, str]:
        if self._token_getter is None:
            return {}
        token = await _resolve(self._token_getter())
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        headers = await self._headers()
        if self._client is not None:
            response = await self._client.request(method, url, headers=headers, **kwargs)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        if response.status_code >= 400:
            logger.warning("graph {} {} -> {}", method, path, response.status_code)
            raise GraphError(response.status_code, response.text)
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {"data": body}


@dataclass(frozen=True)
class GraphCall:
    """One recorded call: what a test asserts about instead of a network trace."""

    method: str
    path: str
    params: dict = field(default_factory=dict)
    json: dict | None = None
    data: dict | None = None


class FakeGraphClient:
    """Answers from a table keyed by ``"METHOD /path"`` (or just ``"/path"``).

    A value may be a dict (the answer), a list of dicts (successive answers), or an
    exception instance (raised). An unstubbed path raises rather than returning a silent
    empty dict, so a test can never pass because a call went nowhere.
    """

    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses: dict[str, Any] = dict(responses or {})
        self.calls: list[GraphCall] = []

    async def get(self, path: str, params: dict | None = None) -> dict:
        return self._answer(GraphCall("GET", path, dict(params or {})))

    async def post(
        self,
        path: str,
        json: dict | None = None,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        return self._answer(GraphCall("POST", path, dict(params or {}), json, data))

    # --- instagram plan, Task D4 ---
    async def delete(self, path: str, params: dict | None = None) -> dict:
        return self._answer(GraphCall("DELETE", path, dict(params or {})))

    def _answer(self, call: GraphCall) -> dict:
        self.calls.append(call)
        for key in (f"{call.method} {call.path}", call.path):
            if key not in self.responses:
                continue
            value = self.responses[key]
            if isinstance(value, list):
                value = value.pop(0) if value else {}
            if isinstance(value, BaseException):
                raise value
            return value
        raise GraphError(404, f"FakeGraphClient has no response for {call.method} {call.path}")
