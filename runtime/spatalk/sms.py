"""One swappable SMS vendor behind :class:`~spatalk.brain.ports.SmsPort`.

Nothing outside this module knows the vendor. Swap it by constructing a different
``SmsPort`` in the application context.
"""

from __future__ import annotations

import httpx


class TelnyxSms:
    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self._key, self._http = api_key, http or httpx.AsyncClient(timeout=10)

    async def send(self, from_number: str, to: str, text: str) -> None:
        r = await self._http.post(
            "https://api.telnyx.com/v2/messages",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"from": from_number, "to": to, "text": text},
        )
        r.raise_for_status()
