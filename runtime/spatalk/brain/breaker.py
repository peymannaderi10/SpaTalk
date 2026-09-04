"""A per-vendor circuit breaker, shared by every channel in the process.

Founder decision 2026-09-03 ~21:20: Google answered every request with 503 for twenty
minutes, and every turn of every call paid the SDK's full retry budget before the caller
heard an apology. Counting failures is what stops that: once a vendor has failed
``failures`` times inside ``window_secs`` it is treated as down for ``cooldown_secs``, and
the runtime starts the turn at the other vendor instead of paying the dead one's latency
again. One success clears the count, so a bad minute costs nothing once it is over.

The breaker names no vendor. It is a dictionary keyed by whatever ``LLM_MODEL`` and
``LLM_MODEL_FALLBACK`` name (CLAUDE.md non-negotiable 4), and it holds no keys, no models
and no wording. The clock is injectable and monotonic: wall-clock time can step backwards
and a breaker that reads it would then stay open for hours.

This module deliberately imports nothing from :mod:`spatalk.settings`; :func:`configure`
takes the numbers from a settings object the caller already has, so counting failures never
drags a dotenv read into an import.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta

from loguru import logger

# The defaults the module-level BREAKER starts with; `configure(settings)` replaces them at
# app start with the environment's values. They are duplicated in `Settings` rather than
# imported from it, which is what keeps this module free of a settings import.
DEFAULT_FAILURES = 3
DEFAULT_WINDOW_SECS = 60
DEFAULT_COOLDOWN_SECS = 300


class VendorBreaker:
    """Recent failures per vendor, and the verdict that follows from them."""

    def __init__(
        self,
        failures: int = DEFAULT_FAILURES,
        window_secs: float = DEFAULT_WINDOW_SECS,
        cooldown_secs: float = DEFAULT_COOLDOWN_SECS,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.failures = failures
        self.window_secs = window_secs
        self.cooldown_secs = cooldown_secs
        self._monotonic = monotonic
        self._failures: dict[str, list[float]] = {}
        self._open_until: dict[str, float] = {}

    # ----- configuration -------------------------------------------------------------

    def reconfigure(self, failures: int, window_secs: float, cooldown_secs: float) -> None:
        """Replace the numbers. The counts already recorded are kept."""
        self.failures = failures
        self.window_secs = window_secs
        self.cooldown_secs = cooldown_secs

    def reset(self) -> None:
        """Forget every vendor's history. For tests, and for a process starting fresh."""
        self._failures.clear()
        self._open_until.clear()

    # ----- recording -----------------------------------------------------------------

    def record_failure(self, vendor: str) -> None:
        """One turn this vendor could not answer, after its own SDK had already retried."""
        now = self._monotonic()
        recent = [t for t in self._failures.get(vendor, ()) if now - t < self.window_secs]
        recent.append(now)
        self._failures[vendor] = recent
        if len(recent) >= self.failures and not self._is_open_at(vendor, now):
            self._open_until[vendor] = now + self.cooldown_secs
            logger.warning(
                "llm vendor {} failed {} times in {}s; not trying it again for {}s",
                vendor,
                len(recent),
                self.window_secs,
                self.cooldown_secs,
            )

    def record_success(self, vendor: str) -> None:
        """This vendor answered. The run of failures that was building up is over."""
        if self._failures.pop(vendor, None) or self._open_until.pop(vendor, None):
            logger.info("llm vendor {} answered; its failure count is cleared", vendor)

    # ----- reading -------------------------------------------------------------------

    def failure_count(self, vendor: str) -> int:
        """How many failures this vendor has inside the window, right now."""
        now = self._monotonic()
        return len([t for t in self._failures.get(vendor, ()) if now - t < self.window_secs])

    def is_open(self, vendor: str) -> bool:
        """True while this vendor is in its cooling-off period."""
        return self._is_open_at(vendor, self._monotonic())

    def open_until(self, vendor: str) -> float | None:
        """The monotonic deadline the cooling-off period ends at, or None if it is shut."""
        now = self._monotonic()
        return self._open_until[vendor] if self._is_open_at(vendor, now) else None

    def remaining_secs(self, vendor: str) -> float | None:
        """Seconds until this vendor is tried again, or None if it is not being avoided."""
        deadline = self.open_until(vendor)
        return None if deadline is None else max(0.0, deadline - self._monotonic())

    def active(self, primary: str, secondary: str | None) -> str:
        """Which vendor a turn should start at.

        The primary, unless its breaker is open and the secondary's is not. With both open
        the answer is still the primary: it is the least bad of two bad options, because it
        is the model the prompts and the adversarial scenarios were graded against, and a
        caller is waiting for the turn to be sent somewhere.
        """
        if secondary is None or secondary == primary:
            return primary
        now = self._monotonic()
        if self._is_open_at(primary, now) and not self._is_open_at(secondary, now):
            return secondary
        return primary

    # ----- internals -----------------------------------------------------------------

    def _is_open_at(self, vendor: str, now: float) -> bool:
        deadline = self._open_until.get(vendor)
        if deadline is None:
            return False
        if now < deadline:
            return True
        # The cooling-off period is over: the vendor gets a clean slate, so one more
        # failure does not immediately re-open a breaker on a count from ten minutes ago.
        del self._open_until[vendor]
        self._failures.pop(vendor, None)
        return False


# One breaker per process: voice calls, text channels and the health endpoint all read the
# same counts, because they are all talking to the same vendor.
BREAKER = VendorBreaker()


def configure(settings) -> VendorBreaker:
    """Point the process-wide breaker at the environment's numbers. Called at app start."""
    BREAKER.reconfigure(
        settings.llm_breaker_failures,
        settings.llm_breaker_window_secs,
        settings.llm_breaker_cooldown_secs,
    )
    return BREAKER


def llm_health(settings, now, breaker: VendorBreaker | None = None) -> dict:
    """What `/healthz` says about the model vendors: who is configured and who is answering.

    ``now`` is the tenant-agnostic wall clock (the runtime's own), used only to turn the
    breaker's monotonic deadline into a timestamp an operator can read.
    """
    from spatalk.brain.driver import provider_for

    breaker = breaker or BREAKER
    primary = provider_for(settings.llm_model)
    fallback = (settings.llm_model_fallback or "").strip()
    secondary = provider_for(fallback) if fallback else None
    remaining = breaker.remaining_secs(primary)
    return {
        "primary": primary,
        "secondary": secondary,
        "active": breaker.active(primary, secondary),
        "breaker_open_until": (
            None if remaining is None else (now + timedelta(seconds=remaining)).isoformat()
        ),
    }
