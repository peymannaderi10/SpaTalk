# runtime QA gate A fix: payment-lexicon

Status: done with deviations
Commit: 2f70f0e (implementation and tests; this report follows in a docs commit, the
convention set by runtime-A8 through A16)
Tests: `uv run pytest -q tests/test_qa_gate_a.py -k payment_over_the_phone` -> 1 passed of 1
(seen failing first); `uv run pytest -q tests/test_qa_gate_a.py` -> 83 passed of 83; full runtime
suite -> **187 passed, 1 skipped of 188**, the 1 skip still the live Gemini test that is `skipif`
on `GOOGLE_API_KEY`. The full-suite run had to be isolated; see the second deviation.
`uv run ruff check spatalk tests scenarios` -> All checks passed!
Interfaces produced: none new. `DEFAULT_LEXICONS["payment"]` in `spatalk/brain/rules.py` gains six phrases;
`rules_gate` and `GateDecision` keep their signatures.

## The finding

`docs/reports/qa-gate-A.md`, first major: the deterministic payment gate did not cover
"Can I pay over the phone now?", the exact phrasing `docs/agents/QA.md:42` lists as a band-3
payment case. `rules_gate` returned `None`, the turn reached the model, and band 3 depended on
the model choosing `escalate`. The fixed payment script was still what got spoken when it did,
so this was a second-net dependency, not an honesty failure.

## The fix

`runtime/spatalk/brain/rules.py`, `DEFAULT_LEXICONS["payment"]` — six phrases appended, nothing
reordered or removed:

    "pay over the phone", "pay by phone", "pay by card", "card details", "take my card", "give you my card"

Every one is a payment *phrase*. "over the phone" is deliberately not a bare term: callers say it
about consultations ("Can I do the consultation over the phone?"), and gating that would send a
routine booking question to band 3 and end the call. The test asserts both directions.

`_pattern` sorts terms by length before alternating, so the longer "pay over the phone" wins over
"pay" fragments, and the `(?<![\w-])…(?![\w-])` boundaries still hold: the phrases contain spaces
only, so no word is matched inside another.

## Tests changed (both stronger, neither weakened)

- `tests/test_qa_gate_a.py::test_payment_over_the_phone_is_a_recorded_lexicon_gap_not_a_silent_one`
  → `::test_payment_over_the_phone_is_gated_as_payment_not_a_lexicon_gap`. It used to assert
  `rules_gate(...) is None` and then patch the tenant lexicon to show the gap was closable. It now
  asserts the built-in gate returns `reason == "payment"` for six phrasings (the QA one plus one per
  new phrase) and returns `None` for two "over the phone" consultation questions. The name keeps the
  `payment_over_the_phone` substring, so the brief's `-k payment_over_the_phone` still selects it.
- `KNOWN_GATE_MISSES` — "Can I pay over the phone now?" removed. That moves the phrase into the
  parametrized `::test_rules_gate_routes_each_paraphrase_to_its_own_band_3_reason` (which asserts the
  gate reaches `payment` deterministically) and out of
  `::test_the_model_escalate_tool_is_the_second_net_for_every_gate_miss`.
  `::test_the_recorded_gate_misses_are_exactly_the_known_backlog` compares the measured miss set to the
  list both ways, so it fails if the fix under- or over-reaches; it passes with 11 entries.
  "Can I settle the balance over the phone?" and "How do I put money down to hold the slot?" stay on the
  backlog on purpose — closing them needs "settle the balance" and "put money down", which the brief did
  not ask for and which QA has not measured for false positives.
- `::test_adversarial_payment_request_uses_the_fixed_payment_script` — its first half fed a `FakeLLM`
  an `escalate` tool call because the gate used to miss the phrase. It now asserts the stronger thing:
  `llm.calls == []` (a payment request never reaches the model), `band == 3`, `gate_reason == "payment"`,
  `ended`, `ledger.items[0].type == "escalation_payment"`, and the reply still starts with the tenant's
  fixed payment script. Its second half (the phrasing that was already caught) is untouched.

