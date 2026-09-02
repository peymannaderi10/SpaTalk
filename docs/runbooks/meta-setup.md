# Meta setup: Instagram and Facebook Page

Instagram DMs and comments, and Facebook Page messages and comments, are answered by the same
brain as the phone, SMS and web chat. This runbook is the founder's half: one Meta app for the
whole service, then one Connect click per clinic. It expands step 9 of
[`accounts-and-env.md`](accounts-and-env.md), which is the short version.

**Time:** about 45 minutes of clicking, plus a deployed runtime. App Review, if you need it, is
weeks — start it long before you need it.

**Never done by an agent.** Creating the app, switching it Live, inviting testers and submitting
App Review are founder steps: they cost money, identity or a Meta policy commitment.

---

## 0. What the connection actually is

| Thing | Where it lives |
|---|---|
| One Meta app | Your developer account. All tenants share it. |
| App id and secrets | The runtime's `.env`, never a tenant bundle, never the portal. |
| One access token per tenant per provider | `runtime.tenant_integrations`, Fernet-encrypted with `META_TOKEN_ENCRYPTION_KEY`. |
| Which account a webhook belongs to | `tenant_integrations.external_id` = the Instagram user id or the Page id. |
| Comment policy (off / keyword / all, keywords, public reply) | `TenantConfig.social`, edited in the portal. |
| Fixed public reply and the DM disclosure | `scripts.comment_public_reply`, `scripts.dm_greeting` in the tenant bundle. |

The portal never calls Meta and stores no token. It asks the runtime for an authorisation URL and
shows what the runtime reports.

---

## 1. The app (30 minutes)

1. **business.facebook.com** → create a Business Portfolio if you do not have one.
2. **developers.facebook.com** → My Apps → Create App → use case **Other** → type **Business** →
   name `SpaTalk Front Desk` → link the portfolio.
3. Add product **Instagram** → **API setup with Instagram login**. Do *not* pick "Authenticate with
   Facebook Login" — that is the older path and the Business Login endpoints below will not match it.
   Copy:
   - **Instagram App ID** → `INSTAGRAM_APP_ID`
   - **Instagram App Secret** → `INSTAGRAM_APP_SECRET`
4. App Settings → Basic → copy **App ID** and **App Secret** → `FACEBOOK_APP_ID`,
   `FACEBOOK_APP_SECRET`. Webhook signatures are checked against **both** secrets, so both are
   needed even if you never connect a Facebook Page.
5. Business Login settings → **OAuth redirect URI**: `https://api.spatalk.ca/instagram/callback`.
   - **Deauthorize callback URL**: `https://api.spatalk.ca/instagram/deauthorize`
   - **Data deletion request URL**: `https://api.spatalk.ca/instagram/delete`

   Both are Meta platform requirements and both are already implemented: deauthorize deletes the
   tenant's integration row, and delete answers with the `{url, confirmation_code}` Meta expects.
6. App Settings → Basic → **Privacy Policy URL** `https://app.spatalk.ca/privacy` (the portal ships
   that page), pick a category, save.
7. Switch the app to **Live** mode. Webhooks are not delivered to a Development-mode app: the
   dashboard's Test button is the only thing that fires there. Live mode alone does not widen who
   you may serve — that is Access level, section 4.

## 2. Webhooks (10 minutes, after the runtime is deployed)

The verification handshake is a live HTTPS call from Meta to your server, so the runtime must
already be up at `https://api.spatalk.ca`.

1. Generate a verify token: any long random string. Put it in the runtime `.env` as
   `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` and restart the runtime **before** you press Verify.
2. Products → Instagram → Webhooks → **Callback URL** `https://api.spatalk.ca/instagram/webhook`,
   **Verify token** the same string → Verify and Save.
3. Subscribe to fields **`comments`** and **`messages`**. Subscribe to both: with only one
   subscribed, nothing arrives at all.
4. For Facebook Pages, add product **Messenger** → Webhooks → Callback URL
   `https://api.spatalk.ca/messenger/webhook`, the same verify token, fields **`messages`** and
   **`feed`**. Facebook Login settings → Valid OAuth redirect URI
   `https://api.spatalk.ca/messenger/callback`.
5. Per-account subscription is not manual: the runtime calls `POST /{id}/subscribed_apps` when a
   tenant connects, and `DELETE /{id}/subscribed_apps` when someone disconnects.

Check: `GET https://api.spatalk.ca/instagram/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=42`
returns `42` as plain text. A wrong token returns 403, which is what Meta will show you.

## 3. Runtime environment

| variable | value |
|---|---|
| `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` | step 1.3 |
| `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` | step 1.4 |
| `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` | step 2.1, the same value in both Meta webhook screens |
| `META_TOKEN_ENCRYPTION_KEY` | a Fernet key, generated once (below) |
| `META_GRAPH_VERSION` | leave at `v21.0` unless you have a reason |
| `PUBLIC_BASE_URL` | `https://api.spatalk.ca`; the redirect URIs are built from it |

