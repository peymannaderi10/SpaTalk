# Monitoring, error reporting and alerts

Operations plan, Task E7. Two audiences: an external monitor that decides whether the
service is alive, and the runtime itself, which knows things the monitor cannot see.

The rule the whole design follows: **one alert per incident per six hours.** An alert that
repeats gets filtered, and a filtered alert is the same as no alert.

## What the runtime already does for you

Every five minutes the scheduler re-derives four conditions and raises each one by email to
`OPS_EMAIL` and, when `OPS_SMS_NUMBER` is set, by one SMS:

| key | condition | what it means |
|---|---|---|
| `escalation_delivery_dead` | a `deliver.*` job with `escalation: true` in state `dead` | an item passed its due time, the runtime tried to tell the clinic, and the attempt died. A customer is waiting and nobody knows. |
| `jobs_dead` | any job in state `dead` | work was dropped after five attempts. The body names the job ids, kinds and last errors. |
| `queue_stale` | the oldest **due** queued job has waited over 5 minutes | the job worker is not draining. Deliveries, digests and follow-ups are all behind it. |
| `scheduler_tick_stale` | the last completed scheduler pass is over 3 minutes old | the scheduler loop stalled mid-pass. Nothing is being escalated or queued. |

Two more conditions come from elsewhere and use the same `alerts.notify`:
`audit_blocking:<tenant>:<day>` from the nightly audit (Task E4) and the per-stage SLO
breach from Task E5.

Every alert writes an `alert_log` row **before** the email is attempted, so a dead mail
server cannot erase the record that the incident happened. To see what has fired:

```
docker compose exec -T db psql -U spatalk -c \
  "SELECT sent_at, key, subject FROM runtime.alert_log ORDER BY id DESC LIMIT 20"
```

## What the runtime cannot do for you

It cannot tell you it is down. That is the monitor's job, and it must run somewhere else.

### 1. UptimeRobot HTTP monitor on `/healthz`

Free plan, 5-minute interval. Create two monitors on the same URL, because a keyword
monitor matches one string.

* **URL**: `https://<API_HOST>/healthz` (the value of `API_HOST` in `runtime/.env`).
* **Monitor 1** — type *HTTP(s) keyword*, keyword `"ok":true`, "alert when keyword **not
  exists**". This catches the process being down, the reverse proxy being down, and the
  certificate expiring.
* **Monitor 2** — type *HTTP(s) keyword*, keyword `"dead_jobs":0`, "alert when keyword
  **not exists**". This catches a runtime that is serving happily while dropping work.
  The response is compact JSON with no spaces, so those exact bytes are what is on the
  wire; `curl -s https://<API_HOST>/healthz` shows them.
* Alert contacts: the founder's email and SMS. Both monitors, no delay.

`/healthz` is unauthenticated and rate-limit exempt by design (Task E8). It carries the
tenant list, the config version per tenant and the deployed commit; it never carries a
caller, a transcript or a key.

```json
{"ok":true,"tenants":["skincentrix"],"config_versions":{"skincentrix":3},
 "commit":"9f2c1ab","queued_jobs":2,"oldest_queued_age_s":11,"dead_jobs":0,
 "last_scheduler_tick":"2026-09-02T04:31:07+00:00"}
```

* `queued_jobs` — everything still queued, including work deliberately scheduled for later
  (the 03:00 retention job sits here all evening). Not an error on its own.
* `oldest_queued_age_s` — how long the oldest job that is *already due* has waited. Over
  300 means the worker has stopped draining.
* `dead_jobs` — work abandoned after five attempts. Should always be 0.
* `last_scheduler_tick` — the end of the last completed scheduler pass, ISO 8601, or `null`
  when the process has just started. More than 3 minutes old means the loop is stuck.

### 2. UptimeRobot port monitor on the media host

The voice WebSocket does not go through the same path as the API, and a call fails silently
if it is down. Create a third monitor:

* Type *Port*, host `<MEDIA_HOST>` (the value of `MEDIA_HOST` in `runtime/.env`, the
  DNS-only record that points straight at the VPS), port **443**, 5-minute interval.

A TCP check is all that is possible here: the media endpoint is `wss://<MEDIA_HOST>/ws/{token}`
and the token is single-use and signed, so an HTTP monitor cannot open a real session.

### 3. Check it works

Do this once, after creating the monitors, and again after any deploy that changes Caddy:

1. `curl -s https://<API_HOST>/healthz | head -c 200` → both keywords present.
2. Stop the app container (`docker compose stop app`); within 5 minutes monitor 1 alerts.
   Start it again and confirm the recovery notice arrives.
3. Insert a fake dead job, confirm monitor 2 alerts and that the email from the runtime
   arrives too, then remove it:
   ```
   docker compose exec -T db psql -U spatalk -c \
     "INSERT INTO runtime.jobs (kind, payload, state, last_error) \
      VALUES ('deliver.email', '{}'::jsonb, 'dead', 'monitor drill')"
   docker compose exec -T db psql -U spatalk -c \
     "DELETE FROM runtime.jobs WHERE last_error = 'monitor drill'"
   ```
   Record the date of the drill in `docs/runbooks/accounts-and-env.md`.

## Environment

| variable | effect |
|---|---|
| `OPS_EMAIL` | where every alert and the nightly audit report go. Empty means the alert is still recorded in `alert_log`, only the email is skipped. |
| `OPS_SMS_NUMBER` | when set, one SMS per incident per six hours on top of the email. |
| `SENTRY_DSN` | when set, unhandled exceptions go to Sentry. Empty means no error tracker is initialised at all. |
| `LOG_FORMAT` | `json` makes loguru emit one JSON object per line for a log shipper; anything else keeps the human-readable console format. |
| `GIT_COMMIT` | set by the image build (`docker build --build-arg GIT_COMMIT=$(git rev-parse --short HEAD)`), reported as `commit` on `/healthz`. |

### The ops SMS needs a number to send *from*

There is one Telnyx account and the runtime owns no operations number of its own, so an
alert SMS goes out from the first tenant `sms_from_number` the registry knows. Skincentrix
has `sms_from_number: null` until the toll-free number is verified
(`docs/runbooks/accounts-and-env.md`), so **until then, setting `OPS_SMS_NUMBER` changes
nothing**: the alert is recorded and emailed, and a line goes into the log saying no number
was available. It starts working by itself the day the number lands in the tenant bundle.

### Sentry, if you want it

Optional, and off by default: a free Sentry project costs nothing but is one more account
and one more processor of data. If you turn it on, the runtime initialises it with
`send_default_pii=False` and two scrubbers of our own that mask phone numbers and email
addresses out of every event, breadcrumb, exception value and `extra` field before it
leaves the process (`spatalk/ops/alerts.py`, `scrub_pii`). `LOG_FORMAT=json` sets loguru's
`diagnose=False` for the same reason: a diagnostic traceback prints the value of every
local variable, and on this service that means a caller's number.

Nothing else is shipped off the box. Latency, cost and audit numbers stay in Postgres and
are read through the portal (`/internal/*`).
