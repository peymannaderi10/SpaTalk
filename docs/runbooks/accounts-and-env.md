# Accounts and environment setup

Everything the platform needs from the outside world, in the order to do it, with the exact environment variable each step produces. Written for one person with a credit card and about three hours, split across two sittings.

The overnight build does not need any of this: its tests run against fakes and a local Postgres. You need it the morning after, to deploy and place the first real call. Two things have multi-day clocks and should be started tonight if you can: Telnyx account verification and AWS SES production access.

## 0. Before you start (10 minutes)

- Pick the domain you will use. This guide assumes `spatalk.ca`; substitute yours. You will create three hostnames: `api.` (webhooks, action links, widget), `media.` (voice audio, must bypass Cloudflare's proxy), `app.` (the portal).
- Open a password manager entry per provider. Every secret below goes there first, then into the env file.
- Generate three random secrets now. PowerShell: `-join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })`. Git Bash: `openssl rand -hex 32`. Label them `SECRET_KEY`, `INTERNAL_API_KEY`, `JWT_SECRET`.
- Keep this table handy; it is the map from provider to variable.

| Needed for | Providers |
|---|---|
| Morning smoke test on a real call | OVH, Cloudflare, Telnyx (local number), Soniox, Inworld, Google AI, Slack |
| Same week | Telnyx toll-free + verification, AWS SES, Stripe, Meta, Google OAuth, Cloudflare Turnstile and R2 |
| Optional | Deepgram (bake-off), UptimeRobot, Sentry |

## 1. Cloudflare and the domain (20 minutes)

Why: DNS, free proxy and WAF for HTTP, Turnstile for the widget, R2 for database backups, Workers for the SMS fallback.

1. Sign in at dash.cloudflare.com. Add the domain as a site (Free plan). Change the nameservers at your registrar to the two Cloudflare gives you. Wait for "Active".
2. DNS records (you will fill the IP after step 2, come back):
   - `A api` → VPS IP, proxy **on** (orange cloud)
   - `A media` → VPS IP, proxy **off** (grey cloud). Voice audio must not pass through the proxy.
   - `A app` → VPS IP, proxy **on** (portal pages)
   - `A app-api` → VPS IP, proxy **on** (portal server: login, Stripe webhook, Google OAuth)
3. SSL/TLS → Overview → set to **Full**. Caddy on the VPS obtains its own certificates.
4. Turnstile → Add site → widget mode Managed, hostnames `api.spatalk.ca` and the clinic's website domain. Copy:
   - `TURNSTILE_SITE_KEY`
   - `TURNSTILE_SECRET_KEY`
5. R2 → Create bucket `spatalk-backups`, location hint North America. Then Manage R2 API Tokens → Create token → Object Read & Write, this bucket only. Copy:
   - `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
   - `R2_ENDPOINT` = `https://<account-id>.r2.cloudflarestorage.com` (account id is on the R2 overview page)
   - `R2_BUCKET=spatalk-backups`
6. Workers (for the SMS fallback in the text-channels plan): My Profile → API Tokens → Create Token → template "Edit Cloudflare Workers". Copy `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.

Gotcha: if you registered the domain with Cloudflare Registrar, the nameserver step is already done.

## 2. OVH VPS (15 minutes, plus provisioning time)

Why: the whole runtime and portal live on one box in Beauharnois, Quebec.

1. ovhcloud.com/en-ca → VPS → choose **VPS-2 2027** (4 vCPU, 8 GB, about CA$13.70/month) or the current equivalent, datacentre **Beauharnois (BHS)**, OS **Ubuntu 24.04**.
2. Add the **Automated Backup** option (about CA$1.80/month).
3. Add your SSH public key during the order (Windows: `ssh-keygen -t ed25519`, then paste `~/.ssh/id_ed25519.pub`).
4. When the email arrives, note the IPv4. Go back to Cloudflare and fill the three A records.
5. First login: `ssh ubuntu@<ip>` (or `root@`, the email says which). Run:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker
```

Variables produced: none directly. Put `API_HOST=api.spatalk.ca`, `MEDIA_HOST=media.spatalk.ca`, `PUBLIC_BASE_URL=https://api.spatalk.ca`, `MEDIA_WS_HOST=media.spatalk.ca` in the runtime env.

## 3. Telnyx (30 minutes, verification can take up to a day)

Why: phone numbers, inbound calls with audio streamed to us, SMS.

1. Sign up at portal.telnyx.com. Complete account verification when prompted (they check business details; this can take hours, so start it tonight). Add a card and fund $20.
2. Auth → API Keys → Create. Copy `TELNYX_API_KEY`.
3. Auth → Public Key → copy the Ed25519 public key. This verifies messaging webhooks later: `TELNYX_PUBLIC_KEY`.
4. Numbers → Buy Numbers → Country Canada, type Local, search area code 905 (Mississauga). Buy one. This is the **voice** number the clinic will forward to.
5. Voice → TeXML Applications → Create. Name `spatalk-runtime`. Voice URL: `https://api.spatalk.ca/telnyx/texml`, method POST. Failover URL: leave blank tonight (the operations plan adds a hosted voicemail bin). Save, then assign the local number to this application (Numbers → your number → Voice settings → TeXML application).
6. Numbers → Buy Numbers → type Toll-Free, Canada. Buy one. This is the **SMS** number.
7. Messaging → Messaging Profiles → Create `spatalk-sms`. Webhook URL: `https://api.spatalk.ca/telnyx/sms` for now (the text-channels plan moves it to a Cloudflare Worker). Assign the toll-free number to this profile.
8. Messaging → Toll-Free Verification → submit for the toll-free number. Fields: business name and address (use yours, the service provider), business registration number, website, use case "customer care and appointment follow-ups", sample messages (use the booking-link text and the missed-call text from the tenant bundle), opt-in description: "Customers text or call the business first; Canada double opt-in: the first reply asks them to confirm YES". Expect about five business days.
9. Write down both numbers in E.164 (`+1905…`, `+1888…`). After deploy you run `spatalk numbers add <local> skincentrix voice` and `spatalk numbers add <tollfree> skincentrix sms`, and set `sms_from_number` in the Skincentrix bundle.

Gotcha: until toll-free verification passes, SMS from the toll-free number is silently dropped. For testing, the local number can send SMS to your own phone if you add it to the messaging profile too.

## 4. Soniox, speech-to-text (5 minutes)

1. console.soniox.com → sign up, add a card (no free credits, pay as you go at about $0.002 per minute).
2. API Keys → Create. Copy `SONIOX_API_KEY`.
3. Set `STT_PROVIDER=soniox`.

## 5. Inworld, text-to-speech (10 minutes)

1. platform.inworld.ai → sign up → create a workspace named `spatalk`.
2. Settings → API Keys → create a **runtime** key. The portal shows a Base64 "Basic" credential; copy that whole string as `INWORLD_API_KEY`. (If the runtime rejects it, the key is the Base64 of `key:secret`; the portal shows both parts.)
3. Voices → pick a voice, note its id (for example `Ashley`). `INWORLD_VOICE=Ashley`, `INWORLD_MODEL=inworld-tts-2`. Switch to the Flash model id from the Models page once the bake-off says latency matters more than voice quality.
4. Settings → Data → enable the zero-data-retention option for the workspace.
5. Set `TTS_PROVIDER=inworld`.

## 6. Google AI Studio, the language model (5 minutes)

1. aistudio.google.com → Get API key → create in a new Google Cloud project named `spatalk`.
2. In that Cloud project, **enable billing**. The paid tier is what carries the no-training terms; the free tier does not.
3. Copy `GOOGLE_API_KEY`. Set `LLM_MODEL=gemini-2.5-flash`.
4. Add the same key as a GitHub Actions secret named `GOOGLE_API_KEY` so the regression suite runs in CI.

## 7. Amazon SES, email delivery (20 minutes, production access up to 24 hours)

Why: the only email provider with no monthly floor. Delivers tracked items and the morning digest.

1. Create an AWS account (or use one you have). Switch region to **Canada (Central) ca-central-1**.
2. SES → Identities → Create identity → Domain `spatalk.ca` → Easy DKIM. It shows three CNAME records: add them in Cloudflare with proxy **off**. Wait for "Verified".
3. While in the sandbox SES only delivers to verified addresses. Add two more identities of type Email address: your own inbox and `info@skincentrix.com`, and click the verification links (ask the clinic to click theirs).
4. SES → Account dashboard → Request production access. Use case: transactional notifications to business customers, low volume. Approval takes up to 24 hours; the sandbox is enough for the first day.
5. SES → SMTP settings → Create SMTP credentials. Copy `SMTP_USER` and `SMTP_PASS`. Set `SMTP_HOST=email-smtp.ca-central-1.amazonaws.com`, `SMTP_PORT=587`, `MAIL_FROM=frontdesk@spatalk.ca`.

## 8. Slack, staff delivery with buttons (15 minutes)

Why: tracked items arrive as messages with Acknowledge and Resolve buttons. One app serves every tenant; each tenant gets its own channel and webhook.

1. api.slack.com/apps → Create New App → From an app manifest → pick the workspace (yours for testing; later the clinic's, or invite them to a shared channel). Paste the manifest below. Create.
2. Basic Information → App Credentials → copy **Signing Secret** as `SLACK_SIGNING_SECRET`.
3. Install App → Install to Workspace → allow. Copy the **Bot User OAuth Token** as `SLACK_BOT_TOKEN` (used by the text-channels plan for staff replies).
4. Incoming Webhooks → Add New Webhook to Workspace → choose the channel `#skincentrix-frontdesk` (create it first). Copy the webhook URL as `SKINCENTRIX_SLACK_WEBHOOK`. The tenant bundle references this variable by name.
5. Interactivity is preset in the manifest to `https://api.spatalk.ca/slack/interactions`. It will show an error until the runtime is deployed; that is fine.

Manifest:

```json
{
  "display_information": { "name": "Front Desk", "description": "AI front desk: tracked items with acknowledge and resolve" },
  "features": { "bot_user": { "display_name": "Front Desk", "always_online": true } },
  "oauth_config": {
    "scopes": { "bot": ["incoming-webhook", "chat:write", "channels:history", "channels:read", "users:read"] }
  },
  "settings": {
    "interactivity": { "is_enabled": true, "request_url": "https://api.spatalk.ca/slack/interactions" },
    "event_subscriptions": { "request_url": "https://api.spatalk.ca/slack/events", "bot_events": ["message.channels"] },
    "org_deploy_enabled": false, "socket_mode_enabled": false, "token_rotation_enabled": false
  }
}
```

## 9. Meta, Instagram and Messenger (30 minutes, review takes weeks)

Why: Instagram comment replies and DMs. Standard Access covers Skincentrix's own account without App Review; Advanced Access (for other clients) needs review.

1. business.facebook.com → create a Business Portfolio if you do not have one.
2. developers.facebook.com → My Apps → Create App → use case "Other" → type **Business** → name `SpaTalk Front Desk` → link the portfolio.
3. Add product **Instagram** → choose "API setup with Instagram login". Note **Instagram App ID** and **Instagram App Secret**: `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`. Also App Settings → Basic → **App Secret**: `FACEBOOK_APP_SECRET` (webhook signatures are checked against both).
4. Business Login settings → OAuth redirect URI: `https://api.spatalk.ca/instagram/callback`. Deauthorize and data-deletion URLs: `https://api.spatalk.ca/instagram/deauthorize` and `https://api.spatalk.ca/instagram/delete`.
5. Webhooks → Instagram → Callback URL `https://api.spatalk.ca/instagram/webhook`, Verify token: generate a random string, save as `INSTAGRAM_WEBHOOK_VERIFY_TOKEN`. Subscribe to fields **comments** and **messages** (both, or nothing fires). Verification only succeeds after the runtime is deployed; come back then.
6. App Roles → Roles → add the clinic's Instagram account owner as an **Instagram Tester**; they accept the invite in Instagram → Settings → Website permissions → Apps and websites → Tester invites.
7. App Settings → Basic → fill Privacy Policy URL (use `https://app.spatalk.ca/privacy`, the portal plan ships that page) and category. Then switch the app to **Live** mode; webhooks only deliver in Live.
8. Later, for other clients: App Review → request Advanced Access for `instagram_business_basic`, `instagram_business_manage_messages`, `instagram_business_manage_comments`; complete Business Verification. Budget about 20 days.
9. Messenger (Facebook Page inbox and comments): add product **Messenger**, subscribe the clinic's Page to `messages` and `feed` after they grant access through the portal's Connect button; permissions `pages_messaging`, `pages_manage_metadata`, `pages_read_engagement`. Same review process. Copy the **Page Access Token** flow output into the portal, not the env.

## 10. Stripe, billing (15 minutes)

1. dashboard.stripe.com → create account (Canada). Stay in **Test mode** for now.
2. Developers → API keys → copy Secret key as `STRIPE_API_KEY` (test key starts with `sk_test_`).
3. Products → Add product `Front Desk` → recurring price **CA$999 per month**. Copy the price id as `STRIPE_PRICE_ID_FRONTDESK`.
4. Developers → Webhooks → Add endpoint `https://app-api.spatalk.ca/payments-webhook`, events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`. Copy the signing secret as `STRIPE_WEBHOOK_SECRET`.
5. Settings → Billing → Customer portal → enable, allow cancel and update payment method. Copy the portal link if the dashboard shows one: `STRIPE_CUSTOMER_PORTAL_URL`.

## 11. Google OAuth for portal login (10 minutes, optional, email login works without it)

1. console.cloud.google.com → same `spatalk` project → APIs & Services → OAuth consent screen → External → app name `SpaTalk`, support email, authorised domain `spatalk.ca`.
2. Credentials → Create → OAuth client ID → Web application. Authorised redirect URI: `https://app-api.spatalk.ca/auth/google/callback`. Copy `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

## 12. Deepgram, optional bake-off (5 minutes)

1. console.deepgram.com → sign up ($200 free credit) → API Keys → create. Copy `DEEPGRAM_API_KEY`.
2. Only used when `STT_PROVIDER=deepgram_flux` or `TTS_PROVIDER=deepgram_aura2`. The runtime sends the opt-out parameter so your audio is not used for model training; check the billing page afterwards for whether that changed the rate.

## 13. GitHub (10 minutes)

1. Create a private repo `spatalk`. Push the code the build produced.
2. Settings → Secrets and variables → Actions → add `GOOGLE_API_KEY`.
3. On the VPS: `ssh-keygen -t ed25519 -f ~/.ssh/deploy` and add the public key as a Deploy key (read-only) on the repo, so `git pull` works there.

## 14. Optional: uptime and errors

- uptimerobot.com free: HTTP monitor on `https://api.spatalk.ca/healthz` every 5 minutes, alert to your phone.
- sentry.io developer plan: create a Python project, copy `SENTRY_DSN`. The operations plan wires it.

## One database, two schemas

The portal and the runtime share one Postgres database. The runtime owns the
`runtime` schema and migrates it with Alembic; the portal owns `public` and
migrates it with Prisma; Wasp's job queue owns `pgboss`. Both migration tools
were run against the same database in both orders on 2026-09-02 and neither
touched the other's schema, so one database is the standard and `DATABASE_URL`
is the same database for both planes (different URL schemes: the runtime uses
`postgresql+asyncpg://`, the portal `postgresql://`).

Two rules follow, and they matter:

- **Never run `prisma migrate reset` or `wasp db reset` against this database.**
  Reset drops every schema Prisma can see, including `runtime`. To start the
  portal's tables over, point `DATABASE_URL` at a scratch database first.
- Take the nightly backup of the whole database, not of one schema.

If a future Prisma or Alembic release breaks the arrangement, the fallback is a
second database on the same server: create it with

```
docker compose exec -T db psql -U spatalk -c "CREATE DATABASE spatalk_portal OWNER spatalk"
```

and point only the portal's `DATABASE_URL` at `spatalk_portal`. Nothing else
changes: the portal reaches runtime data over `/internal`, never over SQL.

## Where every variable goes

Runtime: `runtime/.env` on the VPS (copy from `runtime/.env.example`). Portal: `portal/.env.server` and `portal/.env.client`. Worker: `edge/sms-worker/.dev.vars` and `wrangler secret put`. CI: GitHub Actions secrets.

| Variable | File | From step | Needed for morning call |
|---|---|---|---|
| `DATABASE_URL` | runtime, portal | Compose default `postgresql+asyncpg://spatalk:spatalk@db:5432/spatalk`; the portal uses the same database with the `postgresql://` scheme (see "One database, two schemas" below) | yes |
| `SECRET_KEY`, `INTERNAL_API_KEY` | runtime | step 0 | yes |
| `PUBLIC_BASE_URL`, `MEDIA_WS_HOST`, `API_HOST`, `MEDIA_HOST` | runtime | step 2 | yes |
| `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY` | runtime, worker | step 3 | yes |
| `SONIOX_API_KEY`, `STT_PROVIDER` | runtime | step 4 | yes |
| `INWORLD_API_KEY`, `INWORLD_VOICE`, `INWORLD_MODEL`, `TTS_PROVIDER` | runtime | step 5 | yes |
| `GOOGLE_API_KEY`, `LLM_MODEL` | runtime, CI | step 6 | yes |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` | runtime | step 7 | email only |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM` | portal | step 7 | email only |
| `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`, `SKINCENTRIX_SLACK_WEBHOOK` | runtime | step 8 | yes |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | runtime | step 1 | widget only |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET` | runtime (WAL-G) | step 1 | backups only |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | worker deploy | step 1 | SMS fallback only |
| `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `FACEBOOK_APP_SECRET`, `INSTAGRAM_WEBHOOK_VERIFY_TOKEN`, `META_TOKEN_ENCRYPTION_KEY` (step 0 style secret) | runtime | step 9 | Instagram only |
| `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_FRONTDESK`, `STRIPE_CUSTOMER_PORTAL_URL` | portal | step 10 | portal only |
| `JWT_SECRET`, `WASP_WEB_CLIENT_URL=https://app.spatalk.ca`, `WASP_SERVER_URL=https://app-api.spatalk.ca`, `ADMIN_EMAILS=<your email>`, `RUNTIME_INTERNAL_URL=http://app:8000`, `RUNTIME_INTERNAL_KEY=<INTERNAL_API_KEY>` | portal | step 0 | portal only |
| `APP_HOST=app.spatalk.ca`, `APP_API_HOST=app-api.spatalk.ca` | runtime (Caddy) | step 1 | portal only |
| `EDGE_SHARED_KEY` (step-0 style secret), `RUNTIME_URL=https://api.spatalk.ca` | runtime, worker | step 0 | SMS fallback |
| `OPS_EMAIL=<your email>`, `OPS_SMS_NUMBER=<your mobile E.164>`, `LOG_FORMAT=json` | runtime | step 0 | alerts |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | portal | step 11 | optional |
| `DEEPGRAM_API_KEY` | runtime | step 12 | optional |
| `OPENAI_API_KEY` | runtime, CI | platform.openai.com, only for the model-swap drill | optional |
| `SENTRY_DSN` | runtime | step 14 | optional |

The complete variable list with the plan that introduces each one is in `docs/reference/api-surface.md`.

## After the env file is filled

1. On the VPS: `cd spatalk/runtime && docker compose up -d --build && docker compose exec app alembic upgrade head`.
2. `docker compose exec app spatalk tenant import tenants/skincentrix`.
3. `docker compose exec app spatalk numbers add +1905XXXXXXX skincentrix voice` and the toll-free as `sms`.
4. `curl -s https://api.spatalk.ca/healthz | jq -c '{ok,tenants}'` should return `{"ok":true,"tenants":["skincentrix"]}`; the full response also lists `config_versions` and the deployed `commit`.
5. Go back to Telnyx and confirm the TeXML application's Voice URL is reachable (Telnyx shows a green check after the first webhook). Call the local number from your phone and run the first-call checklist in `docs/runbooks/deploy.md`.
6. Edge worker (SMS fallback): on your laptop, `cd edge/sms-worker && npm ci && npx wrangler login && npx wrangler secret put EDGE_SHARED_KEY` (repeat for `TELNYX_PUBLIC_KEY`, `TELNYX_API_KEY`), set `RUNTIME_URL` in `wrangler.toml`, `npx wrangler deploy`. Then point the Telnyx messaging profile's webhook at the Worker URL instead of the runtime, and run `docker compose exec app spatalk edge sync-texts`.
7. Portal: fill `portal/.env.server` on the VPS, `docker compose up -d --build portal-server portal-web`, open `https://app.spatalk.ca`, sign up with the email in `ADMIN_EMAILS`, verify, and create the Skincentrix organisation from `/admin/tenants/new`.
8. Go back to Meta and click Verify on the webhook; go back to Slack and confirm Interactivity shows no error; go back to Stripe and send a test webhook.

## What to tell the clinic to do (they need 15 minutes)

- Forward their TELUS Business Connect main line to our local number on no-answer after four rings, and on busy. In TELUS Business Connect, under Incoming Call Information, choose **Incoming Caller ID**, not Dialed Number, so we see who is calling.
- Tell us one extension or number that does **not** forward, for live transfer later.
- Confirm the opening hours in `tenants/skincentrix/tenant.yaml` and the cancellation terms in `knowledge.md`.
- Accept the Instagram tester invite and the Slack channel invite.
- Sign off on the 30-day transcript retention and the recordings-off default, in writing.
