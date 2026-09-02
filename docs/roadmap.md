# Roadmap and competitive map

Last updated 2026-09-02. This page records what SpaTalk has, what is parked with a plan, and what is out of scope, using GoHighLevel's AI page (https://www.gohighlevel.com/ai) as the yardstick because it is the product prospects will compare us with. Nothing here is a commitment; the founder decides what moves.

## What GoHighLevel sells versus what SpaTalk does

| GoHighLevel claim | SpaTalk today | Notes |
|---|---|---|
| AI receptionist answers calls around the clock | **Built.** Telnyx voice, Pipecat, Soniox, Gemini Flash; disclosure script first; fixed wording for every outcome. | Plan A. |
| Qualifies leads | **Built, narrower on purpose.** Every request becomes a tracked item with type, service, contact and preferred window; nothing free-text. | The portal shows items per channel and time to action. A "lead" is an item of type `new_booking` or `callback`. |
| Books appointments | **Tier C: captures, does not book.** The assistant sends the booking link or files a request; a human books in Jane. | Tier A needs a booking platform with a write API. Jane has none. Fresha has none. Acuity, Square Appointments, Mindbody and Zenoti do. Decide tenant by tenant; see "Parked" below. |
| Missed-call text-back | **Built.** `missed_call_text` script, `sms.textback` job. | Plan B. Needs the tenant's messaging number (Skincentrix: the 289 local number; toll-free once verified). |
| Conversations across SMS | **Built.** Telnyx SMS with the Cloudflare edge worker for offline auto-reply and replay. | Plan B. |
| Facebook and Instagram | **Built.** Instagram DMs and comments (keyword mode), Messenger, public comment reply script. | Plan D. Needs Meta app review before real accounts connect. |
| WhatsApp | **Not built as a customer channel.** The WhatsApp work done so far (plan W, task W1) is staff notification only, and is dormant. | Customer-facing WhatsApp would be a fourth Meta adapter next to Instagram and Messenger. Parked with Slack. |
| Live chat | **Built.** Web chat widget with takeover. | Plan B, `docs/runbooks/widget-install.md`. |
| Reputation: auto-reply to reviews | **Planned, not built.** `docs/superpowers/plans/2026-09-02-review-replies-plan.md`. | Google Business Profile and Facebook recommendations. Ontario privacy rules shape the design: a public reply must never confirm the reviewer was a client or name a treatment. |
| Reputation: review requests after visits | **Out until Tier A.** We do not know when a visit happened. | Becomes a one-day task once a tenant is on Tier A. |
| Website builder, funnels, CRM, email marketing | **Out of scope by decision.** SpaTalk is a front desk and a ledger, not a marketing suite. | Tenants keep Wix, Squarespace or whatever they have. The widget embeds anywhere. |

Where the products differ in kind, not degree: GoHighLevel's assistant is allowed to say "booked". Ours is built so that it cannot, and every claim it makes about an action is backed by a row a human can see. That is the pitch to a clinic that has been burned by a bot promising things.

## Parked, with a plan

| Feature | Plan | State | What unblocks it |
|---|---|---|---|
| Staff notifications on Slack | `2026-09-01-text-channels-plan.md` task B5 | Built; the Skincentrix bundle carries a Slack destination with no webhook set. | A Slack workspace at the tenant. Set `SKINCENTRIX_SLACK_WEBHOOK`. |
| Staff notifications on WhatsApp | `2026-09-02-whatsapp-delivery-plan.md` | W1 committed (destination kind, migration 0008); W2 onward not started. | Meta developer login and a WhatsApp Business number. |
| Review replies | `2026-09-02-review-replies-plan.md` | Plan only. | Google Business Profile API access for the agency's Cloud project (form; profile verified 60+ days), Meta app review for two page permissions. |
| WhatsApp as a customer channel | none yet | Not started. | Same Meta prerequisites; write a plan modelled on the Instagram plan. |
| Tier A booking | spec §3 (integration tiers) | Not started. | A tenant on a platform with a write API. The capability interface already exists (`fulfilment` in tenant config). |
| Recording | spec §9 | Deliberately off. | A tenant flag, consent wording in `scripts`, and a retention decision. Not before a lawyer reads it. |

## Not doing

- Website builder, funnels, forms, email campaigns, CRM pipelines, payments.
- A model that can say an appointment is booked when it is not.
- Free text on tracked items.
