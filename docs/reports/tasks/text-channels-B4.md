# text-channels Task B4: Web chat widget and fallback form

Status: done with deviations
Commit: the commit whose message is `feat(text): web chat widget over websocket with turnstile
and fallback form` (hash recorded by the docs commit that follows, the convention set by
runtime-A8 through A16 and text-channels B1 to B3)
Tests: `uv run pytest tests/test_widget.py -q` -> 22/22 (18 of the 21 first written were seen
failing; the other three were vacuously green, see below); full runtime suite `uv run pytest -q`
-> 268 passed, 1 skipped of 269 (baseline before this task: 267 of 268 counting the one
pre-existing skip — 246 passed, 1 skipped before B4's tests existed).
`uv run ruff check spatalk tests scenarios` -> All checks passed!
Interfaces produced: `spatalk.text.chat.router` serving `GET /widget.js`,
`GET /widget/{tenant_id}/config`, `WS /chat/ws`, `POST /chat/fallback`;
`spatalk.text.chat.verify_turnstile(token, secret, remote_ip=None) -> bool`;
`spatalk.text.chat.RateLimiter(limit, window)` with `allow(key, now) -> bool`;
`spatalk.text.chat.FallbackForm` (pydantic body `{tenant_id, name, contact, message, session,
turnstile}`); module constants `WIDGET_JS`, `WIDGET_MAX_AGE`, `DEFAULT_ACCENT`,
`TURNSTILE_VERIFY_URL`, `NEW_SESSIONS_PER_MINUTE`, `MESSAGES_PER_MINUTE`, `CLOSE_BAD_REQUEST`
(4400), `CLOSE_TURNSTILE` (4401), `CLOSE_UNKNOWN_TENANT` (4404), `CLOSE_RATE_LIMITED` (4429),
`CLOSE_UNAVAILABLE` (4503); `spatalk/static/widget.js`;
`spatalk.brain.tier_c.INLINE_LINK_CHANNELS`; `Settings.turnstile_site_key`,
`Settings.turnstile_secret_key`; `docs/runbooks/widget-install.md`.

## What it does

`GET /widget.js` serves the one-file widget with `Cache-Control: public, max-age=3600`.
`GET /widget/{tenant_id}/config` returns `{name, greeting, accent, turnstile_site_key}`, the
greeting rendered from the tenant's `scripts.chat_greeting` (never generated).

`WS /chat/ws?tenant&session&turnstile` checks, in order: a session id is present (4400), the
tenant exists (4404), this IP is inside 5 new sessions a minute (4429), and — when
`TURNSTILE_SECRET_KEY` is set — that Cloudflare accepts the token (4401). Only then does it
accept. Each `{"type":"message"}` frame is counted against 30 messages a minute (4429), then
goes through `TextConversationService.handle_inbound(channel="chat", external_id=<session>,
sender=None)`, so chat gets the rules gate, the guard, the tool dispatch, the 24-hour
conversation window and the `chat_in`/`chat_out` metering that SMS already had. The socket
sends `{"type":"typing"}`, then one `{"type":"reply"}` per part, and `{"type":"ended"}` plus a
close when the assistant ends the conversation. A conversation under human control returns
`suppressed`, so nothing is sent — B5 fills that silence with the staff frame.

`POST /chat/fallback` is the socket's safety net: it finds or creates the chat conversation for
that session, stores the visitor's words as a `user` message, and files a `callback` item
carrying **only** the contact (email when the field contains `@`, phone otherwise) and the name.
The message body is never copied onto the item; `test_the_fallback_item_never_carries_the_message_text`
greps every column of the row for the text to prove it.

Tier C now shows booking links inline on `chat`, `instagram` and `messenger` instead of texting
them (`INLINE_LINK_CHANNELS`), which is what the renderer's `scripts.link_shown` path was
already written for.

The widget itself is vanilla JS with inline CSS: floating button, panel, greeting, message
list, input; three reconnects with backoff, then a name/contact/message form posting to
`/chat/fallback` (at `data-fallback` when the Worker is configured, else the widget's own
origin). It respects `prefers-color-scheme` and takes its accent from `data-accent`.

## Tests: failing before, passing after

21 tests were written first against a missing module: `18 failed, 3 passed`. The three that
passed did so vacuously — two assert a 404 for an unknown tenant, which an absent route also
returns, and one (`test_a_booking_link_on_sms_is_still_texted`) is the regression guard that the
tier-C change must not touch voice or SMS. A 22nd test was added during implementation
(`test_a_runtime_with_no_model_configured_closes_the_socket_instead_of_erroring`) after the
first version raised `HTTPException` inside a websocket handler. Names follow the behaviours:

- the four chat routes are on the app; `widget.js` is served as JavaScript, cached an hour;
  the widget carries no third-party assets and follows the colour scheme; the widget is
  syntactically valid JavaScript (`node --check`); the install runbook carries the snippet and
  the accent override;
- the config endpoint returns the name, greeting, accent and site key; 404 for an unknown tenant;
- a chat message round trips through the socket (typing + reply frames, `user`/`assistant` rows,
  `external_ref` = the session, no caller, no SMS sent);
- the second message of a session stays in the same conversation;
- the socket closes after the assistant ends the conversation;
- a bad Turnstile token closes with 4401 and a good one is accepted (injected verifier);
- the sixth session from one IP in a minute closes with 4429; the thirty-first message closes
  with 4429;
- a runtime with no model configured closes with 4503 instead of erroring;
- a conversation under human control gets no bot reply;
- the fallback form creates a conversation, a message and a `callback` item; the item never
  carries the message text; a wrong edge key is 401 (and files nothing); an unknown tenant is 404;
- a booking link on chat is shown inline and never texted; a booking link on SMS is still texted.

## Beyond the suite: the plan's "done when"

The plan's second done-when is "opening `widget.js` in a browser against a local runtime shows
the greeting and a reply". No Chrome extension is connected to this machine
(`list_connected_browsers` -> `[]`), so the pixel check is still owed to a human. Two scripted
checks stand in, both against a real uvicorn on `127.0.0.1:8099` serving the real app with a
`FakeLLM` (scratchpad only, not committed):

1. `live_widget_check.py`: `widget.js: 200 public, max-age=3600 12190 bytes`,
   `config: 200 {"name": "Skincentrix", "greeting": "Hi, I'm Skincentrix's AI assistant. …"}`,
   a real WebSocket handshake returning `{'type': 'typing'}` then
   `{'type': 'reply', 'text': 'We open at ten today.'}`, and `fallback: 200 {"ok":true}`.
   -> `LIVE CHECK PASSED`.
2. `widget_dom_check.mjs`: runs the **unmodified** `widget.js` in Node 22 against that server
   with a minimal DOM stub (Node's own `WebSocket` and `fetch`). Output:
   `greeting: st-msg st-them|Hi, I'm Skincentrix's AI assistant. …`, then after a simulated
   button click and form submit,
   `bubbles: ["…greeting…", "st-msg st-me|What time do you open?", "st-msg st-them|We open at ten today."]`
   -> `WIDGET DOM CHECK PASSED`. So the widget's own config fetch, socket URL, frame handling
   and rendering are exercised, not just its syntax. Layout and colour still need eyes.

## Deviations

- **`accent` is a widget constant plus a `data-accent` attribute, not a tenant config field —
  the reference wins over the plan.** B4's interface asks the config endpoint for `accent`, but
  `docs/reference/tenant-config.md` has no accent field and says "Pydantic models in
  `runtime/spatalk/tenants/schema.py` are the single source of truth … A field added anywhere
  else is a defect". The endpoint therefore returns `chat.DEFAULT_ACCENT` (`#0f766e`) and the
  install snippet overrides it per site with `data-accent`, which is also how the runbook's
  "how to change the accent colour" section reads. Evidence:
  `grep -n accent spatalk/tenants/schema.py` -> no match; `curl /widget/skincentrix/config` ->
  `{"name": …, "accent": "#0f766e", …}`. If a tenant-level accent is ever wanted, it is a
  `tenant.yaml` field plus a row in `tenant-config.md`, and the endpoint reads it there.
- **`Settings` gained `turnstile_site_key` as well as the `turnstile_secret_key` the Files list
  names.** The config endpoint's own contract in the same task returns `turnstile_site_key`, and
  `docs/reference/api-surface.md` lists `TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY | B4 | widget`.
  Both are documented in `.env.example`, whose stated job is every environment variable.
- **Cloudflare Turnstile is the one external script the widget can load, and only when a site
  key is configured.** The plan says "No third-party assets"; a Turnstile token can only be
  minted by Cloudflare's own `api.js`, so the widget injects it lazily *if and only if*
  `/widget/<tenant>/config` returned a non-empty site key, and loads nothing external otherwise.
  The runbook says so. Test `test_the_widget_carries_no_third_party_assets_and_follows_the_colour_scheme`
  asserts the file references no CDN and no plaintext origin.
- **Two shared files outside B4's Files list were touched, both by appending:
  `spatalk/http/app.py` (one `attach_router(app, text_chat.router)` line and its import) and
  `runtime/.env.example` (the two Turnstile variables).** The router is unreachable otherwise;
  this is the same seam B2 used, and `attach_router` is required because FastAPI 0.141 made
  `include_router` lazy (runtime-A14). Evidence:
  `uv run python -c "from spatalk.http.app import create_app; print(sorted(r.path for r in create_app(None, start_background=False).routes))"`
  now lists `/chat/fallback`, `/chat/ws`, `/widget.js`, `/widget/{tenant_id}/config`.
- **One existing assertion in `tests/test_tier_c.py` changed, and it is a correction, not a
  loosening.** `test_booking_link_is_captured_when_no_sms_or_no_phone` asserted that a booking
  link on `channel="chat"` with no contact is `Refused(no_contact)`. B4's interface makes that
  wrong: on a screen the link is shown in the conversation, so no contact is needed. The
  no-contact refusal is still asserted (moved to `channel="voice"`, where a link really does need
  somewhere to go) and a new assertion was added that chat returns `link_sent` **and** sends no
  SMS. Evidence: before the edit `uv run pytest -q` -> `1 failed, 266 passed, 1 skipped`,
  `AssertionError: assert ('link_sent' == 'refused')`; after it, `268 passed, 1 skipped`.
- **Three close codes exist beyond the plan's 4401 and 4429**: 4400 (no session id), 4404
  (unknown tenant) and 4503 (no LLM configured). The plan names close codes only for Turnstile
  and the rate limit, but a socket must be closed for these three too, and `_service(ctx)` raises
  `HTTPException(503)` (B2's behaviour when `GOOGLE_API_KEY` is absent) which a websocket route
  cannot return. Closing before `accept()` is what lets the widget fall through to its form.
- **`handle_inbound` is called with `provider_message_id=None` on chat.** B2's note expected chat
  to pass a real id and let the service dedup, but a WebSocket frame has no provider id: the
  socket is the delivery guarantee. Nothing is deduplicated on chat, and nothing needs to be.
- **`POST /chat/fallback` auth is "edge key when one is configured or presented, else Turnstile
  when configured, else open".** `api-surface.md` says `X-Edge-Key` or Turnstile. A widget
  posting directly (no Worker configured) presents neither header nor, in most installs, a
  token, so refusing it would delete the very message the fallback exists to save. The rule
  implemented is: if the request carries `X-Edge-Key` or the runtime has an edge key configured,
  the key must match (401 otherwise); else if a Turnstile secret is set, the body's token must
  verify; else accept. Test: `test_the_fallback_form_is_rejected_with_a_wrong_edge_key`.
- **The rate limiter is per process and in memory.** One runtime node is the deployment
  (`docs/runbooks/deploy.md`), so a dict of deques is the honest size; it is a class
  (`RateLimiter`) held on `app.state`, so a shared store is a one-line swap when a second node
  appears. It counts against `X-Forwarded-For`'s first hop when present, since Caddy fronts the
  runtime.
- **No model change, no migration, no tenant bundle change.** Chat reuses `conversations` with
  `channel="chat"` and `external_ref=<session uuid>`, which B2 created; `scripts.chat_greeting`
  and `scripts.link_shown` were already authored in both `Scripts` and the Skincentrix bundle
  (`grep -n "chat_greeting\|link_shown" tenants/skincentrix/scripts.yaml` -> lines 12 and 20).
- **Websocket tests drive the ASGI app directly.** `httpx` cannot open a WebSocket and
  Starlette's `TestClient` runs its own event loop, which would touch this test's asyncpg engine
  from a second loop. `tests/test_widget.py::WS` speaks the ASGI websocket protocol over two
  queues instead, so the whole test stays in one loop and real routing, real close codes and
  real frames are exercised. Starlette's close frame carries `reason` as well as `code`, which
  the helper `_closed()` accounts for.
- **One new conditional skip exists**: `test_the_widget_is_syntactically_valid_javascript` is
  `skipif` on `shutil.which("node") is None`. Node 22 is installed here, so it **ran** and passed;
  the suite's single skip is still the pre-existing one.

## Notes for neighbours

- **B5 (takeover) owns the `{"type":"staff"}` frame and needs a socket registry.** `chat.py`
  deliberately holds no map of live sockets: `handle_inbound` already returns
  `suppressed=True, reason="human"` and the socket simply says nothing, so B5 can add
  `app.state.chat_sockets[(tenant_id, session)] = websocket` in the accept path and pop it in the
  `finally`, then push staff text through it (falling back to storing the message for the next
  connect, which the widget will render because it already handles the `staff` frame and styles
  it distinctly). The widget needs no change for that.
- **The chat conversation key is the session uuid the widget generates** (`crypto.randomUUID`,
  stored in memory only), so a page reload starts a new conversation. If the portal (C-plan) or
  D-plan wants continuity across reloads, put the session id in `sessionStorage` in the widget —
  the runtime side already reuses a conversation for 24 h on that key.
- **`text.chat` imports `spatalk.text.service`**, so importing the chat router also registers the
  `text.followup` handler; nothing schedules a follow-up for chat, though, because
  `schedule_followup` still guards on `channel == "sms"` and a caller phone (B2's decision: there
  is no way to reach a chat visitor later). The fallback form is the route for a visitor who
  leaves.
- **Tier C's `INLINE_LINK_CHANNELS` already covers `instagram` and `messenger`,** so D2 and D3
  inherit inline booking links and the `scripts.link_shown` wording with no capability change.
- **E7's `/healthz` route dump and any operational route inventory now include four more paths.**
  All four are unauthenticated by design (`api-surface.md`: widget and config are `none`, the
  socket is Turnstile, the fallback is edge key or Turnstile), so a future rate-limit or WAF rule
  should treat `/widget.js` and `/widget/*/config` as public cacheable and `/chat/*` as the
  guarded pair.
- **`widget.js` ships inside the wheel** (`hatch.build.targets.wheel.packages = ["spatalk"]`
  includes non-Python files under `spatalk/`) and is not excluded by `.dockerignore`, so the
  container serves it. E-plan deploy work must keep `spatalk/static/` in the image.
