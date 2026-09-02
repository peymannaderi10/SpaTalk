# Tenant configuration reference

One document per tenant, stored versioned in `runtime.tenant_config_versions`, imported from a five-file YAML bundle, edited from the portal. This page is the complete field list across all plans, with the authored fixed wording. Fixed wording is never generated at runtime; every string below can be edited per tenant, but a tenant cannot remove one.

## Bundle files

```
tenants/<id>/
  tenant.yaml     identity, hours, escalation, delivery, numbers, integration tier, social policy
  services.yaml   catalog
  knowledge.md    prose facts the model may answer from
  scripts.yaml    fixed wording
  guard.yaml      lexicon additions
```

## tenant.yaml

| field | type | required | meaning |
|---|---|---|---|
| id | slug | yes | tenant id |
| name | string | yes | spoken and written business name |
| public_phone | string | no | the clinic's own number; spoken in refusals |
| timezone | IANA | default `America/Toronto` | all business time |
| jurisdiction | string | default `CA-ON` | shown in compliance views |
| integration_tier | `A` `B` `C` | default `C` | |
| fulfilment | string | default `tier_c` | capability implementation to load |
| retention_days | int | default 30 | transcripts |
| recording_enabled | bool | default false | not implemented in these plans; must stay false |
| hours | map weekday → list of [start, end] `HH:MM` | yes | empty list means closed |
| holidays | list of dates | default [] | |
| voice_numbers | list E.164 | default [] | informational; `tenant_numbers` is authoritative |
| sms_from_number | E.164 or null | default null | the number every SMS is sent *from*, staff delivery included; a `sms` destination cannot be delivered while it is null [S1] |
| transfer_number | E.164 or null | default null | staffed back-line for live transfer [E10] |
| booking_url_default | URL | yes | |
| persona.assistant_name | string | default "the assistant" | |
| persona.tone | string | default "warm, brief, plain-spoken" | |
| persona.max_sentences_per_turn | int | default 2 | |
| escalation.owner_name, owner_email | string | yes | named owner for breaches |
| escalation.owner_phone | E.164 or null | | |
| escalation.urgent_minutes | int | default 15 | |
| escalation.standard_business_hours | int | default 3 | |
| escalation.after_hours_clinical_contact | string or null | | informational |
| delivery.destinations[] | list | yes | each: `kind` (`slack`, `email`, `webhook`, `whatsapp` [W1], `sms` [S1]), `webhook_env` (env var name for slack or webhook), `address` (email), `address_env` (env var name holding the value: required for `whatsapp` and `sms`, an alternative to `address` for `email`) [W1] [S1], `channel_id` (Slack channel id when a bot token is used) [B5], `urgent_only` bool |
| delivery.digest_time_local | `HH:MM` | default 07:30 | |
| delivery.staff_phone_numbers | list E.164 | default [] | staff who may work the ledger by SMS: `#<id> <words>` relay [B5], and `ACK`/`DONE`/`LIST` [S2]. The number every `sms` destination's `address_env` resolves to is authorised the same way without being listed here [S2] |
| social.comment_mode | `off` `keyword` `all` | default `keyword` | [D2] |
| social.comment_keywords | list | default [] | [D2] |
| social.public_reply_enabled | bool | default false | [D2] |

## services.yaml

`services:` list of: `id` (slug), `name`, `category`, `price_text`, `duration_minutes` (optional), `booking_url`, `consult_required` (bool), `clinical` (bool), `description`. The service ids become the enum the model may use; nothing outside this list can be referenced by a tool call.

## knowledge.md

Prose. Goes into the cached system prompt verbatim. Keep under 4,000 words. No wording that promises outcomes, no medical claims, no prices that change weekly unless the tenant will maintain them.

## guard.yaml

Lists of lowercase phrases added to the built-in lexicons: `human_request`, `clinical`, `health_context`, `complaint`, `payment`, `completion`. Word-bounded, case-insensitive. Built-ins live in `spatalk/brain/rules.py` and `guard.py`.

## scripts.yaml, complete, with the authored defaults

