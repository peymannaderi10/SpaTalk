# Repository chores that must stay reproducible. Everything else is in CLAUDE.md.

.PHONY: sync-rates openapi

# The deployed runtime carries its own prices: `spatalk/rates.json` is a copy of the
# researched table. `tests/test_internal_api.py` fails when the two drift.
sync-rates:
	cp ../docs/research/rates.json spatalk/rates.json

# The portal's contract. Regenerating it is how a contract change is declared;
# `tests/test_contract_snapshot.py` fails until the committed file matches the routes.
openapi:
	uv run spatalk openapi --internal --out ../docs/contracts/runtime-internal.openapi.json
