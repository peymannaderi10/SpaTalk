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
| retention_days | int | default 30 | transcripts, and the call notes drafted from them [N1] |
| call_notes | bool | default true | whether the post-conversation job drafts `conversations.notes` from the transcript. False means no model call and no notes; the assistant still asks whether there is anything the team should know, because the answer stays in the transcript either way [N1] |
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
| team[] | list | default [] | the people a caller may ask for: each `name` (string, required, max 80 characters, the width of `items.practitioner`) and `role` (string, default ""). This list plus `any` is the whole enum for `items.practitioner`; a name outside it is nulled by the ledger and logged [L1] |
| concerns | list of strings | default `["pigmentation", "acne", "ageing", "dryness", "hair removal", "hair loss", "body contouring", "skin tightening", "tattoo removal", "glow", "other"]` | the cosmetic taxonomy behind `items.concern`; each entry is at most 40 characters, the width of the column. Deliberately not medical, and enforced: a concern matching the clinical or health-context lexicon is refused at import, and a symptom, a reaction or a condition still routes to the clinical script and lives only in the transcript [L1] |
| escalation.owner_name, owner_email | string | yes | named owner for breaches |
| escalation.owner_phone | E.164 or null | | |
| escalation.urgent_minutes | int | default 15 | |
| escalation.standard_business_hours | int | default 3 | |
| escalation.after_hours_clinical_contact | string or null | | informational |
| delivery.destinations[] | list | yes | each: `kind` (`slack`, `email`, `webhook`, `whatsapp` [W1], `sms` [S1]), `webhook_env` (env var name for slack or webhook), `address` (email), `address_env` (env var name holding the value: required for `whatsapp` and `sms`, an alternative to `address` for `email`) [W1] [S1], `channel_id` (Slack channel id when a bot token is used) [B5], `urgent_only` bool |
| delivery.digest_time_local | `HH:MM` | default 07:30 | |
| delivery.staff_phone_numbers | list E.164 | default [] | staff who may work the ledger by SMS: `#<id> <words>` relay [B5], and `ACK`/`DONE`/`LIST` [S2]. The number every `sms` destination's `address_env` resolves to is authorised the same way without being listed here [S2] |
| sms_guard.burst_limit, sms_guard.burst_window_minutes | int, int | default 12, 10 | a number past this many texts in this many minutes is muted [F1] |
| sms_guard.daily_limit | int | default 40 | texts per local day from one number before it is muted [F1] |
| sms_guard.mute_hours | int | default 24 | how long a flood mute lasts; a person can block permanently instead [F1] |
| sms_guard.tenant_daily_replies | int | default 400 | assistant SMS replies per local day before the assistant pauses on SMS until midnight [F1] |
| social.comment_mode | `off` `keyword` `all` | default `keyword` | [D2] |
| social.comment_keywords | list | default [] | [D2] |
| social.public_reply_enabled | bool | default false | [D2] |

Each `team[]` entry may carry `services: [service_id, …]`, the treatments that person performs; empty or absent means every service. The slot engine reads it for "unfortunately Helen doesn't do X" (slot engine design, §4.3).

`faq:` is a list of `{question, answer}` rows (question up to 200 characters, answer up to 600) the clinic answers in its own words. The runtime renders them into the prompt's facts under a FREQUENTLY ASKED heading, ahead of `knowledge.md`, with the rule that the assistant answers from them first, phrased, adding nothing. They are facts, not scripts: the wording the caller hears is the model's. Edited on the portal's Knowledge page.

## services.yaml

`services:` list of: `id` (slug), `name`, `category`, `price_text`, `duration_minutes` (optional), `booking_url`, `consult_required` (bool), `clinical` (bool), `description`. The service ids become the enum the model may use; nothing outside this list can be referenced by a tool call.

## knowledge.md

Prose. Goes into the cached system prompt verbatim. Keep under 4,000 words. No wording that promises outcomes, no medical claims, no prices that change weekly unless the tenant will maintain them.

