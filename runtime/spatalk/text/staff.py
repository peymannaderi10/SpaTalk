"""Who counts as staff on the SMS line, and what a staff text means.

Founder decision 2026-09-02: tracked items land on the owner's own mobile, and the owner
works the ledger by replying to that text. Two things follow, and they are the whole of this
module:

* **Authorisation is a list of numbers**, not a login. It is the numbers a tenant configured
  for relay (``delivery.staff_phone_numbers``) plus the numbers the ``sms`` destinations
  name through their environment variables. Delivery and the inbound webhook must agree on
  that list, so both read :func:`staff_numbers`.
* **A staff reply is a keyword, never a sentence for the model.** :func:`parse_staff_command`
  recognises a small fixed vocabulary and nothing else; anything it does not recognise is
  answered with the tenant's help text, so a staff phone never reaches the brain and no
  free text ever reaches an item (CLAUDE.md non-negotiables 1 and 2).
"""

from __future__ import annotations

import re

from spatalk.ledger.delivery import sms_destination_numbers
from spatalk.tenants.schema import TenantConfig

# The vocabulary. Everything here is a whole word followed by an item id; a bare "done" with
# no id is not a command, because guessing which item the owner meant is exactly the kind of
# assumption that puts a wrong state on the ledger.
ACK_WORDS = frozenset({"ack", "acknowledge", "acknowledged", "ok", "okay"})
RESOLVE_WORDS = frozenset({"done", "resolve", "resolved", "close", "closed"})
LIST_WORD = "list"

_RELAY = re.compile(r"^#\s*(\d+)\s*(.*)$", re.S)
_NON_WORD = re.compile(r"[^a-z0-9]+")

StaffCommand = tuple[str | None, int | None, str]


def staff_numbers(cfg: TenantConfig) -> set[str]:
    """Every phone number that may work this tenant's ledger by text.

    A destination whose environment variable is unset resolves to nothing and is simply not
    in the set: an unconfigured owner phone must never widen who is authorised.
    """
    return set(cfg.delivery.staff_phone_numbers) | sms_destination_numbers(cfg)


def parse_staff_command(text: str) -> StaffCommand:
    """What this staff text asks for: ``(command, item_id, remainder)``.

    ``("ack", 4821, "")`` for ``ack 4821``, ``ok #4821``, ``acknowledge 4821``;
    ``("resolve", 4821, "")`` for ``done``, ``resolve``, ``resolved``, ``closed`` with an id;
    ``("relay", 4821, "on my way")`` for the ``#4821 …`` form the team already uses;
    ``("list", None, "")`` for ``list``; and ``(None, None, text)`` for everything else,
    which the caller answers with fixed wording rather than a guess.
    """
    relay = _RELAY.match(text.strip())
    if relay:
        return "relay", int(relay.group(1)), relay.group(2).strip()

    words = _NON_WORD.sub(" ", text.lower()).split()
    if words == [LIST_WORD]:
        return LIST_WORD, None, ""
    if len(words) == 2 and words[1].isdigit():
        if words[0] in ACK_WORDS:
            return "ack", int(words[1]), ""
        if words[0] in RESOLVE_WORDS:
            return "resolve", int(words[1]), ""
    return None, None, text
