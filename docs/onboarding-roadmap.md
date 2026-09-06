# From the demo to the first onboarded clinic

Written 2026-09-06 after the slot-engine work. This is the ordered list of what stands between today's laptop demo and a clinic using SpaTalk on its own phone line, with what exists, what is missing, who does each step (the founder's steps are the ones an agent must never do: buying, verifying, DNS, deploying), and a rough size. `docs/roadmap.md` is the competitive map and the parked list; this page is the path.

## What already exists (so nothing here is rebuilt)

- Runtime: voice, SMS, web chat, Instagram and Messenger channels on one knowledge base per tenant; the slot engine (`docs/superpowers/specs/2026-09-05-slot-engine-design.md`); the ledger with delivery to email, Slack, SMS and WhatsApp (staff); missed-call text-back; SMS flood guard; failover between two model vendors; call notes; nightly audit, latency and cost reports; retention; backups runbook.
- Portal: sign-up with email verification, organisations and members with roles, invitations, Stripe subscription gating, the overview and request views, the Setup page (hours, services, team, knowledge and FAQ, scripts, delivery, numbers, integrations, versions), the pricing quote page, the admin tenant list.
- Edge: the Cloudflare SMS worker with offline auto-reply and replay (code and tests; not deployed).
- Runbooks for every account and every deploy step (`docs/runbooks/`).

## 1. Hosting — the platform on its own domain

Everything downstream (verification emails, invitation links, Meta webhooks, Telnyx webhooks, the widget) needs a stable public address; the Cloudflare quick tunnels change hostname on every restart and have no uptime promise.

| Step | Exists | Who | Size |
|---|---|---|---|
| Domain on Cloudflare, DNS for `api`, `media`, `app`, `app-api` (`accounts-and-env.md` §1) | Runbook | Founder | 20 min |
| OVH VPS-2 in Beauharnois, Docker, clone, `.env` (`deploy.md` "Once") | Runbook, compose file, Caddy config | Founder | 1 h + provisioning |
| `docker compose up --build`, `alembic upgrade head`, portal built against `app-api.<domain>` | Compose, Dockerfiles | Founder runs, agent prepares | 1 h |
| Telnyx voice and messaging webhooks pointed at `api.<domain>`; production numbers | Runbook | Founder | 30 min |
| Edge SMS worker deployed (`edge/sms-worker`, `wrangler deploy`), `EDGE_SHARED_KEY` set on both sides | Code and tests | Founder deploys | 30 min |
| Turnstile site and secret keys for the widget | Settings exist | Founder | 10 min |
| Production hardening pass: restart policies, health checks, log rotation, secrets out of the repo, the runtime launched with `.env` exported (the laptop bug of 2026-09-05) | Partly | Agent | 1 day |
| Uptime monitor and error alerts to the founder's phone (`monitoring.md`) | Runbook | Founder | 30 min |
| Key rotation: the Google, Soniox, Telnyx and OpenAI keys that passed through chat this week | — | Founder | 30 min |

## 2. Email — one sender for both apps

Two things send mail: the runtime (request alerts, the morning digest, action links) and the portal (verification, invitations, password resets). Both speak SMTP today; locally they print to Mailpit.

