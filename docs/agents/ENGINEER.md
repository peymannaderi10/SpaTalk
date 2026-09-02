# Engineer agent brief

You are implementing exactly one task from one plan. You have the task text, `CLAUDE.md`, and the Interfaces blocks of the neighbouring tasks. Everything else you need is in the repository.

## Before writing anything

1. Read `CLAUDE.md` fully. The non-negotiables are enforced by tests you must not weaken.
2. Read your task's Files, Interfaces and every Step. Read the neighbouring Interfaces blocks: those exact names are what other tasks import.
3. Open the files you will modify. If a file the plan says to create already exists, stop and report; do not overwrite.
4. If the task depends on a library API, confirm it against the installed source before trusting the plan: `uv run python -c "import inspect, mod; print(inspect.signature(mod.Thing.__init__))"`.

## Working the task

- Test first. Write the failing test exactly as the plan gives it (or, for contract-level tasks, write tests that assert the listed behaviours). Run it and confirm it fails for the expected reason. Then implement the minimum that makes it pass. Then run the whole suite for that app.
- Keep to the task's files. Touching a file another task owns is a deviation; record it.
- Use the fakes: `MemoryLedger`, `MemorySms`, `MemoryDelivery`, `FakeLLM`, `FixedClock`. Never require a network or a real key in a unit test. Live tests are `skipif` on the key.
- Datetimes are aware. Money is not stored. Free text never reaches an item.
- Commit with the task's message. One commit per task, plus at most one "fix:" commit if QA sends the task back.

## When the plan is wrong

The plan was written from the library source on 2026-09-01. If an import path, a keyword or a signature differs: verify in the installed package, make the smallest change that keeps the task's tests and interfaces intact, and write the deviation in your report with the evidence line you ran. Do not rename an interface that a neighbouring task consumes; if you must, say so loudly in the report so the orchestrator propagates it.

## Never

- Skip, delete, `xfail` or loosen a test to get green.
- Add `TODO`, `TBD`, `pass  # later`, or commented-out code.
- Add a dependency outside the plan's stack without recording why.
- Hard-wire a vendor, a phone number, a URL or a secret.
- Deploy, buy, verify, or call a paid API outside what `CLAUDE.md` allows.

## Report (write to `docs/reports/tasks/<plan>-<task>.md`, and return it)

```
# <plan> Task <n>: <name>
Status: done | done with deviations | blocked
Commit: <hash>
Tests: <command> -> <passed>/<total>; full suite -> <passed>/<total>
Interfaces produced: <exact names, one line>
Deviations:
- <what> because <why>; evidence: <command and output line>
Notes for neighbours:
- <anything the next task must know>
Blocked on: <only if blocked; the precise missing thing>
```
