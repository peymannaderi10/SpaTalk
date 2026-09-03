# Jane sync timing test: is one minute each way real?

What this answers, with measurements instead of documentation:

1. **Jane to us.** When a booking is made in Jane, how many seconds until the practitioner's private calendar feed shows it, and is the feed served fresh or from a cache?
2. **Google to Jane.** When an event is written to a Google Calendar linked to a Jane staff profile, how many seconds until Jane shows the grey Busy block and stops offering the slot online?

Jane's guide says the second direction takes "about a minute". Nothing published covers the first. Both need one real Jane account for about an hour; nothing in this test writes to Jane.

## Before you start

- **Ask Jane in writing.** Jane's Terms of Use prohibit collecting information from the service with a "robot, spider, crawler, program" without written consent. The calendar feed is an official feature meant to be polled by calendar apps, and this test polls one feed of the clinic's own account, but a service that polls it every minute in production is a different thing. Have the clinic owner ask Jane support one question, in their own words: "May a third-party service we use poll our staff members' private calendar feeds every minute to read free and busy times only?" Keep the answer. If Jane says no, the read-only availability idea is dead and the ledger stays as it is.
- **Jane's demo clinic will not do.** Jane offers a shared demo clinic (credentials weekly from their support or community), but Google Calendar Sync needs a real staff profile linking a real Google account, and the demo clinic is shared with strangers. Use Skincentrix's own account with one practitioner who agrees, or a paid trial clinic of your own.
- **Privacy.** The feed can contain client names and appointment notes. The probe script never prints or stores titles; it logs hashed event ids and times only. Do not paste feed contents into chat or email. Delete the feed URL from your machine after the test; Jane can regenerate it.

## You need

| Item | Where |
|---|---|
| One practitioner's private **Appointments** feed URL | their Jane staff profile → Create calendar feeds → copy the appointments link |
| The same staff profile linked to a Google account | staff profile → Google Calendar Sync → connect |
| Jane's schedule open in a browser, on that practitioner | any admin login |
| The clinic's online booking page open in a private window | skincentrix.janeapp.com |
| Python 3 on your laptop | already there for the runtime |

## Test 1: Jane to us (feed freshness)

Terminal 1, from the repo root:

```bash
python docs/research/jane-sync-probe.py "<feed url>" --every 10 --minutes 30 --log jane-probe.log
```

Read the first lines it prints. `cache headers:` tells you whether Jane sits behind a cache. `Age` above 0, or a `cf-cache-status: HIT`, means a cached copy; `Cache-Control: max-age=N` is how long that copy may be served. No such headers, or `Age: 0` every time, means the feed is generated per request.

Then, in Jane, book a test appointment for that practitioner a few days out, and at the same moment run in terminal 2:

```bash
python docs/research/jane-sync-probe.py --mark "booked test appointment Thu 14:00"
```

Watch terminal 1 for a `CHANGE` line. The difference between the `MARK` timestamp and the `CHANGE` timestamp is the Jane-to-us latency at a 10-second poll. Repeat with a cancellation (`--mark "cancelled ..."`) and with a reschedule. Three data points are enough.

What you want to see: `CHANGE` within 20 seconds of every `MARK`, and no cache headers that say HIT. That means a one-minute poll in production sees a booking within about a minute.

What would kill the idea: `CHANGE` arriving minutes later, or a `max-age` in the hundreds of seconds, or a HIT status. Then the feed is cached upstream and no polling rate of ours can beat the cache.

## Test 2: Google to Jane (the hold direction)

Keep terminal 1 running: it will also show whether Google-synced Busy blocks appear in the feed at all (Jane's guide does not say).

1. Open Jane's schedule on the practitioner in one window and the online booking page for one of their treatments in a private window. Note a slot that is currently offered online, say Thursday 14:00.
2. In the Google Calendar that is linked to that staff profile, create an event "Hold test" covering Thursday 14:00 to 14:30. Note the second you press Save.
3. Refresh the Jane schedule every 15 seconds. Note when the grey "Busy - Google Calendar Event" block appears.
4. Refresh the online booking page every 15 seconds. Note when Thursday 14:00 stops being offered.
5. Delete the Google event. Note when the block disappears and the slot returns.

Record all five times. Jane's guide says the block appears "after a minute". What matters for us is step 4, because that is when a client can no longer double-book. Do the whole sequence three times at different times of day.

## What the numbers mean for the design

- Test 1 under 60 seconds and no cache: **read-only availability is buildable.** The assistant can offer real openings and the request goes to the ledger with an exact slot.
- Test 2 under 90 seconds at step 4, every time: a hold placed through Google **closes the slot within that window.** The race is the time between the assistant's promise and step 4. You said you accept a one-minute race; this test tells you whether it is one minute or five.
- Anything longer, or inconsistent across the three runs: do not offer holds. Offer openings, file the request, let a person book.

Bring the log file and the five recorded times back and I will turn them into the plan, or into a "no".
