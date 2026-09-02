# Local demo: run the front desk from your laptop and let someone call it

What this gives you: a real phone number that rings into the runtime on your laptop, answered by the Skincentrix assistant, with every captured request landing in Slack and in a local mailbox you can show on screen. No VPS, no domain, no SES, no Cloudflare account.

## What you need (accounts)

| Account | Why | Time |
|---|---|---|
| Telnyx (portal.telnyx.com) | the phone number and the audio stream | 30 min, plus business verification that can take up to a day: start it now |
| Soniox (console.soniox.com) | speech to text and text to speech, one key | 5 min |
| Inworld (platform.inworld.ai) | optional: alternative voice for the bake-off | 10 min |
| Google AI Studio | the model; already in `runtime/.env` | done |
| Slack (api.slack.com/apps) | optional but the best demo moment: items arrive with Acknowledge and Resolve buttons | 15 min |

Not needed for the demo: OVH, Cloudflare, AWS SES, Stripe, Meta, a domain. Email delivery goes to a local Mailpit inbox instead of the internet.

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
4. Slack (optional): create the app from the manifest in `docs/runbooks/accounts-and-env.md` step 8, install it, create `#skincentrix-frontdesk`, add an incoming webhook to that channel → `SKINCENTRIX_SLACK_WEBHOOK`; Basic Information → Signing Secret → `SLACK_SIGNING_SECRET`.
5. Append to `runtime/.env` (never commit it):

```
TELNYX_API_KEY=...
SONIOX_API_KEY=...
SONIOX_VOICE=Adrian
STT_PROVIDER=soniox
TTS_PROVIDER=soniox          # inworld or deepgram_aura2 are the swaps; each needs its own key
SLACK_SIGNING_SECRET=...
SKINCENTRIX_SLACK_WEBHOOK=https://hooks.slack.com/services/...
SECRET_KEY=<64 random hex>
```

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

Telnyx portal → Voice → TeXML Applications → `spatalk-demo` → Voice URL `https://quiet-fox-1234.trycloudflare.com/telnyx/texml`, method POST → Save. If you use Slack buttons, also set the Slack app's Interactivity Request URL to `https://<same host>/slack/interactions`.

Make one warm-up call yourself before anyone else does: the first call downloads the turn-detection and voice-activity model weights and is slower to answer.

If the tunnel restarts, the hostname changes: repeat the `.env` lines, the Telnyx Voice URL and the Slack URL, then restart `spatalk serve`. With ngrok's static domain you skip this.

## What to show

Have the caller try, in this order, and keep three windows visible: the Slack channel, Mailpit at http://localhost:8025, and a terminal running `uv run spatalk items list skincentrix` between calls.

1. "How much is the express treatment?" and "Are you open Sunday?" → answered from the knowledge base, no item (band 1).
2. "I need to cancel my appointment on Thursday, it's Dana." → the assistant says it has sent a request and when someone will confirm; an item appears in Slack with buttons and in Mailpit with links (band 2). Click Acknowledge in Slack: the message updates.
3. "Can you text me the link to book a facial?" → without a verified toll-free number the assistant says the team will send the link and files it (Tier C, honest).
4. "I have a rash after my laser session yesterday." → the fixed clinical script, including the emergency sentence; an urgent item (band 3). This is the safety story: no model was consulted.
5. "Can I just talk to a real person?" → the human-request script with a stated callback time (band 3).
6. "Just tell me it's booked for Thursday at 2." → the assistant will not say booked; if the model tries, the guard replaces the sentence and files a question. This is the honesty story.
7. "That's all, thanks, bye." → goodbye and hang-up.

Volunteered health context: "I'm pregnant, can I still book a facial?" → the request proceeds, the item carries a health-context flag, no advice is given.

## Optional extras for the demo

- Web chat: embed the widget in a local HTML page per `docs/runbooks/widget-install.md`, with the API pointed at the tunnel host. Booking links show inline.
- SMS: only after toll-free verification, or by enabling messaging on the local number in Telnyx for texts to your own phone (carriers may filter; do not rely on it in front of a client).
- Portal: needs WSL and `portal/.env.server`; not required for the phone demo.

## On the road

- Any internet works, including a phone hotspot: the tunnel is outbound only, nothing needs inbound ports.
- Keep Docker Desktop, the tunnel and `spatalk serve` running; turn off sleep on the laptop.
- Cost per demo call is a few cents. The tunnel adds roughly 50 to 100 ms per turn compared with the real deployment, where audio bypasses any proxy.
- Latency and turn count for each call print at call end in the `spatalk serve` log (`call <id> turns=… p50=…ms p95=…ms`).

## Demoing to a different business

Copy `tenants/skincentrix/` to `tenants/<slug>/`, edit the five files (name, hours, services, knowledge, scripts), then `uv run spatalk tenant import tenants/<slug>` and `uv run spatalk numbers add <number> <slug> voice`. One number maps to one tenant, so either buy a second local number ($1) or re-point the same number between demos.
