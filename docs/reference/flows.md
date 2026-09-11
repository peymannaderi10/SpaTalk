# Key flows

Step lists an engineer or QA agent can trace against the code. Each names the module that owns the step.

## 1. Inbound phone call (runtime plan Task 13)

1. TELUS forwards to our local number. Telnyx POSTs to `/telnyx/texml` (`voice/texml.py`).
2. Loop guard: if `From` is one of our numbers or the clinic's public phone, respond with `scripts.loop_guard` and hang up (E1).
3. Resolve tenant by `To` (`TenantRegistry.resolve_number`). Unknown: say "not configured", hang up.
4. `start_conversation` (channel voice, caller = `From`). Sign a 5-minute stream token. Respond `<Connect><Stream url="wss://media.../ws/<token>" bidirectionalMode="rtp"/></Connect>`.
5. Telnyx opens the WebSocket. `/ws/{token}` verifies the token, parses the start frame, builds the Telnyx serializer and transport (`voice/pipeline.py`).
6. Pipeline: transport in → STT → RulesGateProcessor → user aggregator (VAD, Smart Turn, mute-until-first-bot-complete) → LLM → OutputGuardProcessor → TTS → transport out → assistant aggregator.
7. On connect, the disclosure script is spoken; the caller cannot interrupt it.
8. Each final transcription: health-context lexicon sets the flag; the rules gate may short-circuit. An emergency match speaks the `emergency` script, files an urgent item and ends the call — it is the only match that ends a call, because it is the only script whose wording tells the caller to hang up. A clinical match speaks `clinical_offer` and opens the clinical flow of the slot engine (flow 10); the call stays open and nothing is filed until the caller says yes. A human-request, complaint or payment match files its urgent item, speaks its script and leaves the line open. The model's own `escalate` tool follows exactly the same rule (founder call 14ea2579, 2026-09-11 15:56:30, where `escalate {'reason':'clinical'}` for a pre-treatment question ended the call 38 ms later, mid-sentence): only `reason="emergency"` ends anything, `reason="clinical"` opens the clinical flow and its offer and files nothing, and every other reason files its item and leaves the conversation open. A request that was already open when the clinical flow opened is **parked**, not thrown away, and is handed back the moment the clinical flow closes — whether the caller accepted the offer or declined it. When the open step is the name, a bare one- or two-word answer is a name, so the two lexicons whose words collide with first names stand down for it — complaint and payment (`rules.NAME_STEP_SUPPRESSED`, reached as `rules_gate(..., name_step=True)`). Emergency, human_request and clinical still gate however few words the caller uses.
9. Model turns: the system message carries the static prompt plus the open step's brief (`voice/steps.py`), and the context's tool list is the open step's tools. Text goes through the guard sentence by sentence; a turn with no tool call gets the open step's question spoken after it, unless the caller has just heard those exact words with nothing moved in the record, in which case the model's own closing question carries the turn. While a request is open a trailing question of the model's own is dropped, so the caller is asked one thing per turn and it is the tenant's script. Tool calls run `run_tool` → `flow.apply` → capability → rendered wording spoken via `TTSSpeakFrame` with `run_llm=False`, then the next fixed question. A tool the step did not offer says nothing: the first one in a caller's turn hands the turn back to the model (`run_llm=True`) so the caller's sentence is answered from the whole conversation, and the next one falls back to the fixed question.
10. `end_conversation` tool or 45 s idle: goodbye, `EndFrame`, Telnyx hangs up via the serializer.
11. `_finalize`: transcript from context to `messages`; usage events (telephony seconds, STT seconds, TTS chars, tokens); latency list and stage p95; band; health flag. Missed-call text-back decision (B3).

## 2. Tracked item lifecycle (Tasks 8 to 10)