Recommendation: **Resend, over SMTP, on a mail subdomain** (`mail.spatalk.ca` with SPF, DKIM and DMARC). Its free tier (3,000 messages a month, 100 a day) covers a pilot; both apps only need `SMTP_HOST=smtp.resend.com`, a username and an API key as the password; no code change. Google Workspace is for human mailboxes (`hello@`, support), not for application mail: its SMTP relay has per-user sending limits and needs app passwords or OAuth for each sender. Microsoft Graph would mean an OAuth client and a new sender implementation in both apps for no gain. Amazon SES (the runbook's default) works too but needs a production-access request and IAM credentials; keep it as the fallback if Resend's daily cap ever binds.

| Step | Who | Size |
|---|---|---|
| Resend account, domain verified, API key | Founder | 20 min + DNS |
| `SMTP_*` and `MAIL_FROM` in the runtime `.env`; portal built with `PORTAL_EMAIL_PROVIDER` SMTP and the same credentials | Founder (values), agent (wiring check) | 1 h |
| Send a verification, an invitation, a request alert and a digest end to end; check they land out of spam | Both | 1 h |

## 3. Integrations — the Connect buttons on Settings → Integrations

| Integration | State | What is missing | Size |
|---|---|---|---|
| Instagram DMs and comments | Built; Connect and Disconnect on the tab; webhooks; comment-to-DM | Meta app in the agency's developer account (`meta-setup.md`), **App Review** (weeks; submit first, everything else runs in parallel), a real Page to test against | Founder 2 h + review time |
| Facebook Messenger | Built, same tab, same app | Same review | — |
| Slack | Built: Connect on the tab installs the Front Desk app in the clinic's own workspace (`GET /slack/connect` → Slack → `GET /slack/callback`), the bot token and the chosen channel's incoming webhook stored encrypted per tenant, delivery and the takeover thread use them, and the `.env` webhook line becomes the manual fallback (`4e8bf25` runtime, `f5840f6` portal); a connected workspace ticks the checklist's staff-destination step | Founder: `SLACK_CLIENT_ID` and `SLACK_CLIENT_SECRET` in `.env`, the redirect URL and public distribution at api.slack.com (`accounts-and-env.md` section 8), then `/invite @Front Desk` in the channel | — |
| WhatsApp (staff alerts) | Destination kind and migration exist; dormant | Meta Business Manager, a platform WhatsApp Business number, embedded signup on the tab | Founder 1 day of Meta steps + agent 2–3 days |
| WhatsApp (customers) | Not built | A fourth Meta adapter next to Instagram and Messenger, planned like the Instagram plan | Agent 1 week |
| Google Calendar | Not built, and not what a clinic's book runs on | The clinic's system of record is Jane (or Fresha, Acuity, Square, Mindbody, Zenoti). Real booking is Tier A: a write API. Jane's partner API is read-only for appointments today. Build Google Calendar only for a tenant whose book actually lives there; then it is a Tier A adapter | Agent 1 week per platform |
| Google Business Profile (review replies) | Plan only | GBP API access (profile 60+ days old), then plan R | Founder form + agent 3 days |
| Telnyx SMS to US numbers | Canadian numbers work | Toll-free verification or 10DLC registration (error 40010 today) | Founder 1 h + carrier time |

## 4. Onboarding a clinic — the sequence a new tenant goes through

Today a tenant is created by hand: a YAML bundle on disk, `spatalk tenant import`, an organisation row, an owner invited from People. That is fine for the pilot and wrong for the tenth clinic.

| Step | Exists | Missing | Size |
|---|---|---|---|
| Agency creates the clinic: name, timezone, hours, owner's email | Built: `POST /internal/tenants/from-basics` and `spatalk tenant new` render the starter bundle around the basics (`bf4cfb9`); the wizard's "Start from the basics" writes the configuration, the organisation and the owner invitation in one go, beside the bundle upload (`7f6e375`) | — | — |
| Owner signs up from the invitation, verifies email, lands on Setup | Built (needs real email) | — | — |
| Owner fills Services (or imports from the website), Team, Knowledge and FAQ, Scripts review | Built this week | A services importer from a URL would save an hour per clinic; optional | Agent 1 day, optional |
| Phone: a number assigned, the clinic forwards its line (TELUS steps in `accounts-and-env.md` "What to tell the clinic") | Built: the Numbers page shows the assigned voice number with a copy button and the runbook's forwarding instructions, once the agency has mapped one (`4d8c076`) | — | — |
| Test call and test text with the clinic on the line, then the first-run checklist ticked | Built: a "Getting set up" card on the overview, eight steps each linking to where it is done, gone once the first tracked request lands (`c89cfa4`) | — | — |
| Billing: subscription from the quote | Stripe wired, test mode | Live Stripe products and prices; the quote page's number becomes the checkout amount | Founder 1 h + agent 1 day |
| Branding: logo, theme preset, accent | Designed, not built | Three fields on the organisation, a Branding tab, the shell reading them | Agent 1–2 days |

## 5. Gates before a real clinic is on it

- The founder's eight call tests on the chosen model, then the live check that no request since go-live lacks a name and a number (`docs/reports/tasks/slot-engine.md`).
- The Playwright acceptance run (portal plan R4), on the production build.
- The promptfoo gate on the chosen model (done 2026-09-06: 47/50 on Gemini 3.1 Flash-Lite; the three misses are recorded).
- Recording stays off; the AI disclosure script and the privacy page reviewed once by a person who reads contracts; the 30-day retention default confirmed with the clinic.
- A support path the clinic can find: who they text or email when something is wrong, and the takeover thread in Slack once Slack is connected.

## 6. What tends to be forgotten

- The clinic's own after-hours behaviour: what the assistant says when closed is a script; the clinic must read it.
- Holidays in the calendar (Setup → Hours) before the first long weekend.
- The staff phone number is the one that gets alerts; the founder's phone cannot also be a test customer (2026-09-05 lesson).
- WhatsApp needs a platform sender before any tenant sees it; Instagram needs review before any tenant connects.
- Every provider key that went through a chat window gets rotated before the first paying clinic.

## Order

1. Submit the Meta App Review now (longest lead time; nothing depends on it in the meantime).
2. Hosting and email this week, together: domain, VPS, compose, Resend, Telnyx pointed at the domain, the edge worker deployed. Everything after this stops depending on the laptop.
3. Onboarding: the New-clinic form, the Numbers page instructions, live Stripe.
4. Slack connect, then WhatsApp staff alerts.
5. Branding.
6. Call tests and acceptance on the production stack, then Skincentrix becomes the first tenant on it.
