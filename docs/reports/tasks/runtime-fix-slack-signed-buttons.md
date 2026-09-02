# QA gate A fix: slack-signed-buttons
Status: done with deviations
Commit: <filled below>
Tests: `uv run pytest -q tests/test_http_actions.py tests/test_delivery.py` -> 9/9; full suite `uv run pytest -q` -> 191 passed, 1 skipped; `uv run ruff check spatalk tests scenarios` -> All checks passed

## The defect

QA gate A [major], `runtime/spatalk/http/slack.py:14-33`: `/slack/interactions` verified the
Slack request signature and then acted on `payload["actions"][0]["value"]` parsed as a bare
integer item id. Nothing bound that id to a tenant, and `items.id` is a serial primary key, so
a staff member in one workspace could acknowledge or resolve another tenant's item by editing
the button value before the click was re-signed.

## The fix

- `runtime/spatalk/ledger/delivery.py`
  - `ActionLinks` gains `ack_token: str` and `resolve_token: str` (appended after the three
    existing URL fields, so positional construction of the URLs is unchanged).
  - `build_links` already signs `ack`, `resolve` and `transcript` claims with
    `sign_action(secret_key, item.id, action, item.tenant_id)` for the email links; it now
    carries the `ack` and `resolve` tokens through on the dataclass instead of discarding them
    after interpolating the URLs. No new signing scheme, no new secret.
  - `build_slack_blocks` sets each button `value` to the matching token rather than
    `str(item.id)`.
- `runtime/spatalk/http/slack.py`
  - After the Slack signature check, the button value is verified with `verify_action`. The
    item id, the action and the tenant all come from the verified claim; `action_id` is kept
    for the UI and is never consulted for authorization.
  - `BadSignature` (a forged, tampered, expired or bare-integer value) -> 401.
  - A claim whose action is not `ack` or `resolve` (for example a `transcript` token pasted
    into a button) -> 400.
  - A claim whose `tenant_id` does not match the stored item's `tenant_id` -> 403.
  - Unknown item -> 404, as before. The 401-on-bad-Slack-signature behaviour is untouched and
    is still asserted by `test_slack_interaction_requires_valid_signature_and_resolves`.

## Tests

`runtime/tests/test_http_actions.py`
- `_slack_request(secret, value, action_id, user)` helper builds a correctly signed Slack
  interaction body; the existing test now sends a signed `resolve` token as the value.
- `test_slack_button_value_must_be_a_signed_token` — a bare item id (the old format, and the
  exact shape of the QA probe) returns 401 and leaves the item `open`.
- `test_slack_token_for_one_item_cannot_act_on_another` — two items exist; the token for item A
  resolves A and leaves B `open`, because the id can no longer be supplied out of band.
- `test_slack_token_from_another_tenant_is_rejected` — a validly signed token whose tenant is
  `some-other-tenant` returns 403 and leaves the item `open`.
- `test_slack_action_id_cannot_widen_the_token` — an `ack` token clicked with
  `action_id="resolve"` acknowledges (the claim wins); a `transcript` token returns 400 and
  changes nothing.

`runtime/tests/test_delivery.py`
- `test_item_delivery_enqueues_per_destination_and_sends` now verifies both delivered button
  values with `verify_action` and asserts the claims are `ack`/`resolve` for this item id and
  tenant `skincentrix`, and that neither value is a bare integer.
- `test_email_and_blocks_contain_no_free_text_from_caller` constructs `ActionLinks` with real
  signed tokens and asserts the blocks carry them verbatim.

All five http tests and both delivery assertions were seen failing first, for the expected
reasons: `ValueError: invalid literal for int() with base 10: 'eyJpIjoxLCJhIjoiYWNrIi...'` from
`spatalk/http/slack.py:25`, and `TypeError: ActionLinks.__init__() takes 4 positional arguments
but 6 were given`. No test was weakened, skipped or deleted.

Interfaces produced: `ActionLinks(ack_url, resolve_url, transcript_url, ack_token, resolve_token)`, `build_links(settings, item) -> ActionLinks`, `build_slack_blocks(item, cfg, links, now=None) -> list[dict]`

Deviations:
- The task named 401 for `BadSignature` and 400 for a mismatched action but did not name a code
  for the cross-tenant case. Chosen: **403**, because the signature is valid and the refusal is
  an authorization decision, not a parse failure or a missing record. Evidence:
  `uv run pytest -q tests/test_http_actions.py -k another_tenant` -> 1 passed.
- With the id sourced from the claim, a cross-tenant token can only ever name its own item, so
  the `item.tenant_id != claim.tenant_id` check is defence in depth against a future signing
  key shared across tenants. It is kept and tested rather than dropped as unreachable.
- `ActionLinks` is now a five-field dataclass. Two positional constructions existed in the
  repository (`build_links` and one test); both are updated. Evidence:
  `grep -rn "ActionLinks(" --include=*.py .` -> `spatalk/ledger/delivery.py:51`,
  `tests/test_delivery.py:50`.

Notes for neighbours:
- **Anyone building Slack blocks must pass an `ActionLinks` built by `build_links`.** A hand-made
  `ActionLinks` with empty `ack_token`/`resolve_token` produces buttons that the interaction
  endpoint answers with 401. There is no fallback to a bare item id any more.
- Slack button values are capped at 2000 characters; an `itsdangerous` action token is roughly
  80, so there is no headroom problem.
- Buttons in Slack messages delivered before this change carry bare ids and will now be
  refused with 401. Nothing has been delivered to a real workspace yet, so no migration is
  needed; the item is still actionable through the emailed `/a/<token>` links.
- `runtime/spatalk/http/actions.py` (the email-link path) already sourced everything from the
  verified claim and was not touched. It does **not** carry the tenant cross-check; if a signing
  key is ever shared across tenants, add the same `item.tenant_id != claim.tenant_id` guard there.

Blocked on: nothing.