Placeholders: `{name}` business name, `{confirm_by}` rendered due wording, `{service}` service name, `{url}` booking link, `{booking_url}` default booking link, `{phone}` public phone, `{sms_number}` toll-free number. Required keys have no default; a bundle must supply them. Keys marked default may be omitted.

```yaml
# Required: the disclosure and the band-3 scripts. These are the ones that end the business if wrong.
disclosure: "Hi, thanks for calling {name}. I'm {name}'s AI assistant. I can answer questions about services, pricing and hours, and take a message for the team. How can I help?"
clinical: "That's a question for our clinical team, and I don't want to guess. I'm sending them an urgent request right now, and someone will call you back at this number {confirm_by}. If this is an emergency, please hang up and call 911."
human_request: "Of course. I'm sending a request to the team now, and someone will call you back at this number {confirm_by}."
complaint: "I'm sorry to hear that. This needs a person, not an assistant. I'm flagging it to the team as urgent, and someone will call you back at this number {confirm_by}."
payment: "I can't take or discuss payment details on this line. The team can help with that when they call you back {confirm_by}."

# Required: outcome wording.
captured: "I've sent that to the team as a request. Someone will confirm with you {confirm_by}."
link_sent: "I've just texted you the booking link for {service}. Is there anything else I can help with?"
link_captured: "I'll have the team send you the booking link for {service}. Someone will be in touch {confirm_by}."
cannot_complete: "I can't complete that from here, but I've passed it to the team and someone will confirm with you {confirm_by}."
goodbye: "Thanks for calling {name}. Have a great day."

# Defaults exist for everything below. They never promise an action.
after_hours_note: "The clinic is closed right now."
link_shown: "Here is the booking link for {service}: {url}"                                  # chat, Instagram, Messenger
refuse_no_contact: "I'd need a phone number or email to send that. Could you give me one?"
refuse_unknown_service: "I don't have that treatment on the list. Could you tell me a bit more about what you're looking for?"
refuse_out_of_scope: "That's not something I can help with from here. The clinic can, at {phone} during opening hours."
refuse_unavailable: "I'm having trouble saving that right now, so please don't count on me for it. Please call the clinic directly at {phone}."
followup: "Just checking in from {name}: still want a hand with that? Reply here anytime, or book online: {booking_url}"      # sent at most once
missed_call_text: "Hi, this is {name}'s assistant. You just called us. Reply here and I can help, or book online: {booking_url}"
offline_reply: "Thanks for texting {name}. We'll reply shortly. To book now: {booking_url}"                                   # sent by the edge worker when the platform is down
chat_greeting: "Hi, I'm {name}'s AI assistant. I can answer questions about services, prices and hours, or pass a request to the team. How can I help?"
optout_confirm: "You've been unsubscribed from {name} texts. Reply START to opt back in."
help_text: "{name}: reply with your question and the assistant will help, or call {phone}. Reply STOP to unsubscribe."
takeover_notice: "A member of the {name} team has joined this conversation."                   # shown in the chat widget only
comment_public_reply: "Thanks! Check your DMs."                                                # Instagram and Facebook public reply
dm_greeting: "Hi, this is {name}'s assistant."                                                # prefix on the first DM reply
loop_guard: "This line is answered by the clinic's assistant and cannot transfer to itself. Please call back from another number."
failover: "We can't take your call right now. Please text us at {sms_number} or book online at {booking_url}."                # carrier-hosted bin, pasted from `spatalk texml failover-bin`
transferring: "One moment, I'll connect you to the team."
```

Rules for editing: every script that mentions the team must keep `{confirm_by}` so the caller hears a time; no script may contain "booked", "confirmed" or "scheduled"; `clinical` must keep the emergency sentence; `disclosure` must say it is an AI in the first two sentences.

## Schema location

Pydantic models in `runtime/spatalk/tenants/schema.py` are the single source of truth; the portal's settings forms are generated from the JSON schema the runtime serves at `GET /internal/schema/tenant-config`. A field added anywhere else is a defect.