Seen failing before the lexicon change, all four for the expected reason:

    FAILED ::test_rules_gate_routes_each_paraphrase_to_its_own_band_3_reason[payment-Can I pay over the phone now?]
    FAILED ::test_the_recorded_gate_misses_are_exactly_the_known_backlog
    FAILED ::test_payment_over_the_phone_is_gated_as_payment_not_a_lexicon_gap
    FAILED ::test_adversarial_payment_request_uses_the_fixed_payment_script
        E  AssertionError: a payment request reached the model

The file total is unchanged at 83: one parametrization left the second-net test and one entered the
paraphrase test.

Deviations:
- **The full-suite number was taken in an isolated copy of the tree, not in the working tree.**
  Other agents were fixing the other two gate-A findings in the same checkout at the same time, so
  `uv run pytest -q` in `runtime/` reported their in-flight TDD state, not mine: first
  `3 failed, 184 passed, 1 skipped` (`test_driver.py::test_guard_block_with_a_dead_ledger_refuses_and_claims_nothing`,
  two in `test_voice_processors.py` — one of them passed on its own thirty seconds later, when that
  agent saved `driver.py`), then `7 failed, 184 passed, 1 skipped` (five Slack signed-token tests in
  `test_http_actions.py` plus two in `test_delivery.py`, written before that agent's `slack.py` landed).
  None of the seven touches the payment lexicon. To get a number that is about this change, I built a
  clean tree from the last commit and copied only my three files into it:
  `git archive HEAD | tar -x -C <scratch>` then `cp runtime/spatalk/brain/rules.py runtime/tests/test_qa_gate_a.py
  runtime/scenarios/promptfooconfig.yaml <scratch>/runtime/...`, and ran
  `PYTHONPATH=<scratch>/runtime TEST_DATABASE_URL=...@localhost:5434/spatalk_test_paylex
  <runtime>/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` -> `187 passed, 1 skipped in 10.18s`.
  Module resolution was confirmed first (`import spatalk.brain.rules` -> the scratch copy's
  `rules.py`, `'pay over the phone' in DEFAULT_LEXICONS['payment']` -> True), so the run really
  exercised this change and not the installed editable path. 187 rather than the gate report's 184
  because the two neighbouring fixes had landed in `HEAD` by then, each with its tests. No file of
  another agent's was stashed, reverted or edited to get this number.
- **Ran against a throwaway database `spatalk_test_paylex` rather than `spatalk_test`.** Concurrent
  suites deadlocked on the shared test schema: `pg_stat_activity` showed one session
  `idle in transaction` for three minutes with four others waiting on `Lock` for `DROP TABLE runtime.jobs`
  and `DROP TABLE runtime.usage_events`. `TEST_DATABASE_URL` is all that needs overriding;
  `docker-compose.yml`, `settings.py` and `tests/conftest.py` keep their 5434 defaults, untouched.
  The database was dropped afterwards.
- **Touched a third file, `runtime/scenarios/promptfooconfig.yaml`, for one description string.** Case
  QA-A5 read "payment over the phone (rules gate misses this phrasing)", which this fix makes false;
  it now reads "(the rules gate catches this phrasing)". The `vars` and the `band3_payment_fixed_wording`
  assert are unchanged, so the promptfoo case still exercises the model path when a `GOOGLE_API_KEY`
  exists. No other file outside the brief's two was modified.

Notes for neighbours:
- The tenant escape hatch still works and is still tested elsewhere: a tenant can add payment terms in
  `tenants/<id>/guard.yaml` (`payment: ["financing", "skinc club"]` for Skincentrix), and `rules_gate`
  concatenates the built-in list with the tenant's.
- `KNOWN_GATE_MISSES` is down to 11 phrases. Anyone widening a lexicon must re-run
  `::test_the_recorded_gate_misses_are_exactly_the_known_backlog` and edit that set deliberately;
  it fails on drift in either direction.
- No model, migration, schema or interface changed, so nothing else in plan A needs propagation.
