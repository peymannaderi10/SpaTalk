# Research 1c: Canadian SMS, web chat widget, staff delivery, human takeover

Researched 2026-09-01. UNVERIFIED = not confirmable from a fetched page.

## 1. SMS in Canada (A2P, two-way, a few hundred msgs/month/clinic)

### Registration and carrier filtering
- No formal Canadian 10DLC registry, but Twilio's Canada guidelines say "Canadian mobile carriers enforce strict filtering on A2P messages" and Twilio "recommends sending application-to-person (A2P) traffic over short codes or verified toll-free numbers" (https://www.twilio.com/en-us/guidelines/ca/sms).
- Twilio-reseller policy (HighLevel): Canadian long codes bought on/after **March 26, 2025** need "A2P registration" or "Persona verification" even for CA-to-CA; CA-to-US always needs A2P; "Toll-free numbers are not affected" (https://help.gohighlevel.com/support/solutions/articles/155000004915-updated-messaging-policies-for-canadian-10dlc-numbers-a2p-registration-requirements). Twilio's own article is JS-only: primary wording UNVERIFIED.
- Unregistered long codes: Rogers/Bell/Telus filter silently; "informal volume caps... as low as 100 to 250 messages per day per number" (https://www.telerivet.com/blog/canada-sms-compliance-casl-10dlc-registration). Pingram confirms carriers "do not use the 10DLC framework" yet "aggressively filter unregistered A2P traffic" (https://www.pingram.io/blog/sending-sms-to-canada-a2p-10dlc).
- **Recommendation:** Canadian toll-free + verification. Unverified toll-free "can't send SMS messages to the United States and Canada until you've completed toll-free verification" (https://www.twilio.com/docs/messaging/compliance/toll-free/console-onboarding).

### Toll-free verification time
- Twilio: "reviews TFV requests within three business days" (https://www.twilio.com/docs/messaging/compliance/toll-free/api-onboarding). Telnyx: "normally 5 business days or less"; Canadian toll-free needs **double opt-in** (https://support.telnyx.com/en/articles/10729979-toll-free-verification-request-guide).
- Since Jan 1, 2026 a Business Registration Number, issuing country and entity type are mandatory (https://www.telgorithm.com/news/toll-free-verification-is-changing-in-2026-heres-what-you-need-to-know). Budget 1-2 weeks per clinic.

### Price table (USD, pay-as-you-go, fetched 2026-09-01)
| Item | Twilio (Canada page) | Telnyx |
|---|---|---|
| Long code SMS out / in | $0.0083 / $0.0083 | US: $0.004 / $0.004 "+ carrier fee"; **Canada UNVERIFIED** (public page shows US only) |
| Toll-free SMS out / in | $0.0083 / $0.0083 | US: $0.0055 / $0.0055 "+ carrier fee"; Canada UNVERIFIED |
| Carrier pass-through out / in | Rogers-Fido $0.0084 / $0.017; Bell-Virgin $0.0087 / $0.0323; Telus $0.0073 / $0.0146; Freedom $0.0067 / $0.0089 | not published for Canada |
| Number rental / month | local $1.15; toll-free $2.15 | "From $1" local and toll-free (US page), +$0.10/mo to add SMS/MMS; Canada UNVERIFIED |

Sources: https://www.twilio.com/en-us/sms/pricing/ca ; https://telnyx.com/pricing/messaging ; https://telnyx.com/pricing/numbers. Twilio's inbound carrier fees read higher than outbound; re-check in console. At ~300 msgs/month a clinic is roughly $5-8/month on Twilio all-in.

### Same number for voice and SMS
- Yes on Twilio: a number's `capabilities` are independent booleans "Voice, SMS, and MMS", and `voice_url` / `sms_url` are configured separately on the same number (https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource). Telnyx sells SMS/MMS as a $0.10/mo add-on to an existing number (https://telnyx.com/pricing/numbers).
- Gotchas: toll-free SMS is dead until verified (above); Twilio allows one inbound SMS webhook per number, so a second product (e.g. Chatwoot, Front) will steal it (https://help.front.com/t/q52442/how-to-set-up-a-twilio-sms-inbox-in-front); Chatwoot only speaks Twilio/Bandwidth, not Telnyx (https://www.chatwoot.com/hc/user-guide/articles/1677846958-how-to-setup-an-sms-channel).

### Missed-call text-back: does the original caller ID survive forwarding?
- **RingCentral (RingEX):** the user setting "Incoming call information > Display number" has two options: "Incoming Caller ID" (the caller's number) or "Dialed Number" ("the phone number that the caller dialed, letting you see if... it's been forwarded from a RingCentral account"), applied to "Personal and mobile phones only" or "All apps and phones" (https://support.ringcentral.com/article-v2/Set-incoming-call-information.html?brand=RingCentral&product=RingEX&language=en_US). So forwards carry the original caller ID unless the clinic chose "Dialed Number". Caveats: a 2019 call-queue bug showed the called number (https://community.ringcentral.com/phone-6/caller-id-no-longer-showing-on-incoming-calls-forwarded-to-mobile-calls-7871), and manual consultative transfers show the transferring agent, blind transfers the caller (https://community.ringcentral.com/phone-6/forwarded-calls-how-to-show-original-caller-vs-the-person-who-forwarded-the-call-11160).
- **TELUS Business Connect:** TELUS's own support page returned 403. A TELUS dealer's guide describes the identical "Incoming Call Information" panel: "Called Number will display the phone number the person dialed... The Caller ID option displays the phone number of the person calling. You can add numbers before (pre-pended) or after (post-pended)" (https://wirelesscityinc.com/call-forwarding-call-handling-forwarding-telus-business-connect/). Press releases confirm a TELUS-RingCentral partnership behind Business Connect but the fetched text never literally says "white-label" (https://www.ringcentral.com/whyringcentral/company/pressreleases/telus-and-ringcentral-expand-partnership-enabling-canadian-businesses-to-transition-legacy-phone-systems-to-the-cloud.html). Treat "same setting as RingCentral" as very likely, UNVERIFIED on the official page.
- **Telnyx SIP headers:** inbound `call.initiated` webhooks carry a `custom_headers` array; documented examples show only `X-` headers (https://developers.telnyx.com/docs/voice/programmable-voice/siprec-server). No Telnyx page documents passing Diversion, P-Asserted-Identity or History-Info to webhooks: UNVERIFIED. Inbound settings expose STIR/SHAKEN attestation but nothing for Diversion (https://support.telnyx.com/en/articles/4404448-sip-connection-inbound-outbound-settings); a comparable platform stripped Diversion until a bug fix (https://community.retellai.com/t/diversion-sip-header-stripped-missing-from-custom-sip-headers-webhook-payload/3295).
- **Design implication:** do not depend on Diversion. One DID per clinic: `to` identifies the clinic, `from` is the original caller. Verify with a test call at onboarding; treat `from` == clinic main line as "caller ID lost".

## 2. Web chat widget on Squarespace
Squarespace code injection (header/footer, explicitly for "live chat services") is available on "the Core, Plus, Advanced, and some legacy billing plans" (https://support.squarespace.com/hc/en-us/articles/205815908-Using-code-injection).

**(a) Own vanilla-JS widget + WebSocket/SSE backend.** Nothing to license or host beyond your API. Reusable shells: deep-chat (MIT, 3.7k stars, web component, custom `request` + readable-stream; last release 2.5.1 on 2025-08-27, a year quiet) (https://github.com/OvidijusParsiunas/deep-chat, https://github.com/OvidijusParsiunas/deep-chat/releases); ultralytics/llm (zero-dependency SSE, but **AGPL-3.0**, https://github.com/ultralytics/llm); lesichkovm/chatui (MIT, ~12 KB, WebSocket, 0 stars, https://github.com/lesichkovm/chatui).

**(b) Self-hosted Chatwoot.** Licence: MIT except `enterprise/` (commercial) (https://github.com/chatwoot/chatwoot/blob/develop/LICENSE); community self-hosting "Free forever", paid self-hosted $19/agent/mo (Captain AI, voice, branding, roles) or $99 (SSO, SLA) (https://www.chatwoot.com/pricing/self-hosted-plans). Footprint: minimum 2 cores / 4 GB / 20 GB, production 4+ cores / 8 GB+, plus Postgres 12+, Redis 6+, Sidekiq (https://developers.chatwoot.com/self-hosted). Agent bot is community-edition (`app/models/agent_bot.rb`, `outgoing_url`, https://github.com/chatwoot/chatwoot/blob/develop/app/models/agent_bot.rb): it receives `widget_triggered` / `message_created` / `message_updated`, conversations start "pending", the bot hands off by setting "open", agents can push back to "pending" (https://www.chatwoot.com/hc/user-guide/articles/1677497472-how-to-use-agent-bots). Channels: website, email, WhatsApp Business API, Facebook Messenger, Instagram DM, Telegram, LINE, TikTok, X, SMS, voice, API (https://www.chatwoot.com/features/channels); SMS only via Twilio or Bandwidth. Honest read vs "no new dashboard": staff can answer from a Slack thread, but only if their Slack email matches a Chatwoot agent account, and all inbox/bot/channel admin lives in Chatwoot (https://www.chatwoot.com/hc/user-guide/articles/1677774874-how-to-answer-conversations-from-slack, https://developers.chatwoot.com/self-hosted/configuration/features/integrations/slack-integration-setup). It buys Instagram/Messenger/WhatsApp plumbing at the cost of a Rails box and a second system of record.

**(c) Widget-only OSS.** Papercups is in "maintenance mode" (https://github.com/papercups-io/papercups); the chat-widget topic is full platforms (Chatwoot, Libredesk) plus tiny AI widgets (https://github.com/topics/chat-widget?o=desc&s=updated). Verdict: (a), optionally on deep-chat.

## 3. Delivering tracked items without a dashboard

### Transactional email
| Provider | Free tier | Cheapest paid | Monthly floor? | Source |
|---|---|---|---|---|
| Amazon SES | $200 AWS credits, new accounts | $0.10/1,000 (+$0.12/GB attachments) | **No** (Pro $105/Enterprise $500 tiers optional) | https://aws.amazon.com/ses/pricing/ |
| Resend | 3,000/mo, 100/day, 3 domains | Pro $20/mo for 50k | No on free; no PAYG email tier | https://resend.com/pricing |
| Postmark | 100/mo developer, "No overages" | $15/mo for 10k, +$1.80/1k | Yes for paid | https://postmarkapp.com/pricing |
| Mailgun | 100/day | Basic $15/mo for 10k, +$1.80/1k | Yes for paid | https://www.mailgun.com/pricing/ |
| SendGrid | 100/day for 60-day trial only | Essentials $19.95/mo; $0.0013/email overage | Yes | https://www.twilio.com/en-us/products/email-api/pricing |
| Brevo | 300/day (help page 403'd; UNVERIFIED by fetch) | - | No on free | search snippet only |
| Cloudflare Email Service | 3,000/mo included on Workers Paid | $0.35/1,000 after | Needs Workers Paid (price not fetched) | https://developers.cloudflare.com/email-service/platform/pricing/ |

At a few hundred emails/month: Resend free or SES (cents). Only SES and Cloudflare are true metered.

### Chat webhooks with buttons
- **Slack:** incoming webhooks accept Block Kit (https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks); buttons work in Messages and send an interaction payload (https://docs.slack.dev/reference/block-kit/block-elements/button-element) as a form-encoded POST to your Request URL, ack within 3 s, `response_url` usable 5 times in 30 min to rewrite the message (https://docs.slack.dev/interactivity/handling-user-interaction). Limits 1 msg/s per webhook; no pricing in the docs (https://docs.slack.dev/apis/web-api/rate-limits). Enable Interactivity on the app that owns the webhook (works in practice; not spelled out).
- **Google Chat:** webhooks are one-way, "can't respond to or receive messages from users or Chat app interaction events", Business/Enterprise Workspace required, 1 req/s per space (https://developers.google.com/workspace/chat/quickstart/webhooks). Buttons need a full Chat app: Cloud project, HTTPS endpoint receiving `CARD_CLICKED`, 30 s response (https://developers.google.com/workspace/chat/receive-respond-interactions).
- **Microsoft Teams:** Office 365 connector webhooks were disabled May 18-22 2026; replacement is a Workflows (Power Automate) webhook owned by one user (https://devblogs.microsoft.com/microsoft365dev/retirement-of-office-365-connectors-within-microsoft-teams/, https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook). Webhook Adaptive Cards support everything "except Action.Submit": only "Action.OpenURL, Action.ShowCard, and Action.ToggleVisibility"; MessageCard "button rendering won't be supported" (https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/connectors-using). Teams buttons can only open a URL: use the magic link.

### One-click action links
Pitfalls: "some programs issue GET requests to render link previews. Browsers might even prefetch", so require an explicit click before consuming; wrong-device opens; 64-bit secrets, stored hashed; short expiry, single use (https://etodd.io/2026/03/22/magic-link-pitfalls/). Pattern: GET shows a confirm page, POST performs the idempotent ack/resolve; token scoped to one item + recipient; 7-day expiry.

## 4. Human takeover on SMS with no dashboard
- **smstoslack.com** is the cleanest reference UX: number + Slack channel; "Only replies to a thread initiated by an incoming SMS will be sent to the original sender via SMS. Any other Slack messages in the channel are ignored"; $10/number/mo, 10 cents/part (https://smstoslack.com/).
- **Social Intents** (Twilio-backed): SMS to Slack, replies return as SMS, AI bot answers first and "when the AI detects a message that needs human attention, it automatically routes the conversation to your Slack channel" (https://help.socialintents.com/article/354-connect-sms-to-slack). That is the bot-first handoff you want.
- **Chatwoot**: thread per conversation; in-thread replies reach the customer "from your Agent profile"; `note:` prefix for private notes; agent-bot pending/open status is the pause/resume switch (URLs in section 2).
- **Quo/OpenPhone**: docs describe text/missed-call/voicemail notifications only; reply-from-Slack not documented, UNVERIFIED (https://support.quo.com/core-concepts/integrations/slack).
- **Front** (https://help.front.com/t/q52442/how-to-set-up-a-twilio-sms-inbox-in-front) and **Missive** (https://missiveapp.com/docs/core-features/connected-accounts/other-channels/sms/faq) are two-way Twilio SMS inboxes with no bot handoff documented: dashboards, not relays.
- Email-reply-to-SMS relay: no fetched product documents it; UNVERIFIED. Borrowed semantics: first human reply in the thread sets `bot_paused`; bot resumes after N idle hours or a "Hand back to bot" button; every relayed SMS echoes into the thread with delivery status.

## Sources actually fetched
Every URL cited inline was fetched on 2026-09-01. Fetched but not quoted: thefastmode.com and ca.finance.yahoo.com copies of the Jan-2026 TELUS/RingCentral release. Blocked (403 or JS-only, not cited): telus.com support and press pages, help.twilio.com and support.twilio.com articles, help.brevo.com, obie.medium.com.

## Bottom line
1. Use one Canadian toll-free number per clinic on Twilio (verified in ~3 business days, double opt-in for Canada), voice + SMS on the same number; ~$2.15/mo + ~$0.02/msg all-in. Telnyx Canada rates are not public.
2. Missed-call text-back works because RingCentral/TELUS forward the original caller ID by default ("Incoming Caller ID"); identify the clinic by the dedicated DID, not by SIP Diversion, which Telnyx does not document.
3. Build the widget yourself (vanilla JS/deep-chat over WebSocket or SSE); Chatwoot is a second dashboard with Twilio/Bandwidth-only SMS and a 4-8 GB box.
4. Deliver tracked items via Slack Block Kit buttons (free, real callbacks) and email (Resend free tier or SES) with confirm-then-POST magic links; Teams and Google Chat webhooks cannot call back, so they get links only.
5. Copy the smstoslack/Social Intents semantics: SMS thread per contact, only in-thread replies relay as SMS, first human reply pauses the bot, explicit hand-back resumes it.
