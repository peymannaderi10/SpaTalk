# Deploy runbook (OVH VPS-2 2027, Beauharnois)

Everything here is run by a person, on the founder's machine and on the VPS. No agent has
executed any step below: buying a number, changing DNS, deploying and placing a call are
the founder's morning steps (`CLAUDE.md`, "Things agents must not do overnight"). The
accounts and every environment variable they produce are in `accounts-and-env.md`;
this page is what to do once those exist.

Substitute your domain for `<domain>` throughout (the accounts runbook assumes `spatalk.ca`).

## Once

1. Order OVH VPS-2 2027 (4 vCPU, 8 GB) in Beauharnois, Ubuntu 24.04. Enable the 7-day automatic backup option.
2. DNS (Cloudflare): `api.<domain>` A record proxied (orange cloud); `media.<domain>` A record DNS-only (grey cloud); `app.<domain>` and `app-api.<domain>` A records proxied (the portal). All to the VPS IP. Media must bypass the proxy: Cloudflare does not proxy the bidirectional audio WebSocket.
3. On the VPS: `apt install -y docker.io docker-compose-v2 git`, add your user to the docker group, then close every port but SSH and the web: `sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw --force enable`. Postgres is published on loopback only, so nothing else needs a rule. `git clone` the repo, `cd runtime`, `cp .env.example .env`, fill every key. Set `POSTGRES_PASSWORD` to something real *before* the first `up` (`openssl rand -hex 24`): Postgres reads it once, when the data volume is created. A note in `.env` goes on its own line, never after an empty value; `spatalk serve` refuses to start otherwise and names the key. `API_HOST=api.<domain>`, `MEDIA_HOST=media.<domain>`, `APP_HOST=app.<domain>` and `APP_API_HOST=app-api.<domain>` are what Caddy reads for its four site blocks; `PUBLIC_BASE_URL=https://api.<domain>` and `MEDIA_WS_HOST=media.<domain>` are what the runtime puts in TeXML and action links. `APP_API_HOST` is also what the portal's client is compiled against, so changing it means rebuilding `portal-web`.
4. `bash scripts/deploy.sh`. It pulls, builds the three images, runs `alembic upgrade head` with the new image, starts everything and waits until the runtime reports healthy. The first build pulls Torch and ONNX for the Silero VAD and the local smart-turn model and installs the Wasp toolchain twice, so allow fifteen minutes; the runtime image is about 3 GB (VPS-2's 80 GB disk is ample, a 20 GB box is not). The app container never migrates on start-up; the schema is created by the script's migrate step and nothing else.
5. `docker compose exec app spatalk tenant import tenants/skincentrix`. A clinic that has no bundle yet starts from the basics instead: `spatalk tenant new <id> --name "<clinic>" --timezone America/Toronto --owner-email <owner> --booking-url <url> [--public-phone +1…]` writes a starter bundle to `tenants/<id>` (it needs no database, so run it in the checkout on the VPS, then commit the directory); edit the five files, then import them with the same command. The admin wizard's "Start from the basics" does the same through the portal in one step.
6. Telnyx: buy one Canadian local number (Mississauga 905 if available). Create a TeXML Application with Voice URL `https://api.<domain>/telnyx/texml` (POST). Assign the number to it. Copy the API key into `.env`.
7. `docker compose exec app spatalk numbers add +1905XXXXXXX skincentrix`, then `docker compose restart app`.
8. Slack: one app for every clinic, created once from the manifest in `accounts-and-env.md` section 8 (Interactivity `https://api.<domain>/slack/interactions`, Events `/slack/events`, redirect URL `https://api.<domain>/slack/callback`, public distribution on). Put its signing secret, client id and client secret in `.env` as `SLACK_SIGNING_SECRET`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, with `META_TOKEN_ENCRYPTION_KEY` set. Each clinic then connects its own workspace from Settings → Integrations → Slack and invites the bot to the channel it picked; no per-clinic line in `.env`. Manual fallback for a clinic that cannot install apps: `SLACK_BOT_TOKEN` and `SKINCENTRIX_SLACK_WEBHOOK`, as before.
9. SES: verify the sending domain in ca-central-1, create SMTP credentials, fill `SMTP_*` and `MAIL_FROM`.

## The portal

The portal is two more containers in the same Compose project, on two more Caddy
sites: `app.<domain>` is the built client (static files), `app-api.<domain>` is the
Wasp server that holds the session cookie, the Stripe webhook and the Google OAuth
callback. Both images build the portal from the committed source — `wasp build`
runs inside them — so the VPS needs Docker and nothing else.

1. `cp portal/.env.server.example portal/.env.server` on the VPS and fill it. Three
   values must match this deploy: `WASP_WEB_CLIENT_URL=https://app.<domain>`,
   `WASP_SERVER_URL=https://app-api.<domain>`, and `RUNTIME_INTERNAL_KEY` equal to
   the runtime's `INTERNAL_API_KEY`. `RUNTIME_INTERNAL_URL=http://app:8000` reaches
   the runtime inside the Compose network. Leave `PORTAL_EMAIL_PROVIDER` unset:
   the image always sends over SMTP, and Wasp refuses the Dummy provider in a
   production build — which also means `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
   `SMTP_PASSWORD` and `MAIL_FROM` must all be filled in, even though a
   development `.env.server` running the Dummy provider can leave them out. The
   server exits on start naming any it is missing. Do not set `DATABASE_URL` for
   the container — Compose
   overrides it with `postgresql://spatalk:spatalk@db:5432/spatalk`, the same
   database the runtime uses, where the portal owns the `public` schema.
2. `docker compose up -d --build portal-server portal-web caddy`. The first build
   installs the Wasp toolchain and builds the client twice (once per image), so
   allow about ten minutes; afterwards Docker's layer cache makes it minutes.
3. The server migrates its own schema on start: its command is
   `npx prisma migrate deploy` followed by `npm run start`. This is the one place
   the portal differs from the runtime, whose schema is created by an explicit
   `alembic upgrade head`. `wasp db migrate-dev` is a development command and must
   never be run against this database: its answer to drift is an offer to reset
   every schema it can see, and the runtime's schema is one of them.
4. Stripe's webhook endpoint is `https://app-api.<domain>/payments-webhook` and
   Google's authorised redirect URI is
   `https://app-api.<domain>/auth/google/callback`; both are in
   `accounts-and-env.md` and both point at the API host, never the client host.
5. Open `https://app.<domain>`, sign up with the address in `ADMIN_EMAILS`, verify
   from the email, and create the first organisation from `/admin/tenants/new`.

Checks:

```
curl -s https://app.<domain>/login | grep -o '<title>[^<]*'      # the client is served
curl -s -o /dev/null -w '%{http_code}\n' https://app-api.<domain>/auth/me   # 401 signed out
docker compose logs portal-server | grep -i "migrat\|listening"
```

## Every deploy

`bash scripts/deploy.sh`: pull, build, migrate the runtime schema with the new image, restart, wait for `/healthz`, print what it reports, prune the images the previous deploy left. A deploy that stops half-way is finished by running it again. `docker compose ps` shows every container `(healthy)`; one that is not has a failing health check and `docker compose logs --tail 100 <service>` says why. Logs rotate on their own (five files of 20 MB per container).

The portal needs no migration step of its own: `portal-server` runs
`prisma migrate deploy` every time it starts.

## Config change for a tenant

Edit the bundle, `spatalk tenant import tenants/<id>`, no restart needed (30-second cache).

## Checks

`curl -s https://api.<domain>/healthz | jq -c '{ok,tenants}'` returns `{"ok":true,"tenants":["skincentrix"]}`. The whole response also carries `config_versions` (the config version each tenant is running) and `commit` (the image's `GIT_COMMIT`).
`docker compose logs -f app` while calling the number.

## First real call

The failable check for the runtime plan. Call the Telnyx number from a mobile and confirm
each line. Record the results in `docs/runbooks/first-call-<date>.md`; a line that fails is
a defect against the task named beside it, not something to work around.

1. The disclosure script plays in full and speaking over it does not interrupt it (Task 13, `MuteUntilFirstBotCompleteUserMuteStrategy`).
2. "How much is the express treatment?" is answered with $99 in one or two sentences.
3. "Can I talk to a real person?" plays the human-request script with a stated callback time, the call ends, and within a minute an item appears in Slack (with buttons) and in the inbox email (with links). `docker compose exec app spatalk items list skincentrix` shows it as `open`, `urgent`.
4. Click Acknowledge in Slack: the message updates to "acknowledged by <you>"; `items list` agrees.
5. Call again: "I need to cancel my appointment Thursday, it's Dana." The reply is the captured template ("I've sent that to the team as a request..."), never the word "cancelled" and never "booked" or "confirmed". An item of type `cancel` appears.
6. Call again and say goodbye: the goodbye script plays and the call ends.
7. In the app logs, find the line `call <id> turns=... p50=...ms p95=...ms`. Record p95. If p95 is over 800 ms, set `LLM_MODEL=gemini-2.5-flash-lite` in `.env`, restart, and call again.
8. Bake-off: set `STT_PROVIDER=deepgram_flux` and `TTS_PROVIDER=deepgram_aura2` (with `DEEPGRAM_API_KEY`), restart, repeat step 7. Keep the pair with the lower p95 unless its cost breaks the ceiling in `docs/research/costmodel.py`.
9. Open `docs/research/rates.json`, replace the two unverified Telnyx numbers with the rates shown in the Telnyx portal, run `python docs/research/costmodel.py docs/research/rates.json`, confirm exit code 0.

## If something is wrong

- `curl` hangs or Caddy serves its default page: `API_HOST` or `MEDIA_HOST` is empty in `.env`. Caddy reads them through `env_file`; `docker compose exec caddy printenv API_HOST` tells you.
- Telnyx shows a failed webhook: the Voice URL must be the proxied `api.` host over HTTPS, method POST. `docker compose logs app | grep texml`.
- The call connects but stays silent: the stream URL is built from `MEDIA_WS_HOST`. If that record is proxied (orange cloud) the WebSocket never upgrades; set it to DNS-only.
- `alembic upgrade head` fails with "connection refused": the app container reaches Postgres as `db:5432`, not `localhost:5434`. Check `DATABASE_URL` in the `app` service, which compose sets and `.env` must not override.
- Nothing arrives in Slack: `docker compose exec app spatalk items list skincentrix` still shows the item, so the ledger is fine and the delivery job is not. `docker compose logs app | grep deliver`.
- The portal loads but every page says the server is unreachable: the client was built against the wrong host. `docker compose exec caddy printenv APP_API_HOST`, fix `APP_HOST`/`APP_API_HOST` in `runtime/.env`, then `docker compose build --no-cache portal-web && docker compose up -d portal-web`. Rebuilding is the only way to change it: the URL is compiled into the bundle.
- Login redirects back to `localhost`: `WASP_WEB_CLIENT_URL` or `WASP_SERVER_URL` in `portal/.env.server` still holds the development values. Fix and `docker compose up -d portal-server`.
- `portal-server` restarts in a loop: read `docker compose logs portal-server`. A failed `prisma migrate deploy` (connection refused, or a migration that is not committed) exits before the server starts; a missing environment variable fails Wasp's env validation with the variable's name.