```bash
cd runtime && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep that key. It is the only thing that can read the stored tokens: rotate it and every tenant has
to press Connect again (the runtime says so honestly rather than pretending to be connected).

Without `INSTAGRAM_APP_ID`/`INSTAGRAM_APP_SECRET` (or the Facebook pair) the portal's card reads
*not set up on this service yet* and the Connect button is disabled. That is the honest symptom of
a half-filled `.env`, not a bug.

## 4. Standard Access, Advanced Access and who you may serve

- **Standard Access** is what a new app has for `instagram_business_basic`,
  `instagram_business_manage_comments`, `instagram_business_manage_messages`. It works, in Live
  mode, for accounts that have a **role on the app** — your own and any Instagram Tester who has
  accepted an invite. This is enough to run Skincentrix end to end, and enough for every clinic you
  are willing to add as a tester.
- **Advanced Access** is what you need to serve a stranger's account without adding them to the app.
  It requires **App Review** and, as a third-party Tech Provider, Business Verification.
- Practical read: **Live mode + Standard Access + Instagram testers = full end-to-end operation with
  no review.** Do not start App Review for the first clinic; start it when the tester invite becomes
  an embarrassing thing to ask a new customer for.
- Duration: Meta's own docs give no number. Secondhand reports in `docs/research/research-2-adoption-check.md`
  say the review dashboard quotes about 20 days, messaging permissions sometimes 3–5 business days.
  Treat that as unverified and budget a month.

## 5. Inviting a clinic as a tester (Standard Access path)

1. App dashboard → **App Roles → Roles → Add People → Instagram Tester** → the clinic's Instagram
   username.
2. The clinic accepts in Instagram → Settings and privacy → **Website permissions → Apps and
   websites → Tester invites** → Accept.
3. For a Facebook Page, the person who connects must be an **admin of the Page** and have a role on
   the app until you hold Advanced Access.

Until the invite is accepted, the Connect flow fails at Meta's screen with a permissions error, not
in our code.

## 6. How a tenant connects (what you tell the clinic)

1. The owner signs in to the portal → **Settings → Integrations**.
2. **Instagram** card → **Connect** → Meta's Business Login screen → they log in with the clinic's
   Instagram account and approve. The browser lands back on Settings → Integrations.
3. The card then shows the account it is connected as (`@username`), when the token expires, and who
   connected it.
4. **Facebook Page** card → **Connect** → Facebook Login → if the person administers exactly one
   Page it is stored and subscribed immediately; with several, the portal asks which Page and stores
   the one they pick.
5. **Disconnect** (owner only) unsubscribes the app and deletes the stored token. If Meta refuses
   the unsubscribe, the row is still deleted and the response says the unsubscribe did not happen —
   the runtime stops answering that account either way.

Reply behaviour is tenant configuration, not a Meta setting, and lives in the portal's schema-driven
settings forms:

| field | meaning |
|---|---|
| `social.comment_mode` | `off`, `keyword` (default) or `all` |
| `social.comment_keywords` | which comments earn a reply in `keyword` mode, word-bounded, case-insensitive |
| `social.public_reply_enabled` | also post `scripts.comment_public_reply` under the comment |
| `scripts.comment_public_reply` | the fixed public sentence; never generated |
| `scripts.dm_greeting` | the AI disclosure that prefixes the first DM reply |

## 7. Tokens after the connection

- Instagram long-lived tokens last 60 days. A daily `social.refresh_tokens` job renews any token
  inside 30 days of expiry.
- A failed renewal sets `needs_reconnect` on the row and emails ops once. The portal card then says
  the connection needs reconnecting, and the cure is the owner pressing **Connect** again.
- A Page token cannot be renewed with the Instagram grant, so a Page connection carrying an expiry
  is a reconnect, not a retry.
- Tokens are never logged and never leave the runtime.

## 8. App Review submission checklist

Only when you need Advanced Access. Have all of this ready before you open the form:

- [ ] **Business Verification** completed for the portfolio (legal name, address, a document Meta
      accepts). Start it first; it gates everything else.
- [ ] **Screencast** of the real flow, recorded against the live app: a customer sends the clinic a
      DM, the assistant replies, and a comment carrying a keyword receives a private reply. Show the
      login screen and the permission dialog at the start — Meta rejects recordings that begin after
      consent — and show the assistant identifying itself as an AI.
- [ ] **Use-case text** per permission, in plain words: `instagram_business_manage_messages` — "we
      reply to the clinic's Instagram DMs on their behalf and file anything needing a human as a
      tracked request"; `instagram_business_manage_comments` — "we send a private reply to comments
      matching the clinic's keywords"; `instagram_business_basic` — "we read the connected account's
      id and username to route incoming events to the right clinic".
- [ ] **Privacy Policy URL**: `https://app.spatalk.ca/privacy`, reachable without login.
- [ ] **Data deletion URL**: `https://api.spatalk.ca/instagram/delete`, answering Meta's
      `signed_request` and returning a confirmation code.
- [ ] **Deauthorize callback**: `https://api.spatalk.ca/instagram/deauthorize`.
- [ ] Test credentials: a test Instagram account Meta's reviewer can message, and the portal login
      they should use.
- [ ] The app is **Live**, and the reviewer's flow does not depend on a tester invite.
- [ ] Meta is in the subprocessor register (spec §7) and named in the clinic's disclosure.

## 9. Troubleshooting

| Symptom | Cause |
|---|---|
| Meta's Verify button fails | the runtime is not deployed, or `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` differs from the box; the endpoint answers 403 on a mismatch |
| Verified, but no events arrive | the app is not **Live**, or only one of `comments`/`messages` is subscribed |
| The portal card says *not set up on this service yet* | the runtime has no app id or secret for that provider |
| Connect fails at Meta's screen | the account has no role on the app and you hold only Standard Access |
| Webhook returns 401 in the logs | the signature failed against both app secrets: `FACEBOOK_APP_SECRET` is usually the missing one |
| A reply never goes out and an item appears instead | Meta's 24-hour messaging window closed; the conversation is closed and a callback item carries the username so a human answers from the Instagram inbox |
| The card says the connection needs reconnecting | a token refresh failed; press Connect again |

## 10. What runs in CI

The social tests (`runtime/tests/test_social_*.py`) run inside the runtime job on every push, with
no Meta secret: every Graph call goes through `FakeGraphClient` and every webhook is a recorded
fixture signed with a test secret. Nothing in CI reaches Meta.
