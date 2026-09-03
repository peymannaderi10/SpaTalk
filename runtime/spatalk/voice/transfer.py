"""Live transfer to a staffed back-line (operations plan, Task E10).

Spec §10 weakness 7: the brief promises a business-hours transfer to a person, and the
clinic may not have a line that can receive one. Everything here is built so that the
promise degrades honestly rather than loudly:

- the tool reaches the model only on a call where the tenant has a `transfer_number` *and*
  the clinic is open right now (:func:`transfer_available`), so the model cannot offer a
  transfer into an empty room;
- the carrier lives behind :class:`TransferPort`, with :class:`MemoryTransfer` standing in
  for it in tests, so nothing in the suite dials anything;
- :func:`attempt_transfer` never raises and never waits longer than
  :data:`TRANSFER_TIMEOUT_SECONDS`; a refusal, an error and a silent carrier are one answer
  (``False``), and the handler turns that into a real urgent callback item.

**Option A** is what is coded: the call arrives through the TeXML application, and the leg
is transferred with `POST /v2/calls/{call_control_id}/actions/transfer`, where the
`call_control_id` is the one Telnyx sends in the media stream's start message (the same id
`TelnyxFrameSerializer` already uses to hang up). Whether Telnyx accepts a call-control
action on a TeXML-originated leg is the one fact that cannot be established without a live
call: `docs/runbooks/transfer.md` is the spike the founder runs, and it also lists the
change set for **Option B** (move the number to a Call Control application) if A is refused.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol

import httpx
from loguru import logger

from spatalk.brain.hours import BusinessCalendar
from spatalk.brain.tools import TRANSFER_TOOL
from spatalk.tenants.schema import TenantConfig

__all__ = [
    "TRANSFER_TOOL",
    "TRANSFER_TIMEOUT_SECONDS",
    "MemoryTransfer",
    "TelnyxTransfer",
    "TransferPort",
    "attempt_transfer",
    "make_transfer",
    "mask_number",
    "suppress_auto_hangup",
    "transfer_available",
]

# How long the caller waits on "One moment, I'll connect you to the team" before the
# assistant gives up and files an urgent callback instead. Long enough for a carrier round
# trip and a ring, short enough that nobody is left listening to nothing.
TRANSFER_TIMEOUT_SECONDS = 20.0

TELNYX_API = "https://api.telnyx.com/v2"


def transfer_available(cfg: TenantConfig, now: datetime) -> bool:
    """True when this tenant can hand a caller to a person right now.

    Both halves matter. Without `transfer_number` there is nowhere to send the call; outside
    opening hours the back-line rings an empty room, which is worse than a callback the
    ledger tracks.
    """
    return bool(cfg.transfer_number) and BusinessCalendar(cfg).is_open(now)


def mask_number(number: str) -> str:
    """The back-line as an outcome may carry it: last four digits, the rest starred."""
    digits = "".join(c for c in (number or "") if c.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


class TransferPort(Protocol):
    """One carrier action: put this leg through to that number. Raises on refusal."""

    async def transfer(self, call_control_id: str, to: str) -> None: ...


class TelnyxTransfer:
    """The Telnyx Call Control transfer action, behind :class:`TransferPort`.

    Nothing outside this class knows the vendor, and the vendor is named only here and in
    `spatalk.sms`, so a carrier swap is two files.
    """

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self._key = api_key
        self._http = http or httpx.AsyncClient(timeout=TRANSFER_TIMEOUT_SECONDS)

    async def transfer(self, call_control_id: str, to: str) -> None:
        r = await self._http.post(
            f"{TELNYX_API}/calls/{call_control_id}/actions/transfer",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"to": to},
        )
        r.raise_for_status()


class MemoryTransfer:
    """In-memory TransferPort for tests; records (call_control_id, to) pairs.

    `fail=True` is a carrier that refuses, `delay` is a carrier that never answers. Both are
    real outcomes of the spike, and both must end as an urgent callback rather than silence.
    """

    def __init__(self, fail: bool = False, delay: float = 0.0):
        self._fail, self._delay = fail, delay
        self.calls: list[tuple[str, str]] = []

    async def transfer(self, call_control_id: str, to: str) -> None:
        if self._delay:
            await asyncio.sleep(self._delay)
        self.calls.append((call_control_id, to))
        if self._fail:
            raise RuntimeError("carrier refused the transfer")


def make_transfer(settings) -> TransferPort | None:
    """The carrier client for this deployment, or None when no key is configured."""
    key = getattr(settings, "telnyx_api_key", "")
    return TelnyxTransfer(api_key=key) if key else None


async def attempt_transfer(
    port: TransferPort | None,
    call_control_id: str | None,
    to: str | None,
    timeout: float | None = None,
) -> bool:
    """Try to hand the leg over. True only when the carrier accepted it.

    Never raises: the caller of this function is mid-call with a person on the line, and the
    only useful answer is yes or no. A missing port, a missing leg id and a missing number
    are all no, because in each case nothing was attempted.
    """
    if port is None or not call_control_id or not to:
        logger.warning(
            "transfer not attempted: port={} call={} to_configured={}",
            port is not None,
            bool(call_control_id),
            bool(to),
        )
        return False
    budget = TRANSFER_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        await asyncio.wait_for(port.transfer(call_control_id, to), timeout=budget)
    except asyncio.TimeoutError:
        logger.warning("transfer to {} timed out after {}s", mask_number(to), budget)
        return False
    except Exception as e:  # noqa: BLE001  carrier refusal, network, anything
        logger.warning("transfer to {} failed: {}", mask_number(to), e)
        return False
    return True


def suppress_auto_hangup(params) -> None:
    """Stop the Telnyx serializer hanging up a leg that now belongs to a person.

    `TelnyxFrameSerializer` calls the hangup API on the first EndFrame or CancelFrame it
    sees when `auto_hang_up` is on, which it is by default. That is right for every other
    way a call ends and exactly wrong after a transfer: our pipeline shuts down seconds
    later and would drop the caller mid-sentence with the staff member. The serializer keeps
    the `InputParams` instance it was constructed with, so flipping the documented field on
    the object we passed in is enough, and it is a no-op if a caller passes nothing.
    """
    if params is not None and hasattr(params, "auto_hang_up"):
        params.auto_hang_up = False
