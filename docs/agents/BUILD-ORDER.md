# Overnight build order

How to run the five plans with engineer, QA and reviewer agents so that in the morning the founder only fills environment variables, creates provider accounts, deploys, and places a call.

## What "done in the morning" means

- Every task in all five plans has a commit, and the full test suites pass on a clean checkout: `runtime` pytest, `portal` build and e2e, `edge` vitest.
- The promptfoo suite passes if `GOOGLE_API_KEY` was available; otherwise it is marked "not run" in the report, never "passed".
- `docs/reports/<date>-overnight-build.md` exists with the report format at the bottom of this file.
- Nothing external happened: no numbers bought, no deploys, no DNS, no paid calls beyond the capped promptfoo runs.

## Phases and dependencies

```
P-1 Repository               git init; commit CLAUDE.md and docs/ as "docs: build package"   (orchestrator, before anything)
P0  Scaffold                 runtime Task 1                                  (serial, 1 engineer)
P1  Brain and config         runtime Tasks 2, 3, 4, 5, 6, 11                 (2 lanes: [2,3] then [4,5,6,11])
P2  Persistence and ledger   runtime Tasks 7, 8, 9, 10                       (serial: 7 -> 8 -> 9 -> 10)
P3  Drivers                  runtime Tasks 12, 13, 14                        (12 and 13 in parallel, then 14)
P4  Suite and containers     runtime Tasks 15, 16 (files only, no deploy)    (parallel)
    --- QA gate A: runtime ---
P5  Text channels            text-channels plan B1..B6                       (B1 edge worker parallel with B2..B5; B6 last)
P6  Portal                   portal plan C1..C9                              (C3 is on the runtime side; C1 and C3 in parallel first; C9 last)
P7  Instagram                instagram plan D1..D3                           (after P5 human-takeover and P6 settings page)
    --- QA gate B: channels and portal ---
P8  Operations               operations plan E1..E10                         (mostly parallel; E10 last)
    --- QA gate C: whole system ---
Reviewer pass, report, stop.
```

Dependencies that matter: Task 7 (DB) before anything that touches Postgres; Task 12 (`dispatch_tool`) before Task 13 (voice handlers); Task 14 before Task 15's provider test and before every follow-on plan; C3 (runtime internal API) before C4/C5; B5 (takeover) before D1's DM handling reuses it.

## What the run can verify without any provider account

Every task's tests run on fakes and a local Postgres. Internet access is needed for PyPI, npm, the Wasp CLI and the Smart Turn and Silero model weights; no account is.

| Needs | Tasks | Report as |
|---|---|---|
| nothing | A1 to A16 (files), B1 to B6, C1 to C9, D1 to D5, E1 to E9 | passed or failed |
| `GOOGLE_API_KEY` | promptfoo suite (A15, B6, D5), live Gemini test in `test_driver.py`, judge test in E4 | "not run (no key)" when absent, never "passed" |
| `OPENAI_API_KEY` | live client test in E6 | same |
| live platform (morning) | first-call checklist, latency bake-off, real Slack and SES delivery, Meta webhook verification and OAuth, Stripe test webhooks, Worker deploy, portal on its hosts, E10 spike | listed under "What the founder must do this morning" |

## Agent roles

- **Engineer**: one task at a time, TDD, commit, report. Brief: `docs/agents/ENGINEER.md`.
- **QA**: runs at each gate; owns the acceptance matrix; writes adversarial scenarios; blocks on severity. Brief: `docs/agents/QA.md`.
- **Reviewer**: after QA gate C; reads diffs against the spec's invariants; produces the findings list the founder reviews in the morning. Brief: `docs/agents/REVIEWER.md`.
- Every agent also gets `docs/reference/` (data model, tenant config, API surface and payload shapes, flows). When a plan and a reference document disagree, the reference document wins and the deviation is reported.
- **Orchestrator** (the workflow itself): dispatches tasks in the order above, passes each engineer the task text plus `CLAUDE.md` plus the "Produces/Consumes" blocks of neighbouring tasks, collects reports, stops the run on a blocking QA finding it cannot resolve in two attempts.

## Orchestration prompt (paste into a Claude Code session with the Workflow tool)

```
Use a workflow to build the SpaTalk platform overnight from the plans in this repository.

Read CLAUDE.md and docs/agents/BUILD-ORDER.md first. Execute the phases in the order given there.
For every task: dispatch a fresh engineer agent with docs/agents/ENGINEER.md, CLAUDE.md, the four files in
docs/reference/, the task text from the relevant plan, and the Interfaces blocks of the tasks immediately
before and after it.
Require the engineer's report in the format in ENGINEER.md and store it under docs/reports/tasks/.
At each QA gate dispatch a QA agent with docs/agents/QA.md; if it returns a blocking finding, dispatch
one engineer to fix it and re-run QA once; if still blocking, stop the run and write the report.
After QA gate C dispatch a reviewer agent with docs/agents/REVIEWER.md.
Never deploy, buy numbers, change DNS, or call paid APIs other than Gemini for promptfoo (max one eval
per gate). Do not weaken tests. Finish by writing docs/reports/<date>-overnight-build.md in the format
at the end of BUILD-ORDER.md and committing it.
```

Sizing note: about 45 engineer tasks, 3 QA gates and 1 review, so tell the workflow the size guideline is "large" or the run will refuse to fan out.

## Parallelism rules

- Never two engineers in the same file. Lanes above are chosen so files do not overlap.
- Shared files that several tasks touch (`models.py`, `conftest.py`, `app.py`, `pyproject.toml`) are edited only by the task that the plan names as their owner; other tasks append via their own modules and ask the orchestrator to merge.
- Alembic: one migration per phase, generated by the last task of the phase that changed models, never by parallel tasks.

## Stop conditions

Stop and report rather than improvise when: a Pipecat import in the smoke test fails and the fix is not a rename; a plan's interface cannot be honoured without changing a consumer; a test needs a live provider key that is not present; the Wasp multi-schema spike (portal C1) fails in both orders.

## Morning report format (`docs/reports/<date>-overnight-build.md`)

```
# Overnight build report, <date>

## Result
one line: all phases complete | stopped at <phase/task> because <reason>

## Test evidence
runtime: pytest <passed>/<total>, ruff clean yes/no
portal: wasp build ok yes/no, e2e <passed>/<total>
edge: vitest <passed>/<total>
promptfoo: <passed>/<total> | not run (no key)

## Deviations from the plans
- <task>: <what changed and why>   (one line each; link the task report)

## QA gate findings
- gate A/B/C: <severity> <finding> -> fixed in <commit> | open

## Reviewer findings (open)
- <file:line> <invariant> <one sentence>

## What the founder must do this morning
1. docs/runbooks/accounts-and-env.md steps marked "now"
2. fill runtime/.env, portal/.env.server, edge secrets
3. deploy per docs/runbooks/deploy.md, then the first-call checklist
4. anything the run could not verify without keys (list)
```
