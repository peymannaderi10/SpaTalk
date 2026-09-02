"""Does the model this runtime is configured to talk through still exist? (Task E6.)

Spec §10 weakness 3: the whole conversation runs on one model at one vendor, and the vendor
retires models on its own calendar. The founder found out the hard way once already —
`gemini-2.5-pro` answers 404 "no longer available to new users" on this account (promptfoo
run A, 2026-09-02) — and the failure mode is the worst kind: nothing changes in the
repository, and one morning every call fails.

So once a week CI asks the provider for its model list and compares it with `LLM_MODEL`.
Three answers, three exit codes, and they are deliberately distinct:

* **0** the configured model is listed and carries no retirement notice.
* **1** a finding: the model is absent, or the provider's own description marks it
  deprecated. A deprecated model still answers, which is exactly why this is worth catching
  now rather than on the morning it stops.
* **2** the question could not be asked at all: no key, a provider error, an empty listing.
  This is not a pass. A weekly check that goes green when it reached nobody is worse than no
  check, because it also removes the suspicion that would have made someone look.

The runbook for what to do about a finding is `docs/runbooks/model-swap.md`.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from loguru import logger

from spatalk.brain.driver import GOOGLE, OPENAI, model_name, provider_for

# The environment variable each vendor's listing needs, by provider, for the message a
# missing key produces. `docs/reference/api-surface.md` is the source of both names.
KEY_ENV = {GOOGLE: "GOOGLE_API_KEY", OPENAI: "OPENAI_API_KEY"}
KEY_SETTING = {GOOGLE: "google_api_key", OPENAI: "openai_api_key"}

# What a provider writes when a model is on its way out. Google puts it in the model's
# description; OpenAI's listing carries no such field at all, so for OpenAI the check is
# presence, and a retirement shows up as an absence a week or so before it bites.
DEPRECATION_MARKERS = (
    "deprecated",
    "deprecation",
    "no longer available",
    "will be retired",
    "retirement",
    "discontinued",
    "sunset",
)

# Exit codes. `OK` and `FINDING` are the two answers; `UNCHECKED` is "I could not ask".
OK = 0
FINDING = 1
UNCHECKED = 2


@dataclass(frozen=True)
class ModelInfo:
    """One model as the provider lists it."""

    name: str
    description: str = ""
    deprecated: bool = False


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    provider: str
    model: str
    reason: str
    checked: int

    @property
    def exit_code(self) -> int:
        if self.ok:
            return OK
        return UNCHECKED if self.checked == 0 else FINDING


def normalise(name: str) -> str:
    """A model name comparable across the two listings.

    Google returns `models/gemini-2.5-flash`; the same model is configured as
    `gemini-2.5-flash`. OpenAI returns bare ids. Case is ignored on both.
    """
    raw = (name or "").strip()
    if raw.startswith("models/"):
        raw = raw[len("models/") :]
    return raw.lower()


def is_deprecated(model: ModelInfo) -> bool:
    if model.deprecated:
        return True
    text = (model.description or "").lower()
    return any(marker in text for marker in DEPRECATION_MARKERS)


def evaluate(models: list[ModelInfo], configured: str) -> CheckResult:
    """Compare a provider's listing with the configured model. No network, no settings."""
    provider = provider_for(configured)
    wanted = model_name(configured)
    if not models:
        return CheckResult(
            ok=False,
            provider=provider,
            model=wanted,
            reason=f"{provider} listed no models at all, so {wanted} was never checked",
            checked=0,
        )
    found = next((m for m in models if normalise(m.name) == normalise(wanted)), None)
    if found is None:
        return CheckResult(
            ok=False,
            provider=provider,
            model=wanted,
            reason=(
                f"{wanted} is not in the {len(models)} models {provider} lists; "
                "the swap drill is docs/runbooks/model-swap.md"
            ),
            checked=len(models),
        )
    if is_deprecated(found):
        return CheckResult(
            ok=False,
            provider=provider,
            model=wanted,
            reason=(
                f"{wanted} is listed by {provider} but marked deprecated: "
                f"{(found.description or 'no description').strip()}"
            ),
            checked=len(models),
        )
    return CheckResult(
        ok=True,
        provider=provider,
        model=wanted,
        reason=f"{wanted} is listed by {provider} and carries no retirement notice",
        checked=len(models),
    )


# --- asking the provider ----------------------------------------------------------------


async def list_models(settings, provider: str) -> list[ModelInfo]:
    """Every model the provider will admit to, as `ModelInfo`. The only network call here."""
    key = getattr(settings, KEY_SETTING[provider], "")
    if provider == OPENAI:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key)
        page = await client.models.list()
        return [ModelInfo(name=m.id) for m in page.data]
    from google import genai

    client = genai.Client(api_key=key)
    pager = await client.aio.models.list()
    out: list[ModelInfo] = []
    async for m in pager:
        out.append(ModelInfo(name=m.name or "", description=m.description or ""))
    return out


async def check_configured_model(settings, model: str | None = None, lister=None) -> CheckResult:
    """The whole check: which vendor, does it have a key, what does it list, is it there."""
    configured = model or settings.llm_model
    provider = provider_for(configured)
    try:
        wanted = model_name(configured)
    except ValueError as e:
        return CheckResult(False, provider, configured, str(e), 0)
    if not getattr(settings, KEY_SETTING[provider], ""):
        return CheckResult(
            ok=False,
            provider=provider,
            model=wanted,
            reason=(
                f"{KEY_ENV[provider]} is not set, so {provider} was never asked about "
                f"{wanted}; nothing was checked"
            ),
            checked=0,
        )
    ask = lister or list_models
    try:
        models = await ask(settings, provider)
    except Exception as e:  # noqa: BLE001  any provider failure is "could not ask", not "fine"
        logger.warning("could not list {} models: {}", provider, e)
        return CheckResult(
            ok=False,
            provider=provider,
            model=wanted,
            reason=f"{provider} could not be asked about {wanted}: {e}",
            checked=0,
        )
    return evaluate(list(models), configured)


# --- the CI entry point -----------------------------------------------------------------


def main(argv: list[str] | None = None, settings=None) -> int:
    """`python -m spatalk.ops.model_check [--model LLM_MODEL]`. Returns the exit code."""
    parser = argparse.ArgumentParser(description="Check the configured LLM at its provider.")
    parser.add_argument(
        "--model",
        default=None,
        help="the LLM_MODEL string to check; defaults to the configured one",
    )
    args = parser.parse_args(argv)
    if settings is None:
        from spatalk.settings import get_settings

        settings = get_settings()
    result = asyncio.run(check_configured_model(settings, model=args.model))
    label = {OK: "ok", FINDING: "FINDING", UNCHECKED: "NOT CHECKED"}[result.exit_code]
    print(f"[{label}] {result.provider}: {result.reason}")
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover  exercised by .github/workflows/model-check.yml
    raise SystemExit(main())
