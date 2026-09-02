# operations plan Task E9: Monthly cost reconciliation

Status: done

Commit: <pending>

Tests: `uv run pytest tests/test_ops_cost_report.py -q` -> 22/22; full suite
`uv run pytest -q` -> 772 passed, 1 skipped, 1 failed (773 collected excluding the skip);
the single failure is pre-existing and belongs to another task, see Deviations.

Interfaces produced: `spatalk.ops.cost_report.{RUN_KIND, PRICE_CAD_PER_TENANT_MONTH,
month_window, previous_month, per_tenant_fixed, add_invoice, recorded_invoices, drift_pct,
cost_report, providers_by_drift, format_cad, report_email, run_cost_report}`;
`spatalk.models.ProviderInvoice`;
`spatalk.ledger.scheduler.{MONTHLY_COST_REPORT_UTC_HOUR, ensure_monthly_cost_report_scheduled}`;
CLI `spatalk invoices add <provider> <YYYY-MM> <amount_cad>` and `spatalk cost report <YYYY-MM>`;
Alembic `0009` (`provider_invoices`, down_revision `0008_whatsapp`).

`cost_report(ctx, month, price_cad=999.0)` returns

```
{month, price_cad,
 per_tenant: {tenant: {<channel>: cad, ..., fixed: cad, total: cad}},
 per_tenant_margin_pct: {tenant: pct},
 per_provider_estimate: {provider: cad},
 invoices: {provider: cad | None},
 drift_pct: {provider: pct | None}}
```

## What it does

`spatalk.rates.estimate_cad` prices each `(tenant, channel, provider, unit)` group of the
month's `usage_events`; `provider_invoices` holds what each provider actually billed; drift
is `(invoice - estimate) / estimate` as a percentage. `run_cost_report` emails the summary
to `OPS_EMAIL` and writes an `ops_runs` row whether or not the mail goes out, so a month
nobody reconciled is a missing row rather than silence. The scheduler queues
`ops.cost_report` once a month from 05:00 UTC on the first, with the month just ended in the
payload.

Three decisions the plan left open, taken and documented in the module docstring:

1. **The month is a UTC calendar month.** Everything else in the runtime uses tenant time
   (CLAUDE.md non-negotiable 8), but an invoice is cut on the provider's calendar; a
   tenant-local month would sum two tenants over two different windows and then compare the
   union against one invoice. `docs/reference/data-model.md` already specifies
   `provider_invoices.month` as `YYYY-MM`, which this reads as UTC.
2. **A provider with no invoice is `None`, never `0.0`,** and the email prints
   "not entered". Zero is the one reading that makes an unentered invoice look like a free
   month. `drift_pct` is `None` both when no invoice was entered and when an invoice stands
   against an estimate of zero, where a percentage would be a division by zero rather than a
   finding.
3. **The per-tenant total carries `per_tenant_fixed_cad` (CA$4.50) from the rates table**
   alongside the metered channels, so the gross margin against CA$999 counts the DID and
   toll-free rentals too. Every channel key plus `fixed` sums to `total`. A tenant with no
   usage still appears, with its fixed cost only: a quiet tenant is not a free one.

`PRICE_CAD_PER_TENANT_MONTH = 999.0` lives in the module rather than in tenant config,
because it is the number spec §6 wrote the business case against. A tenant on a different
contract is a portal concern; the reconciliation would then read its price from the portal.

## Deviations

- **Pre-existing suite failure, not this task's and not closed by it:**
  `tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table` fails at
  HEAD. `docs/research/rates.json` gained `reference_bundles_usd_per_min` (Telnyx Voice AI
  Agents) and a `soniox_tts` entry in commits `a0939cc` and `4fbee36`
  ("docs(research): ..."), and `runtime/spatalk/rates.json` was never re-synced with
  `make sync-rates`. Evidence: `git diff --stat HEAD -- runtime/spatalk/rates.json
  docs/research/rates.json` is empty (both files are exactly as committed), and
  `uv run pytest tests/test_delivery.py tests/test_edge_sync.py tests/test_internal_api.py
  tests/test_ops_alerts.py tests/test_tier_c.py -q` -> `1 failed, 95 passed` with that one
  test as the only failure, on a checkout carrying none of this task's modules. Nothing in
  E9 touches either file. Deliberately not fixed here: re-syncing the packaged rates table
  changes what the portal's cost estimate and this reconciliation charge for, which is the
  research task's call, not this one's.
- No other deviation. Every interface the plan names exists with that name; the plan's
  `cost_report(ctx, month)` signature gained one keyword-only-by-default `price_cad`
  parameter so a different contract price can be priced without editing the module.

## Notes for neighbours

- **Whoever owns the rates table:** run `make sync-rates` and commit
  `runtime/spatalk/rates.json`. The suite is one test from green and that is the test.
- The scheduler now calls `ensure_monthly_cost_report_scheduled(ctx)` inside
  `run_scheduler_forever`, appended after E4's nightly-audit hook. `ALERT_CHECK_SECONDS` and
  the tick are untouched.
- `ops.cost_report` is the third `ops_runs.kind` (after `ops.retention` and
  `ops.nightly_audit`) and the third registered ops job handler. Its `ops_runs.summary` is
  the full report dict, so a portal health page can read a month's reconciliation straight
  out of `ops_runs` without re-running it.
- Alembic head is now `0009`. Chain the next migration after it.
- E10 adds no usage unit, but if a transfer meters carrier minutes, record them as a
  `usage_events` row with the carrier's provider name and one of `rates.PRICED_UNITS`;
  anything else prices at zero and will read as free in this report.
- The founder-facing half of this task is two commands, and no runbook names them yet:
  `spatalk invoices add telnyx 2026-08 41.50` after each provider invoice arrives, and
  `spatalk cost report 2026-08` to see the drift. Worth a line in
  `docs/runbooks/accounts-and-env.md` or a monthly calendar entry alongside E2's restore
  drill.
