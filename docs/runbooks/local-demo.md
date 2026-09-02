# Local demo: run the front desk from your laptop and let someone call it

What this gives you: a real phone number that rings into the runtime on your laptop, answered by the Skincentrix assistant, with every captured request arriving as a text on the owner's own mobile, answerable with `ACK 12` or `DONE 12`, and in a local mailbox you can show on screen. No VPS, no domain, no SES, no Cloudflare account.

## What you need (accounts)

| Account | Why | Time |
|---|---|---|
| Telnyx (portal.telnyx.com) | the phone number, the audio stream, and the texts that reach the owner's mobile | 30 min, plus business verification that can take up to a day: start it now |
| Soniox (console.soniox.com) | speech to text and text to speech, one key | 5 min |
| Inworld (platform.inworld.ai) | optional: alternative voice for the bake-off | 10 min |
| Google AI Studio | the model; already in `runtime/.env` | done |
| Your own mobile | where every tracked item lands, and where you reply `ACK` or `DONE` in front of the room | 0 min |

Not needed for the demo: OVH, Cloudflare, AWS SES, Stripe, Meta, Slack, a domain. Email delivery goes to a local Mailpit inbox instead of the internet.

## Software on the laptop

- Docker Desktop running (Postgres and Mailpit run in containers).
- The runtime environment from the build (`runtime/.venv` exists; if not: `cd runtime && uv venv --python 3.12 && uv pip install -e ".[dev]"`).
- A tunnel so Telnyx can reach the laptop. Two options:
  - `cloudflared` quick tunnel: no account, supports WebSockets, but the public URL changes every time you start it. Install: `winget install Cloudflare.cloudflared`.
  - `ngrok` with its free static domain: stable URL across restarts, needs an ngrok account. Browser visits to action links show a one-time ngrok interstitial; webhooks and audio are unaffected.

## One-time setup

1. Telnyx: complete verification, add a card, fund $20. Auth → API Keys → create → `TELNYX_API_KEY`. Numbers → Buy → Canada → Local → 905 → buy one. Voice → TeXML Applications → Create `spatalk-demo` with any placeholder Voice URL for now (you set the real one each demo). Assign the number to it.
2. Soniox: API key → `SONIOX_API_KEY`; pick a TTS voice from their voices page → `SONIOX_VOICE`.
3. Inworld (optional): workspace, runtime API key (copy the Base64 "Basic" credential) → `INWORLD_API_KEY`; pick a voice id → `INWORLD_VOICE`. Only if you want to compare voices.
4. Telnyx messaging, so items can reach your phone: Messaging → Messaging Profiles → Create `spatalk-demo-sms` and assign the number you bought to it (leave the webhook URL blank for now; you set it on demo day, when the tunnel hostname exists). Auth → Public Key → copy the Ed25519 public key: that is what proves an inbound text really came from Telnyx.
5. Put the number the texts are sent *from* into the tenant bundle: edit `runtime/tenants/skincentrix/tenant.yaml`, set `sms_from_number` to the number you bought, and re-run `spatalk tenant import` (below). The number the texts go *to* is never written into the bundle: the bundle names the environment variable `SKINCENTRIX_STAFF_SMS`, and only your `.env` holds the digits.
6. Append to `runtime/.env` (never commit it):

```
TELNYX_API_KEY=...
TELNYX_PUBLIC_KEY=...        # Telnyx → Auth → Public Key; without it inbound texts are 401
SONIOX_API_KEY=...
SONIOX_VOICE=Adrian
STT_PROVIDER=soniox
TTS_PROVIDER=soniox          # inworld or deepgram_aura2 are the swaps; each needs its own key
SKINCENTRIX_STAFF_SMS=+1905XXXXXXX   # YOUR mobile, in E.164: every item is texted here
SECRET_KEY=<64 random hex>
```

Leave `EDGE_SHARED_KEY` empty on the laptop. It is for the Cloudflare Worker front door, and when it is set the runtime accepts *only* the worker's key and rejects Telnyx's own signature, so your replies would come back 401.

`GOOGLE_API_KEY` and `LLM_MODEL` are already there. `SMTP_HOST` and `SMTP_PORT` default to Mailpit.

## Every demo: start-up (about five minutes)

From `runtime/` in Git Bash:

```bash
docker compose up -d db
docker start mailpit 2>/dev/null || docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
uv run alembic upgrade head
uv run spatalk tenant import tenants/skincentrix
uv run spatalk numbers add +1905XXXXXXX skincentrix      # your Telnyx local number, once
```

Second terminal, start the tunnel and copy its hostname:

```bash
cloudflared tunnel --url http://localhost:8000
# prints something like https://quiet-fox-1234.trycloudflare.com
```

Back in the first terminal, point the runtime at that hostname and start it:

```bash
printf 'PUBLIC_BASE_URL=https://quiet-fox-1234.trycloudflare.com\nMEDIA_WS_HOST=quiet-fox-1234.trycloudflare.com\n' >> .env
uv run spatalk serve
curl -s https://quiet-fox-1234.trycloudflare.com/healthz      # expect {"ok":true,"tenants":["skincentrix"],...}
```

Telnyx portal, two URLs to set from the same hostname:

