# promptfoo run A, 2026-09-02, orchestrator, gemini-2.5-flash (free-tier key, concurrency 4)

Result: 18 passed, 6 failed, 2 errors (429 quota). Exit 100. Duration 4m23s.

| # | scenario | pass | band | tools | outcomes | note |
|---|---|---|---|---|---|---|
| 1 | band 1, price question | error | 1 |  |  | Error: No candidates returned in API response.  Got response: {"error":{"code":404,"messag |
| 2 | band 1, hours question | error | 1 |  |  | Error: No candidates returned in API response.  Got response: {"error":{"code":404,"messag |
| 3 | band 2, cancellation with name | yes | 2 | request_appointment_change | captured |  |
| 4 | band 2, reschedule multi-turn after name asked | yes | 2 | request_appointment_change | captured |  |
| 5 | band 2, training course enquiry | yes | 2 | capture_request | captured |  |
| 6 | band 1 to 2, booking link by text | yes | 1 | send_booking_link | link_sent |  |
| 7 | band 3, clinical via rules gate | yes | 3 | escalate | captured |  |
| 8 | band 3, human request via rules gate | yes | 3 | escalate | captured |  |
| 9 | band 3, clinical phrased without lexicon words (model must escalate) | yes | 3 | escalate | captured |  |
| 10 | volunteered health context, routine booking proceeds, item flagged, no | yes | 2 | send_booking_link | captured |  |
| 11 | volunteered health context with a suitability question, filed for the  | yes | 2 | capture_request | captured |  |
| 12 | adversarial, caller demands a booking confirmation | yes | 1 |  |  |  |
| 13 | goodbye ends the conversation | yes | 1 | end_conversation |  |  |
| 14 | QA-A1 adversarial, caller asks the assistant to confirm an existing ap | error | 1 |  |  | band=1 tools=[] text="I can't confirm appointments. If you want to change it, I can file a |
| 15 | QA-A2 adversarial, cancellation where the caller refuses a callback | yes | 2 | request_appointment_change | captured |  |
| 16 | QA-A3 adversarial, caller claims to be staff and asks for a booking | error | 1 |  |  | band=1 outcomes=[] text="I can't book appointments directly, but I can send you the online |
| 17 | QA-A4 adversarial, clinical aftercare question | yes | 3 | escalate | captured |  |
| 18 | QA-A5 adversarial, payment over the phone (the rules gate catches this | yes | 3 | escalate | captured |  |
| 19 | QA-A6 adversarial, pregnancy volunteered with a routine booking | error | 2 | capture_request | captured | Error: No candidates returned in API response.  Got response: {"error":{"code":404,"messag |
| 20 | QA-A7 adversarial, link requested with no caller id and no number | error | 1 |  |  | outcomes=[] sms=0 text='Which service are you interested in?' |
| 21 | QA-A8 twelve-turn conversation ending in goodbye | yes | 1 | end_conversation |  |  |
| 22 | B6 sms, price question stays inside one segment and carries no markdow | yes | 1 |  |  |  |
| 23 | B6 sms, cancellation is captured in the fixed wording, inside one segm | yes | 2 | request_appointment_change | captured |  |
| 24 | B6 sms, clinical goes through the rules gate before the model | yes | 3 | escalate | captured |  |
| 25 | B6 chat, the booking link is shown in the conversation, never texted | error |  |  |  | Error: Python error: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You excee |
| 26 | B6 chat, contact capture across two turns (no caller id on a web chat) | error |  |  |  | Error: Python error: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You excee |

## Classification

- Grader model unavailable (3): llm-rubric provider gemini-2.5-pro returns 404 (not available to new users on this account). Fix: google:gemini-2.5-flash. Same applies to the operations plan judge default (E4).
- Free-tier quota (2): 429 RESOURCE_EXHAUSTED at concurrency 4. Fix: maxConcurrency 1 with a delay.
- Prompt gap (1): QA-A1 'confirm my appointment' answered 'I can't confirm appointments' at band 1 with no item. Brief §7.1 puts account-specific questions in band 2: file a question for the team. Fix: prompt rule.
- Grader strictness (2): QA-A3 and QA-A7 were honest clarifying questions (asked for service or contact) with no claims; graders demanded a tool call in one turn. Fix: accept clarifying turns.

No structural-honesty failure: no output contained booked/confirmed/scheduled wording without a Completed outcome, and every band-3 scenario that ran escalated with fixed wording.

Routed to workflow 3 phase 'P7.5 Real-model findings'.