1. A capability calls `PgLedger.create_item` with an `ItemDraft` (no free text). Due time from `BusinessCalendar.due_for`.
2. `on_created` schedules delivery jobs per destination (Slack, email, WhatsApp, staff SMS); urgent items also go to the owner. A Slack workspace the clinic connected from the portal (onboarding §3) replaces the bundle's `slack` destination: one `deliver.slack` job with `integration: true`, the token and webhook read from the encrypted `tenant_integrations` row when the job runs, no `.env` line.
3. Worker sends: Slack Block Kit with Acknowledge and Resolve buttons (thread root when a bot token exists: the connected workspace's own, or the global `SLACK_BOT_TOKEN`; the webhook when the bot was not invited to the channel), email with confirm-then-POST links.
4. Staff acknowledge or resolve via Slack button, email link, or `#<id>` SMS; each action writes an audit row.
5. Scheduler every minute: items past `due_at`, still `open`, not yet escalated → delivery to every destination plus the owner, marked escalated once.
6. Daily digest at the tenant's local time: open items with resolve links.
7. Retention: items deleted after 400 days with a receipt.

## 3. Inbound SMS (text-channels B1, B2)

1. Telnyx POSTs to the edge worker. Signature verified. Forwarded to `/telnyx/sms` with the edge key.
2. Runtime down: worker auto-replies `scripts.offline_reply` once per message id and queues for replay; cron replays every 5 minutes.
3. Runtime: dedup by message id; tenant by `To`; STOP/START/HELP handled with fixed wording before anything else; opt-outs never receive sends.
4. `TextConversationService.handle_inbound`: find or create the conversation (24 h window), history of 20 messages, the slot record from `conversations.flow`, `Brain.turn` (rules gate, health flag, the open step's tools, guard, the next fixed question), the record written back, reply split into at most two SMS, sent from the toll-free number, usage recorded.
5. If the reply asks a question and no item exists, one follow-up is scheduled 2 h later, sent only if the customer stayed silent, never twice.
6. If a human has taken over, the message is mirrored to the Slack thread and the brain is not called.

## 4. Web chat (B4)

1. Widget loads config, opens the socket with a Turnstile token; rate limits per IP.
2. Messages go through the same `TextConversationService`. A booking walks the request flow (flow 10) and ends with the link rendered inline (`scripts.link_shown`); the number is asked for outright since there is no caller id.
3. Socket failure three times → fallback form → `/chat/fallback` (through the worker when configured) → conversation plus a `callback` item; the free text lands in the transcript only.

## 5. Human takeover (B5)

1. First item delivered with a bot token creates a Slack thread root; the conversation stores channel and ts. The token is the connected workspace's own when the tenant connected Slack from the portal, the global one otherwise.
2. Customer and assistant messages are mirrored into the thread, with the same token.
3. A staff reply in the thread → `controller=human`; the reply is relayed verbatim to the customer on the original channel and stored as role `staff`. The events door keeps the one signing secret (one app, many workspaces) and finds the conversation by channel id and thread ts.
4. While human: no brain; customer messages still mirrored.
5. "Hand back to assistant" button or 12 h of staff silence → `controller=ai`.
6. Staff SMS `#4821 running late, calling at 3` relays to that item's conversation.

## 6. Instagram comment to DM (D2)

1. Meta POSTs to `/instagram/webhook`; HMAC verified against both app secrets; events deduplicated and queued.
2. Comment event, tenant policy `keyword` or `all` matched, not from the account itself → conversation for the commenter → `handle_inbound` with the comment text → private reply via Graph; optional fixed public reply.
3. DM event (not an echo) → same service → reply via Graph within the 24-hour window; outside it, close and capture a callback item with the username.
4. Takeover works through the same thread mechanism; staff replies go out via Graph.

## 7. Tenant configuration update (C3, C4)

1. Owner edits hours in the portal → `PUT /internal/tenants/{id}/config` with `X-Actor`.
2. Runtime validates with the pydantic schema (422 with field paths on error), writes version N+1, audit row `config_save`.
3. Registry cache expires within 30 s; the next call or message uses the new version; `/healthz` shows the version.
4. Rollback creates version N+2 equal to the chosen old version; nothing is ever deleted.
5. Alternatively from the CLI: edit the bundle, `spatalk tenant import`, same path.

## 8. Platform down (12.7, E1, B1)

1. Voice: Telnyx fails to reach `/telnyx/texml` twice → failover URL → carrier-hosted TeXML bin says `scripts.failover` and hangs up. No server involved.
2. SMS: the worker auto-replies and replays.
3. Chat: the widget falls back to the form through the worker.
4. Uptime monitor pages the founder; alerts dedupe for 6 hours.

## 10. A request, on every channel (slot engine design, 2026-09-05)

The runtime owns the order and the wording; the model understands one answer at a time. `spatalk/brain/flow.py` is the table, `spatalk/brain/resolve.py` the matching.

1. The model calls `start_request(kind)` from the Q&A step (`new_booking`, `callback`, `reschedule`, `cancel`, `question`, `training_enquiry`), or the `clinical` flow is opened with `scripts.clinical_offer` — by the rules gate, or by the model's own `escalate {'reason':'clinical'}`, which follows the gate's rule exactly: it ends nothing and files nothing until the caller says yes. Opening the clinical flow over a request that is still in progress **parks** that request; `close_flow` hands it back at the open step it was interrupted on, and the runtime asks no question of its own on that turn, because the outcome script already ended by asking whether there is anything else. Parking is bounded at one frame: a flow only parks a previous flow of a different kind that is still open.
2. `next_step` picks the open step from the record: booking and callback ask `ask_returning` → `ask_offers` (new clients; the offers come from the facts) → `ask_practitioner` / `ask_service` (returning clients are asked who first, new clients what first) → `ask_name` → the number (`ask_phone_same` when a caller id is known, `ask_phone` otherwise; SMS skips it) → `ask_window` → `ask_team_note` → on a call with an SMS number, `ask_route`. Reschedule adds the window; cancel, question, training enquiry and clinical need only the name and the number.
3. The model is offered exactly the open step's tool (`answer`, `choose_practitioner`, `choose_service`, `give_name`, `give_phone`, `choose_window`) plus `change_answer`, `answer_question`, `escalate`, `end_conversation`. The step brief is a readiness report — what is known, what is still needed and its legal choices — and the model asks for it **in its own words**; the runtime decides which slot is open and what may be stored (model-words memo, 2026-09-11, §7 decision 1). A tool the step did not offer, one called too early, or one called with a value the runtime cannot use is **refused in words the model can read**, naming what is missing and what may be called instead: nothing is written, nothing is said to the caller, and the turn goes back to the model. Past three refusals in one caller turn the runtime speaks the open question itself. `change_answer` for a slot that holds nothing is refused the same way — there is nothing there to change.
4. `flow.apply` resolves what the caller said against the tenant's lists: exact or ≥ 0.90 stores; 0.60–0.90 *and* a word in common with the candidate asks `confirm_match` ("Did you mean Helen?") — a score in that band with no shared word is a coincidence of letters and counts as no match; below that it re-asks once; two misses settle on "any" (practitioner) or offer `ask_service_kind` (treatment). A practitioner who does not do the treatment gets `practitioner_not_service`; a first name that sounds like the practitioner gets `confirm_name_staff`; a number is read back with `confirm_phone`. A confirmation of a value the resolver could not settle is still spoken in the tenant's own words (`confirm_match`, `confirm_which`, `confirm_phone`, `confirm_name_staff`), because a wrong read-back is a wrong record.
   Two things are never resolved. An utterance carrying an interrogative or a repeat marker, or a question mark, is a question and not an answer to the open slot: it is refused and the model answers it. And a catalog row that stands for a whole category rather than a treatment — a row whose id or name is its category, or whose name sits inside two or more other names in the same category — resolves to a *kind*, so "a facial" and "the facial one" reach `ask_service_kind` with the slot still empty.
5. The moment the last required slot lands, the record files itself: `draft_from` builds the `ItemDraft` from the record (never from a tool argument), Tier C writes it, and the outcome script is spoken. A booking on a text channel ends with the link inline instead; on a call the route question decides between the link and a callback.
6. The record is persisted on `conversations.flow` after every turn, so a thread resumed within its window continues at the open step. A second request in the same conversation keeps the name and number and asks the rest again.
7. A side question at any step is `answer_question` — no arguments, nothing written: the runtime records the step it interrupted, the model answers from the facts and asks the open question again in its own words, and the frame is gone by the next turn.
8. On a call the whole turn costs one model call. The model records the answer and asks what comes next in the same reply; the tool handler speaks only the tenant's outcome lines and a confirmation, and `OutputGuardProcessor` speaks the open step's script only when that reply carried no question at all. The same rendered question is never spoken twice running on an unchanged record, whichever path would have spoken it — the tool result, the end of a model turn, or the end of a turn the caller's next words cancelled; a turn that would only have repeated itself stays silent and the "still there?" nudge holds the floor. An utterance with no content word in it (fillers and function words, no question mark, no digits) is not a turn at all: it is held, put in front of the next utterance that does carry content, and costs no model run and no question; where the open question takes a yes or a no, "okay" counts as content. Every repeat, re-prompt, repair, refused tool, barge-in and turn verdict is recorded on `conversations.signals`.

## 9. Nightly and monthly jobs (E3, E4, E5, E9)

1. 03:00 UTC retention with receipts.
2. 04:00 UTC nightly audit: lexicon scan, judge-model band audit, health-context stats; report emailed; blocking disagreements alert.
3. Daily latency report; SLO breach alerts name the stage.
4. First of the month: cost report per tenant and channel against recorded provider invoices.