A tenant's new-client offers belong here, never in the prompt or in code: the prompt tells the assistant to mention "the clinic's new-client offers listed in the facts" and nothing more, and only if the facts list any, so a clinic with no offer is never told to name one and a clinic that ends an offer edits one file [L1].

## guard.yaml

Lists of lowercase phrases added to the built-in lexicons: `human_request`, `emergency`, `clinical`, `health_context`, `complaint`, `payment`, `completion`. `emergency` is checked first and is the only gate answered with the 911 script; `clinical` holds symptoms and safety questions and no pain words, because "does it hurt?" is a question about a treatment [founder decision 2026-09-05]. Word-bounded, case-insensitive. Built-ins live in `spatalk/brain/rules.py` and `guard.py`.

## scripts.yaml, complete, with the authored defaults

Placeholders: `{name}` business name, `{confirm_by}` rendered due wording, `{service}` service name, `{url}` booking link, `{booking_url}` default booking link, `{phone}` public phone, `{sms_number}` toll-free number. Required keys have no default; a bundle must supply them. Keys marked default may be omitted.

```yaml
# Required: the disclosure and the band-3 scripts. These are the ones that end the business if wrong.
disclosure: "Hi, thanks for calling {name}. I'm {name}'s AI assistant. I can answer questions about services, pricing and hours, and take a message for the team. How can I help?"
clinical: "I've passed that to our clinical team as an urgent request, and someone will call you back at this number as soon as possible. Is there anything else I can help with?"
clinical_text: "I've passed that to our clinical team as an urgent request; someone will call you as soon as possible. Anything else I can help with?"   # text channels; default exists
emergency: "If this is an emergency, please hang up and call 911 right now. Otherwise I've sent an urgent request to our clinical team and someone will call you back at this number as soon as possible."   # the emergency lexicon only; the one script that says 911; default exists
emergency_text: "If this is an emergency, please call 911 right now. Otherwise I've sent an urgent request to our clinical team and someone will contact you as soon as possible."   # text channels; default exists
human_request: "Of course. I'm sending a request to the team now, and someone will call you back at this number as soon as they're free."
complaint: "I'm sorry to hear that. This needs a person, not an assistant. I'm flagging it to the team as urgent, and someone will call you back at this number as soon as possible."
payment: "I can't take or discuss payment details on this line. The team can help with that when they call you back, as soon as they're free."

# Required: outcome wording.
captured: "I've sent that to the team as a request. Someone will confirm with you as soon as they're free. Is there anything else I can help with?"
link_sent: "I've just texted you the booking link for {service}. Is there anything else I can help with?"
link_captured: "I'll have the team send you the booking link for {service}. Someone will be in touch as soon as they're free. Is there anything else I can help with?"
cannot_complete: "I can't complete that from here, but I've passed it to the team and someone will confirm with you as soon as they're free. Is there anything else I can help with?"
goodbye: "Thanks for calling {name}. Have a great day."

# Defaults exist for everything below. They never promise an action.
after_hours_note: "The clinic is closed right now."
link_shown: "Here is the booking link for {service}: {url}"                                  # chat, Instagram, Messenger
refuse_no_contact: "I'd need a phone number or email to send that. Could you give me one?"
refuse_no_name: "Before I pass that to the team, could I get your first name?"
refuse_unknown_service: "I don't have that treatment on the list. Could you tell me a bit more about what you're looking for?"
refuse_out_of_scope: "That's not something I can help with from here. The clinic can, at {phone} during opening hours."
refuse_unavailable: "I'm having trouble saving that right now, so please don't count on me for it. Please call the clinic directly at {phone}."

# Slot engine: the questions the runtime asks, in order (slot engine design, §7). Defaults exist.
ask_returning: "Have you been in to see us before?"
ask_offers: "Would you like to hear our new-client offers?"
ask_after_offers: "What did you have in mind?"
ask_practitioner: "Is there someone in particular you'd like to see, or whoever's available?"
ask_practitioner_again: "Sorry, who would you like to see? Anyone's fine too."
practitioner_any: "No problem, I'll leave it as whoever's available."
practitioner_not_service: "Unfortunately {practitioner} doesn't do {service}. I can suggest someone, if you don't have anyone else in mind?"
practitioner_suggest: "{names} can do {service}. Would one of them work?"
practitioner_else: "Who else did you have in mind?"
ask_service: "What would you like to come in for?"
ask_service_kind: "I can run through two or three options, or {consultation} can help you pick — which would you prefer?"
ask_service_again: "Sorry, which treatment did you have in mind?"
confirm_match: "Did you mean {value}?"
confirm_which: "Did you mean {first} or {second}?"
ask_name: "Could I get your first name?"
ask_name_again: "Just a first name is fine — it's so the team knows who to ask for."
no_name: "No problem — you can reach the clinic at {phone} during opening hours. Is there anything else I can help with?"
confirm_name_staff: "Just to check, your first name is {name} as well?"
ask_phone_same: "Is the number you're calling from the best one to reach you on?"
ask_phone: "What's the best number to reach you on?"
confirm_phone: "That's {digits} — is that right?"
phone_fallback: "No problem, I'll use the number you're calling from."
ask_window: "Which day or time of day suits you best for the visit? Any is fine."
ask_team_note: "Is there anything you'd like the team to know before they call?"
ask_route: "I can text you the booking link now, or have the team call you to book — which do you prefer?"
clinical_offer: "That's one for our clinical team rather than me — would you like me to have them reach out to you?"
clinical_declined: "No problem. Is there anything else I can help with?"
offers_intro: "Here's what we have for new clients: {offers}."
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
fillers: []   # optional phone-only lines the system speaks the instant a turn is handed to the model, e.g. ["Okay, let me check."]; empty means the model's own first words do the acknowledging
sms_paused: "Thanks for texting {name}. The assistant is paused right now. A member of the team will read your message, or you can call {phone}."   # once per sender per day when sms_guard.tenant_daily_replies is reached [F1]

# Staff-only wording for the call notes [N1]. Never spoken, never sent to a customer.
notes_label: "AI notes, drafted from the transcript"                                        # heads the notes block on the portal card, the staff email and the Slack post
notes_health_line: "Caller mentioned a health matter; read the transcript before calling."  # replaces any drafted sentence the health-context, clinical or emergency lexicon matches
still_there: "Are you still there? Take your time, I'm listening."   # once, after ten seconds of silence following the assistant's turn; the next silence gets the goodbye
model_unavailable: "Sorry, I'm having a little trouble on my end. Could you say that once more?"   # spoken once per ten seconds when the model provider fails after the SDK's retries; the repeat is a new turn
model_down: "I'm sorry, I'm not able to help on this line right now. Please call the clinic directly at {phone}."   # spoken once, and the call then ends, when a second turn in a row failed at every configured vendor (LLM_MODEL and LLM_MODEL_FALLBACK)
```

Rules for editing: every script that mentions the team must say when to expect contact, either `{confirm_by}` for a clock time or "as soon as they're free" / "as soon as possible" (founder decision 2026-09-03: Skincentrix speaks no clock time to the caller, because "by 7:29 p.m." sounds like a deadline the clinic may miss; the due time is still set on the item, shown in the portal and sent in the team's alert); no script may contain "booked", "confirmed" or "scheduled"; `emergency` and `emergency_text` must keep the 911 sentence and are the only scripts that may say it (founder decision 2026-09-05: a caller with a rash, or asking whether a facial hurts, is not told to hang up and call 911); `disclosure` must say it is an AI in the first two sentences.

## Schema location

Pydantic models in `runtime/spatalk/tenants/schema.py` are the single source of truth; the portal's settings forms are generated from the JSON schema the runtime serves at `GET /internal/schema/tenant-config`. A field added anywhere else is a defect.
