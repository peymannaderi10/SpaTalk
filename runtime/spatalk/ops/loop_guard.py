"""The loop guard: refuse a call that came from one of our own numbers.

Spec §10 weakness 7. The forwarding chain in front of this system is configured by hand at
the carrier, and the clinic's back-line may not exist at all. Two ways that bites:

* our own Telnyx number gets forwarded back to itself, so the assistant answers the
  assistant, burns telephony minutes on both legs, and files a conversation nobody made;
* a staff member calls the assistant from the clinic's public line to "test" it, and the
  assistant treats the clinic as a customer.

Both are the same shape: `From` is a number this tenant owns. The answer is the fixed
`loop_guard` script, a hangup, an alert row, and no conversation.

Numbers are compared in E.164 because that is the only form both sides agree on: the
carrier presents `+19057037546`, and `tenant.yaml` carries the clinic's own number the way
a human typed it (`905-703-7546`).
"""

from __future__ import annotations


from spatalk.tenants.schema import TenantConfig

# North American Numbering Plan. The tenant bundle is a Canadian clinic; a tenant outside
# +1 writes its own numbers in full international form, which this function passes through.
DEFAULT_COUNTRY_CODE = "1"


def normalise_e164(value: str | None, country_code: str = DEFAULT_COUNTRY_CODE) -> str | None:
    """Best-effort E.164 for a number a human or a carrier wrote. None when there is none.

    `"(905) 703-7546"`, `"905-703-7546"` and `"+1 905 703 7546"` all become
    `"+19057037546"`. Caller-id strings that are not numbers at all (`"anonymous"`,
    `"unavailable"`, `""`) become None, which never matches anything.
    """
    if not value:
        return None
    raw = value.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    if raw.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return f"+{country_code}{digits}"
    return "+" + digits


def own_numbers(cfg: TenantConfig) -> set[str]:
    """Every number the tenant's own configuration claims, in E.164."""
    claimed = [cfg.public_phone, cfg.sms_from_number, *cfg.voice_numbers]
    return {n for n in (normalise_e164(v) for v in claimed) if n}


async def is_own_number(cfg: TenantConfig, registry, number: str | None) -> bool:
    """True when `number` is one of this tenant's own lines.

    Two sources, because neither is complete on its own: `tenant_numbers` is authoritative
    for the numbers we bought (`registry.resolve_number`), and the bundle is the only place
    the clinic's own public phone is recorded (it is TELUS's, not ours).
    """
    target = normalise_e164(number)
    if target is None:
        return False
    if target in own_numbers(cfg):
        return True
    # The registry keys on the stored string; look up both forms so a number stored
    # without normalisation still matches.
    for candidate in (target, (number or "").strip()):
        if candidate and await registry.resolve_number(candidate) == cfg.id:
            return True
    return False


async def log_loop_guard_alert(ctx, tenant_id: str, number: str) -> None:
    """Raise the loop-guard alert through Task E7's `notify`.

    One `alert_log` row, one email and one ops text per tenant and calling number inside the
    dedup window. QA gate C found the earlier version wrote a row nobody was told about and
    never deduplicated, so a number stuck in a forwarding loop alerted once per ring.
    """
    from spatalk.ops.alerts import notify

    normalised = normalise_e164(number) or (number or "unknown")
    subject = (
        f"Loop guard: {tenant_id} refused a call from its own number {normalised}. "
        "Check the carrier forwarding chain."
    )
    body = (
        subject
        + "\n\nA call arrived from a number this tenant owns or publishes. The assistant said "
        "the loop-guard script and hung up; no conversation was created. If this repeats, a "
        "forwarding rule at the carrier points the clinic's line back at the assistant."
    )
    await notify(ctx, f"loop_guard:{tenant_id}:{normalised}", subject, body)
