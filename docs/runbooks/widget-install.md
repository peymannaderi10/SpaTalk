# Installing the web chat widget

The widget is one file the runtime serves at `/widget.js`. It has no build step, loads no
third-party assets (the one exception is Cloudflare Turnstile, and only when a site key is
configured), and follows the visitor's light or dark colour scheme.

## Squarespace (and any site with code injection)

Settings → Advanced → **Code Injection** → *Footer*, then paste:

```html
<script src="https://api.<domain>/widget.js" data-tenant="skincentrix" defer></script>
```

Replace `api.<domain>` with the runtime's public host (`PUBLIC_BASE_URL` without the scheme,
e.g. `api.skincentrix.ca`) and `skincentrix` with the tenant id. Save, then reload the public
site: a "Chat with us" button appears bottom right.

WordPress, Wix, Webflow and a plain HTML site take the same tag; put it just before `</body>`.

## Options on the script tag

| attribute | default | what it does |
|---|---|---|
| `data-tenant` | *(required)* | the runtime tenant id; the widget refuses to load without it |
| `data-accent` | `#0f766e` | the button, header and outgoing-bubble colour; any CSS colour |
| `data-label` | `Chat with us` | the text on the floating button |
| `data-fallback` | the widget's own origin | base URL the fallback form posts to; set it to the Cloudflare Worker so the form still works when the runtime is down |

Changing the accent colour to the clinic's brand teal:

```html
<script src="https://api.<domain>/widget.js" data-tenant="skincentrix"
        data-accent="#b08968" defer></script>
```

Pointing the fallback form at the Worker (recommended in production):

```html
<script src="https://api.<domain>/widget.js" data-tenant="skincentrix"
        data-fallback="https://sms-worker.<account>.workers.dev" defer></script>
```

## What the visitor sees

1. A floating button. Clicking it opens the panel and shows the tenant's `chat_greeting`
   from `scripts.yaml` — the greeting is tenant config, never generated.
2. Messages go over a WebSocket to `/chat/ws` and through the same brain as phone and SMS.
   Booking links are shown inline in the conversation (`scripts.link_shown`); nothing is
   texted, because there is no phone number in a chat.
3. If the socket drops, the widget reconnects up to three times. After that it shows a short
   form (name, phone or email, message) that posts to `/chat/fallback`. That call creates a
   `callback` item for the team. The message body is stored in the conversation transcript
   only — it is never copied onto the item, which carries the contact and nothing else.
4. Rate limits are per IP: 5 new sessions and 30 messages a minute. Exceeding them closes the
   socket with code 4429 and the widget tells the visitor to try again shortly.

## Turnstile (optional, recommended once the widget is public)

1. Cloudflare dashboard → Turnstile → **Add site**, hostname = the clinic's domain, widget
   mode **Invisible**.
2. Put the two keys in `runtime/.env`:

   ```
   TURNSTILE_SITE_KEY=0x4AAAAAAA...
   TURNSTILE_SECRET_KEY=0x4AAAAAAA...
   ```

3. Restart the runtime. `GET /widget/<tenant>/config` now returns the site key, the widget
   loads the Turnstile script and passes a token on `/chat/ws`, and the runtime verifies it
   with Cloudflare. A connection with no valid token is closed with code 4401.

With no `TURNSTILE_SECRET_KEY` set, the socket does not challenge and the widget loads
nothing from outside the runtime's own origin.

## Checking it works

```
curl -sS https://api.<domain>/widget/skincentrix/config
```

should return the tenant name, the greeting, the accent and the site key (empty string when
Turnstile is off). Then open the clinic's site, click the button, and send "what time do you
open" — the reply arrives in the panel and the conversation is visible in the runtime with
channel `chat`.
