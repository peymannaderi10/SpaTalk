# Carrier failover and the loop guard

Two protections for the same failure: the phone rings and this runtime cannot answer it
honestly. One is carrier-side and needs no server (the failover bin); one is in the runtime
and stops the assistant answering itself (the loop guard).

Everything under "Set it up" and "Verify it" is run by a person on the founder's machine and
in the Telnyx portal. No agent has executed any of it: changing a carrier setting and
placing a call are the founder's steps (`CLAUDE.md`, "Things agents must not do overnight").

---

## 1. The carrier failover bin

### What it is

Telnyx retries the TeXML application's Voice URL and, when it still cannot reach us, calls
the **Failover URL**. If that URL is also us, the caller hears silence or a carrier error.
So the failover URL points at a **TeXML Bin**: a static document Telnyx hosts and plays on
its own infrastructure. When the VPS is down, the network is down, or the container is
mid-restart, the caller still hears the clinic's own wording and hangs up knowing what to do.

The bin cannot promise anything and cannot take a message. It says the clinic's `failover`
script (`docs/reference/tenant-config.md`) and hangs up. That is the honest answer when the
system that files requests is not running: nothing was captured, so nothing is claimed.

### Get the body

```bash
docker compose exec app spatalk texml failover-bin skincentrix
```

It prints the tenant's live `scripts.failover` wrapped in TeXML, for example:

```xml
<Response><Say voice="female" language="en-CA">We can't take your call right now. Please text us at +18885550100 or book online at https://skincentrix.janeapp.com/locations/skincentrix.</Say><Hangup/></Response>
```

> **Run this after the toll-free number is verified.** With `sms_from_number: null` in
> `tenants/<id>/tenant.yaml`, the `{sms_number}` placeholder falls back to the clinic's
> `public_phone`, and the bin then tells callers to text a line that cannot receive texts.
> Re-run the command and re-paste the bin whenever the SMS number, the booking URL or the
> `failover` script changes: the bin is a copy, and nothing keeps it in sync for you.

### Set it up

1. Telnyx portal → **Voice → TeXML → TeXML Bins → Create**. Paste the printed body. Name it
   `spatalk-failover-<tenant>`. Save, and copy the bin's URL.
2. **Voice → TeXML → Applications →** the application the number is assigned to. Set
   **Failover URL** to the bin URL, method `POST`. Leave the Voice URL pointing at
   `https://api.<domain>/telnyx/texml`. Save.
3. Record the date and the bin URL in `docs/runbooks/accounts-and-env.md` alongside the
   other external clocks (spec §10 weakness 10).

### Verify it

Do this once at set-up and again after any change to the TeXML application.

1. From a phone that is **not** the clinic's line and not one of our numbers, call the
   clinic's Telnyx number. Expect the assistant's disclosure. Hang up.
2. On the VPS: `docker compose stop app` (leave `db` and `caddy` running).
3. Call again. Expected: within a few seconds you hear the failover wording in one voice,
   then the call ends. There must be no ring-out, no silence longer than about five seconds,
   and no carrier error tone.
4. `docker compose start app`, wait for `GET /healthz` to return `"ok":true`, and call once
   more to confirm the normal path is back.
5. Write the date, the observed delay before the message, and the outcome here:

| Date | Delay before the message | Result | By |
|---|---|---|---|
| _(not yet run — needs a purchased number and a deployed VPS)_ | | | |

### The voicemail variant, and why it is not the default

A bin can record instead of hanging up:

```xml
<Response><Say voice="female" language="en-CA">…</Say><Record maxLength="120" playBeep="true"/></Response>
```

`<Record>` creates a **carrier-side audio recording** of a caller who may be describing a
medical problem. That is patient audio living somewhere this system's retention job cannot
reach, outside `retention_days`, and outside the "recording off by default" rule
(`CLAUDE.md` non-negotiable 9, `docs/reference/data-model.md` retention). So it is opt-in
per tenant, only after the tenant has agreed in writing where those recordings live, who
listens to them and when they are deleted. Do not add it because it seems more helpful.

---

## 2. The loop guard

### What it is

`spatalk/ops/loop_guard.py`. On every inbound call, before a conversation exists, the
runtime compares `From` against the numbers this tenant owns: everything the registry maps
to the tenant (`tenant_numbers`), plus the clinic's `public_phone` from the bundle,
normalised to E.164 so `905-703-7546` and `+19057037546` are the same number.

On a match the caller hears `scripts.loop_guard` ("This line is answered by the clinic's
assistant and cannot transfer to itself. Please call back from another number."), the call
is hung up, a row is written to `runtime.alert_log`, and **no conversation is started**.

### Why

The forwarding chain in front of this system is configured by hand at TELUS, and the
clinic's back-line may not exist (spec §10, weakness 7). Two ways that bites: our own
number forwarded back to itself, so the assistant talks to the assistant on two billed
legs and files a conversation nobody made; or staff "testing" the assistant from the
clinic's public line and being treated as a customer. Both look identical to the guard.

### Check it

```sql
-- self-calls refused, newest first
select key, subject, sent_at from runtime.alert_log
where key like 'loop_guard:%' order by sent_at desc limit 20;
```

More than one or two rows means the forwarding chain is wrong, not that a customer is
confused. Open the TELUS forwarding settings and the Telnyx number assignment before
changing anything in the runtime.

A live check, once the number exists: call the Telnyx number from the clinic's own line.
Expected: the loop-guard sentence, a hangup, one new `alert_log` row, and no new row in
`runtime.conversations`.