- Voice → TeXML Applications → `spatalk-demo` → Voice URL `https://quiet-fox-1234.trycloudflare.com/telnyx/texml`, method POST → Save.
- Messaging → Messaging Profiles → `spatalk-demo-sms` → Inbound Settings → Webhook URL `https://quiet-fox-1234.trycloudflare.com/telnyx/sms`, method POST → Save. Without this the items still arrive on your phone; your `ACK` and `DONE` replies just go nowhere.

Check the round trip before anyone is watching: text `LIST` from your mobile to the demo number and you should get "Skincentrix front desk: 0 open item(s)." back within a few seconds.

Make one warm-up call yourself before anyone else does: the first call downloads the turn-detection and voice-activity model weights and is slower to answer.

If the tunnel restarts, the hostname changes: repeat the `.env` lines, the Telnyx Voice URL and the messaging profile webhook URL, then restart `spatalk serve`. With ngrok's static domain you skip this.

## What to show

Have the caller try, in this order, and keep three things visible: your phone (screen-mirrored if you can), Mailpit at http://localhost:8025, and a terminal running `uv run spatalk items list skincentrix` between calls.

1. "How much is the express treatment?" and "Are you open Sunday?" → answered from the knowledge base, no item (band 1).
2. "I need to cancel my appointment on Thursday, it's Dana." → the assistant says it has sent a request and when someone will confirm; a text arrives on your phone within seconds and an email lands in Mailpit with links (band 2). Reply `ACK 1` from your phone: `#1 acknowledged.` comes straight back, and the terminal shows the item acknowledged by `sms:+1905XXXXXXX`.
3. "Can you text me the link to book a facial?" → without a verified toll-free number the assistant says the team will send the link and files it (Tier C, honest).
4. "I have a rash after my laser session yesterday." → the fixed clinical script, including the emergency sentence; an urgent item (band 3). This is the safety story: no model was consulted.
5. "Can I just talk to a real person?" → the human-request script with a stated callback time (band 3).
6. "Just tell me it's booked for Thursday at 2." → the assistant will not say booked; if the model tries, the guard replaces the sentence and files a question. This is the honesty story.
7. "That's all, thanks, bye." → goodbye and hang-up.

Volunteered health context: "I'm pregnant, can I still book a facial?" → the request proceeds, the item carries a health-context flag, no advice is given. The text on your phone gains one line, "Caller mentioned a health condition; read the transcript first." The condition itself is not in the text; it is in the transcript behind the link.

## What the owner sees, and what to text back

Each tracked item is one text, at most three segments, built from the item's own columns and fixed wording. Nothing in it is written by the model (it arrives as one paragraph; it is wrapped here to fit the page):

```
Skincentrix front desk #1: Cancellation request via voice. Who: Dana +19055550101.
Due by 5:00 pm today. Reply ACK 1 or DONE 1.
Transcript: https://quiet-fox-1234.trycloudflare.com/a/<token>
```

An urgent item (the rash question, the request for a person) is prefixed `URGENT:`; an item that blew its due time is re-sent prefixed `ESCALATED, past due:`.

Replies are accepted from `SKINCENTRIX_STAFF_SMS` and from any number in the bundle's `delivery.staff_phone_numbers`:

| Text back | What happens |
|---|---|
| `ACK 1` (also `OK 1`, `ACKNOWLEDGE #1`) | the item becomes acknowledged, actor `sms:<your number>`, and `#1 acknowledged.` comes back |
| `DONE 1` (also `RESOLVE 1`, `RESOLVED #1`, `CLOSED 1`) | the item becomes resolved and `#1 resolved.` comes back |
| `LIST` | up to five open items, one line each with their ids |
| `#1 on my way` | the words after the id go to that customer verbatim and the assistant stops answering that conversation |
| anything else | the tenant's help text. A staff number never reaches the model, and no text you send becomes item content |

An id that is not one of this tenant's open items is answered `No open item #1.` — including an id belonging to another clinic and one somebody already resolved in the portal. The system never claims an action it did not take, which is the point of the whole demo.

The morning digest at 07:30 tenant time is one text: "Skincentrix front desk: 3 open item(s). Reply LIST for details."

Replying `STOP` opts your own number out like anyone else's: the runtime then texts you nothing, items go to email only, and `START` turns it back on.

## Optional extras for the demo

- Web chat: embed the widget in a local HTML page per `docs/runbooks/widget-install.md`, with the API pointed at the tunnel host. Booking links show inline.
- Customers texting the number: the assistant answers inbound SMS as well, but a local number texting strangers is unregistered A2P traffic that Canadian carriers may filter, and the production path is a verified toll-free number. Texts between the demo number and your own handset are reliable enough to show; do not promise a client that customer texting works until verification is through.
- Portal: needs WSL and `portal/.env.server`; not required for the phone demo.

## On the road

- Any internet works, including a phone hotspot: the tunnel is outbound only, nothing needs inbound ports.
- Keep Docker Desktop, the tunnel and `spatalk serve` running; turn off sleep on the laptop.
- Cost per demo call is a few cents. The tunnel adds roughly 50 to 100 ms per turn compared with the real deployment, where audio bypasses any proxy.
- Latency and turn count for each call print at call end in the `spatalk serve` log (`call <id> turns=… p50=…ms p95=…ms`).

## Demoing to a different business

Copy `tenants/skincentrix/` to `tenants/<slug>/`, edit the five files (name, hours, services, knowledge, scripts), then `uv run spatalk tenant import tenants/<slug>` and `uv run spatalk numbers add <number> <slug> voice`. One number maps to one tenant, so either buy a second local number ($1) or re-point the same number between demos.
