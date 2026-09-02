# Review Replies Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Tests first (write the test, see it fail, make it pass, commit). Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Read `CLAUDE.md`, spec §3, §4, §5 and `docs/reference/tenant-config.md` first. This plan is parked: it is written so that it can be built without the founder present, but nothing here is scheduled.

**Goal:** New Google and Facebook reviews for a tenant appear in the portal within an hour, each with a drafted reply; positive reviews can be answered automatically when the tenant opts in, negative reviews always go to a human as a tracked item, and no reply ever confirms that the reviewer was a client or names a treatment.

**Architecture:** A `reviews` table filled by a polling job per source (Google Business Profile through the My Business API v4, Facebook recommendations through the Graph API using the page token the Instagram plan already stores). A `reviews.draft` job classifies the review, drafts a reply with a dedicated small prompt (positive) or a fixed script (negative), runs a review-specific lexical guard, and either queues the reply for approval or, when the tenant has opted in for that rating, posts it through `reviews.post`. The portal gets a Reviews page next to Requests. The model sees the review and the business name only; never a transcript, never a ledger row, never a customer record.

**Tech Stack:** existing runtime (FastAPI, SQLAlchemy, Alembic, jobs registry in `spatalk/jobs.py`, `LLMClient` from `make_llm`, `GraphClient` from `spatalk/social/graph.py`, encrypted `tenant_integrations` from `spatalk/social/models.py`), portal (Wasp 0.25, internal API with `X-Internal-Key`), Google My Business API v4 (`accounts.locations.reviews.list`, `accounts.locations.reviews.updateReply`), Facebook Graph API (`GET /{page-id}/ratings`).

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §3 (ledger: every non-self-serve thing becomes an item), §5 (structural honesty; fixed wording is config; every model utterance passes a guard), §8 (compliance, Ontario). Plan D (`2026-09-01-instagram-plan.md`) for the Meta integration this reuses. Reference pages win over this plan where they disagree.

## Global Constraints

- Everything in `CLAUDE.md` "Non-negotiables". In particular: a reply is model output, so it passes a guard before any API call; the negative-review wording is a script in `scripts.yaml`, not a prompt; secrets are environment variable names; tests use fakes and never reach Google or Meta.
- **The model never sees anything but the review.** The draft prompt receives: business name, persona tone, sign-off, the reviewer's display name, the rating, the review text. Structural test: `spatalk/reviews/` imports nothing from `spatalk/ledger/`, `spatalk/conversations.py`, `spatalk/brain/` except `spatalk/brain/guard.py` lexicons and `spatalk/brain/ports.py` types; enforced in `tests/test_structural_honesty.py`.
- **Ontario rule (PHIPA; CPSO guidance applies to any clinic with a regulated practitioner):** a public reply must not confirm that the reviewer was a client, must not name or allude to a treatment, procedure, result or visit, and must not discuss health. The guard enforces it lexically; the prompt says it in words; the human editor sees the guard's warnings.
- **No offers, no arguments, no requests.** A reply never offers money, credit, discounts, a free service or a redo; never disputes the review; never asks the reviewer to change or remove it (Google's review policy).
- **Negative reviews never get a generated reply.** Google 1 to 3 stars, Facebook "not recommended": fixed script `review_negative_reply`, plus a tracked item so a human calls the person. Posting even the fixed reply needs a human's approval.
- **One reply per review.** A review the reviewer edits after we replied gets a tracked item, not a second automatic reply.
- **Retention:** review text is public content the platform already shows; keep it while the review exists on the platform, purge a row 30 days after the platform stops returning it (retention job extension, task R2).
- **Cost:** one draft is about 700 input and 80 output tokens on Gemini Flash, under 0.001 CAD. Polling: one call per tenant per source per 30 minutes; Google's basic quota is 300 queries per minute per project, so 25 tenants use under 1 percent.
- No new product-sized dependency: no Pub/Sub (Google's push notifications need a Cloud Pub/Sub topic; polling is enough at this scale and is how Facebook is handled too).

## Prerequisites the founder must do (not agents)

1. Google: a Cloud project owned by the agency; request Business Profile API access through the "GBP API contact form" ("Application for Basic API Access"). Google requires the requesting account to own or manage a Business Profile verified for 60 or more days with a website; approval sets the project quota from 0 to 300 QPM. Create an OAuth client (web) with redirect `https://<runtime host>/oauth/google-business/callback`; store its id and secret as `GOOGLE_BUSINESS_CLIENT_ID` and `GOOGLE_BUSINESS_CLIENT_SECRET`. Scope used: `https://www.googleapis.com/auth/business.manage`.
2. Meta: add `pages_read_user_content` and `pages_manage_engagement` to the app's review submission (the Instagram plan already asks for messaging permissions).
3. Each tenant: the owner clicks "Connect Google Business Profile" in the portal and picks the location; Facebook reviews use the page already connected for Messenger.

## File Structure

```
runtime/spatalk/reviews/__init__.py
runtime/spatalk/reviews/models.py        Review table
runtime/spatalk/reviews/classify.py      is_negative(source, rating, recommended) ; reply_policy(cfg, review) -> "auto" | "approve"
runtime/spatalk/reviews/guard.py         guard_review_reply(text, cfg) -> list[str]  (violations; empty = pass)
runtime/spatalk/reviews/prompt.py        build_review_prompt(cfg, review) -> str
runtime/spatalk/reviews/google.py        GoogleBusinessClient protocol, HttpGoogleBusinessClient, FakeGoogleBusinessClient, token refresh
runtime/spatalk/reviews/facebook.py      list_recommendations(graph, page_id, token) ; post_recommendation_reply(graph, story_id, token, text)
runtime/spatalk/reviews/jobs.py          reviews.poll, reviews.draft, reviews.post handlers; schedule_review_polls(sf, registry, clock)
runtime/spatalk/http/reviews_oauth.py    GET /oauth/google-business/start, GET /oauth/google-business/callback
runtime/spatalk/http/internal.py         reviews endpoints (delimited block)
runtime/spatalk/tenants/schema.py        ReviewSettings ; Scripts gains review_negative_reply, review_positive_fallback
runtime/alembic/versions/00NN_reviews.py next free number at build time
runtime/tenants/skincentrix/tenant.yaml  reviews: {enabled: false}
runtime/tenants/skincentrix/scripts.yaml the two new scripts
runtime/tests/test_reviews_classify.py, test_reviews_guard.py, test_reviews_jobs.py, test_reviews_oauth.py, test_reviews_api.py, test_structural_honesty.py (extended)
portal/src/client/ReviewsPage.tsx, portal/src/client/settings/Integrations.tsx (Google connect button), portal/src/client/operations.ts (delimited block), portal/src/client/pages.wasp.ts (route), portal/src/client/OrgShell.tsx (nav entry)
docs/reference/data-model.md, tenant-config.md, api-surface.md   (updated in the task that adds each thing)
docs/runbooks/accounts-and-env.md        the founder prerequisites above
```

## Task R1: Schema, table, classification, guard, prompt

**Files:** `runtime/spatalk/reviews/{__init__,models,classify,guard,prompt}.py`, `runtime/spatalk/tenants/schema.py`, migration, Skincentrix bundle, `docs/reference/{data-model,tenant-config}.md`, tests `test_reviews_classify.py`, `test_reviews_guard.py`, `test_structural_honesty.py`.

**Interfaces (produces):**
- `ReviewSettings(BaseModel, frozen=True)`: `enabled: bool = False`; `google_location: str | None = None` (resource name `accounts/{a}/locations/{l}`, set by the connect flow); `facebook: bool = False` (use the connected page); `auto_post_min_rating: int | None = None` (None: every reply waits for approval; 4: Google 4 and 5 stars and Facebook "recommended" post automatically); `sign_off: str | None = None`. Field `reviews: ReviewSettings = ReviewSettings()` on `TenantConfig`. Validator: `auto_post_min_rating` must be 4 or 5 when set (negative reviews can never auto-post).
- `Scripts.review_negative_reply` default: `"Thank you for taking the time to share this. We take every piece of feedback seriously and would like to talk with you directly. Please call us at {phone} and a member of the team will follow up."`; `Scripts.review_positive_fallback` default: `"Thank you for the kind words and for taking the time to share them. The whole {name} team appreciates it."`. Both go through the existing banned-word validator.
- Table `runtime.reviews`: `id` bigint pk; `tenant_id` fk; `source` text (`google` | `facebook`); `external_id` text; unique `(tenant_id, source, external_id)`; `rating` smallint null (Google 1 to 5); `recommended` bool null (Facebook); `author_name` text; `text` text; `review_created_at`, `review_updated_at` timestamptz; `last_seen_at` timestamptz; `reply_state` text (`none` | `drafted` | `approved` | `posted` | `skipped` | `failed`); `reply_text` text null; `reply_source` text null (`model` | `script` | `human`); `guard_violations` jsonb (list of strings, empty when clean); `item_id` bigint fk null; `posted_at` timestamptz null; `last_error` text null; index `(tenant_id, reply_state)`, index `(tenant_id, review_created_at desc)`.
- `is_negative(source: str, rating: int | None, recommended: bool | None) -> bool`: Google rating of 3 or less; Facebook `recommended is False`; unknown rating counts as negative (a human looks).
- `reply_policy(cfg: TenantConfig, review: Review) -> Literal["auto", "approve"]`: `"auto"` only when not negative and `cfg.reviews.auto_post_min_rating` is set and (Google `rating >= auto_post_min_rating` or Facebook `recommended`).
- `guard_review_reply(text: str, cfg: TenantConfig) -> list[str]`: returns violation codes, empty when clean. Checks, word-bounded and case-insensitive: `service_name` (any `services[].name` as a whole phrase, and any word longer than 3 letters from `services[].id` split on `_`); `clinical` and `health_context` lexicons (built-ins plus `guard.yaml`); `client_relationship` phrases: `your treatment`, `your procedure`, `your appointment`, `your visit`, `your session`, `your results`, `your skin`, `your consultation`, `treated you`, `saw you`, `your nurse`, `your injector`; `offer`: `refund`, `discount`, `free`, `credit`, `complimentary`, `compensate`, `on the house`, `redo`; `dispute`: `unfortunately you`, `not true`, `incorrect`, `never happened`, `false`; `solicit`: `update your review`, `change your review`, `remove your review`, `edit your review`, `reconsider`; `length` when over 400 characters; `emoji` when any codepoint is in the emoji ranges; `url` when it contains `http` or `www.`. A staff first name that appears in the review text is allowed in the reply; the guard does not check names.
- `build_review_prompt(cfg: TenantConfig, review: Review) -> str`: system text with exactly these rules, in this order: you write one public reply for `{name}` to a review; tone `{persona.tone}`; at most 60 words, two sentences; thank the reviewer by first name if a name is given; refer to one specific thing they praised in their own general words; never name a treatment, procedure, product or result, never say anything that confirms they were a client, never mention health; no offers, no promises, no questions, no emoji, no links; end with `{sign_off}` when set; output the reply text only. User text: `Rating: {rating}/5` or `Recommended`, then `Review by {author_name}: {text}`.

**Tests:**
- `test_reviews_classify.py`: Google 3 stars negative, 4 positive; Facebook `recommended=False` negative; `rating=None` negative; `reply_policy` returns `approve` when `auto_post_min_rating` is None, `auto` for a 5-star with threshold 4, `approve` for a 4-star with threshold 5, `approve` for every negative regardless; validator rejects `auto_post_min_rating: 3`.
- `test_reviews_guard.py`: one test per violation code with a sentence that trips it and a near-miss that does not (for `service_name` use the Skincentrix catalog: "laser hair removal" trips, "laser-focused service" does not because the full name is matched as a phrase; "free" trips, "carefree" does not); a clean reply returns `[]`; a reply containing a staff name mentioned in the review passes.
- `test_structural_honesty.py`: AST walk over `spatalk/reviews/` asserting no import from `spatalk.ledger`, `spatalk.conversations`, or `spatalk.brain` other than `spatalk.brain.guard` and `spatalk.brain.ports`; `Scripts` without the two new keys still validates (defaults) and the defaults contain no banned word.

**Done when:** tests pass, migration applies and downgrades, `spatalk tenant import tenants/skincentrix` succeeds with `reviews: {enabled: false}`, reference docs updated. Commit `feat(reviews): settings, table, classification and reply guard`.

## Task R2: Sources: Google Business Profile and Facebook recommendations, polling

**Files:** `runtime/spatalk/reviews/{google,facebook,jobs}.py` (poll only), `runtime/spatalk/http/reviews_oauth.py`, `runtime/spatalk/http/app.py` (attach router), `runtime/spatalk/ops/retention.py` (purge rule), `runtime/.env.example`, `docs/reference/api-surface.md`, `docs/runbooks/accounts-and-env.md`, tests `test_reviews_jobs.py` (poll half), `test_reviews_oauth.py`.

**Interfaces (consumes):** `TenantIntegration` and `store_integration`, `integration_for`, `access_token`, `delete_integration`, `sign_state`, `verify_state` from `spatalk/social/meta_oauth.py` and `spatalk/social/models.py` (provider strings: existing `facebook_page`; new `google_business`); `GraphClient` from `spatalk/social/graph.py`; `enqueue`, `register_handler`, `JobContext`, `DeadLetter` from `spatalk/jobs.py`; `record_usage` from `spatalk/conversations.py` (called from `jobs.py` only, through `ctx`, so the structural test stays true: the reviews package receives the recorder as `ctx.record_usage`, wired in `build_context`).

**Interfaces (produces):**
- `class GoogleBusinessClient(Protocol)`: `async def list_reviews(location: str, token: str, page_token: str | None) -> tuple[list[dict], str | None]`; `async def update_reply(review_name: str, token: str, text: str) -> None` (PUT `https://mybusiness.googleapis.com/v4/{review_name}/reply` with `{"comment": text}`); `async def list_locations(token: str) -> list[dict]` (for the connect flow; Business Information API `accounts/{a}/locations` with `readMask=name,title`). `HttpGoogleBusinessClient(http: httpx.AsyncClient)` and `FakeGoogleBusinessClient(reviews: list[dict], locations: list[dict])` recording `replies: list[tuple[str, str]]`. `JobContext.google_business: Any = None` follows the `graph` pattern: production builds per call, tests inject the fake.
- OAuth: `GET /oauth/google-business/start?state=<signed>` redirects to Google with scope `https://www.googleapis.com/auth/business.manage`, `access_type=offline`, `prompt=consent`; `GET /oauth/google-business/callback` exchanges the code, stores the refresh token encrypted in `tenant_integrations` (provider `google_business`, `external_id` = chosen location resource name once picked), and redirects to the portal's Integrations tab with `?pick=google-business` when the account has more than one location; `POST /internal/tenants/{tenant_id}/integrations/google-business/location` body `{location: str}` finalises the choice and writes `reviews.google_location` into a new config version (actor `system:google-connect`). Token refresh: `async def google_access_token(integration, settings, http) -> str` exchanges the refresh token on each poll (short-lived access tokens are not stored).
- Facebook: `async def list_recommendations(graph: GraphClient, page_id: str, token: str) -> list[dict]` calling `GET /{page_id}/ratings?fields=open_graph_story,recommendation_type,review_text,reviewer,created_time,has_review` (page token requested by a person with `MODERATE` or higher; permission `pages_read_user_content`); `async def post_recommendation_reply(graph, story_id: str, token: str, text: str) -> None` posting a comment on the recommendation's `open_graph_story` id (`POST /{story_id}/comments`, permission `pages_manage_engagement`). Verify both edges against the Graph API reference at build time; if replying to recommendations is not possible through the API at the app's access level, Facebook reviews stay read-only (drafts shown in the portal with a "copy" action) and the tests for `post_recommendation_reply` are marked skipped with that reason in the task report.
- Job `reviews.poll` payload `{tenant_id, source}`: fetches all reviews (Google pages through `nextPageToken`; Facebook one page of 100), upserts by `(tenant_id, source, external_id)`; a new row gets `reply_state = "none"` and enqueues `reviews.draft {review_id}`; an existing row whose `review_updated_at` moved and whose `reply_state` is `posted` gets a tracked item (type `review_updated`, urgency standard, no automatic re-reply); Google reviews that already carry a `reviewReply` from before we connected are stored as `posted` with `reply_source = "human"`; `last_seen_at` updated on every poll; usage `review_poll` recorded once per run. A Google 401 or 403 dead-letters the job, marks the integration `needs_reconnect` (existing field from plan D) and raises the E7 alert `integration.reconnect`. A Meta or Google 429 raises a normal exception so the job retries with backoff.
- `schedule_review_polls(sf, registry, clock)`: called from the existing scheduler tick; for every tenant with `reviews.enabled`, enqueue `reviews.poll` for `google` when `google_location` is set and for `facebook` when `reviews.facebook` and a `facebook_page` integration exists, at most once per 30 minutes per tenant and source (dedupe on a queued or running job with the same payload).
- Retention: `spatalk/ops/retention.py` deletes review rows with `last_seen_at` older than 30 days.

**Tests:**
- Poll upserts and does not duplicate on a second run; a new row enqueues exactly one `reviews.draft`; an edited posted review creates a `review_updated` item and no draft; pre-existing Google replies land as `posted/human`; 401 dead-letters and flags the integration; 429 retries; usage rows written; scheduler enqueues once per 30 minutes and skips tenants with `enabled: false`; retention purges only rows unseen for 30 days.
- OAuth: start URL has the scope and `access_type=offline`; callback with a bad state is 400; callback stores an encrypted refresh token and never logs it (capture logs); the location choice endpoint writes a config version.

**Done when:** tests pass, `api-surface.md` lists the three new routes, the runbook has the founder prerequisites with the form name and the 60-day rule. Commit `feat(reviews): google business profile and facebook sources with polling`.

## Task R3: Draft, guard, approval, post

**Files:** `runtime/spatalk/reviews/jobs.py` (draft and post), `runtime/spatalk/brain/renderer.py` (one new public function), tests `test_reviews_jobs.py` (draft and post half), `test_structural_honesty.py` (extended).

**Interfaces (consumes):** `LLMClient` via `make_llm` (`JobContext.llm`); `guard_review_reply`, `build_review_prompt`, `is_negative`, `reply_policy` from R1; the ledger port on `ctx.ledger` with `create_item(ItemDraft)` from `spatalk/brain/ports.py` (the reviews package calls the port, never the ledger module); `fill_script(text: str, cfg: TenantConfig) -> str` added to `spatalk/brain/renderer.py` as a thin public wrapper over the existing `_fill` that fills `{name}`, `{phone}` and `{booking_url}` only.

**Interfaces (produces):**
- Job `reviews.draft {review_id}`:
  - negative: `reply_text = fill_script(cfg.scripts.review_negative_reply, cfg)`, `reply_source = "script"`, `reply_state = "drafted"`; create an item `ItemDraft(type="review_negative", urgency="standard", contact=ContactInfo(name=author_name))` and link `item_id`; deliver through the normal destinations (the staff message shows the source, the rating and the first 120 characters of the review, built from fields, plus a portal link to the review).
  - positive: call the model with `build_review_prompt`; run `guard_review_reply`; on violations, call once more with the violations appended as `Do not use: <words>`; if still violating, use `fill_script(cfg.scripts.review_positive_fallback, cfg)` with `reply_source = "script"`; else `reply_source = "model"`. Store `guard_violations` (final). Then `reply_policy`: `"auto"` sets `reply_state = "approved"` and enqueues `reviews.post`; `"approve"` sets `drafted`.
  - The model call records usage with the existing LLM usage kind and channel `reviews`.
  - Model failure (timeout, 5xx): the job retries; after the last retry the row stays `none` with `last_error`; no item is created (a positive review with no reply is not urgent); the daily digest counts it under "reviews waiting".
- Job `reviews.post {review_id, actor}`: refuses (DeadLetter) unless `reply_state == "approved"` and (`reply_text` passes `guard_review_reply` or `reply_source == "human"`); Google: `update_reply(review_name, token, reply_text)`; Facebook: `post_recommendation_reply(...)`; success sets `posted`, `posted_at`, writes an audit row (`reviews.post`, actor `system:auto` or `user:<id>`) and usage `review_reply`; a 4xx other than 429 sets `failed` and `last_error`, dead-letters and raises the E7 alert `reviews.post_failed` (with dedup); 429 and 5xx retry.
- Structural: `reviews.post` is the only code path that posts. Test asserts by scanning `spatalk/` that `update_reply` and `post_recommendation_reply` appear only in `reviews/jobs.py`, `reviews/google.py`, `reviews/facebook.py` and tests.

**Tests (through the job runner with `FakeLLM`, `FakeGoogleBusinessClient`, `FakeGraphClient`, `MemoryLedger`, `MemoryDelivery`):**
- Negative Google review: script reply, `drafted`, one item of type `review_negative`, delivered to destinations, no model call (assert the fake LLM recorded no calls).
- Positive with threshold None: model reply, `drafted`, no post job.
- Positive with threshold 4 and 5 stars: `approved`, post job enqueued, fake client received `(review_name, text)`, row `posted`, audit and usage rows exist.
- Model reply naming a service: second call made with the `Do not use` line; second reply clean: stored as `model`.
- Both model replies violate: fallback script stored, `reply_source = "script"`, `guard_violations` non-empty.
- Post refuses a `drafted` row (DeadLetter) and a row whose text fails the guard unless `reply_source == "human"`.
- Google 403 on post: `failed`, alert raised once (dedup on a second run).
- Structural honesty tests as above.

**Done when:** tests pass, suite green, ruff clean. Commit `feat(reviews): drafts with guard, approval policy and posting`.

## Task R4: Internal API, portal Reviews page, Google connect button, docs

**Files:** `runtime/spatalk/http/internal.py` (delimited block `# --- reviews (plan R, R4) ---`), `portal/src/client/ReviewsPage.tsx`, `portal/src/client/operations.ts`, `portal/src/client/pages.wasp.ts`, `portal/src/client/settings/Integrations.tsx`, `portal/src/client/OrgShell.tsx` (nav entry), `docs/reference/api-surface.md`, the OpenAPI contract for the runtime internal API in `docs/contracts/` (regenerate), tests `runtime/tests/test_reviews_api.py`, portal unit tests next to `operations.ts`, one Playwright spec `portal/e2e/reviews.spec.ts`.

**Interfaces (produces):**
- `GET /internal/tenants/{tenant_id}/reviews?state=<reply_state>&limit=50&cursor=` returns `ReviewOut[]`: `id, source, external_id, rating, recommended, author_name, text, review_created_at, reply_state, reply_text, reply_source, guard_violations, item_id, posted_at, last_error`.
- `POST /internal/reviews/{id}/reply` body `{text: str, actor: str}`: stores `text` as `reply_text` with `reply_source = "human"`, `guard_violations = guard_review_reply(text, cfg)` (warnings, not a block), `reply_state = "approved"`, enqueues `reviews.post` with the actor, returns `ReviewOut`. 409 when the row is already `posted`.
- `POST /internal/reviews/{id}/approve` body `{actor}`: approves the stored draft as is (state must be `drafted`, else 409), enqueues post.
- `POST /internal/reviews/{id}/skip` body `{actor}`: `skipped`, audit row; resolves the linked item if any with the same actor.
- `GET /internal/tenants/{tenant_id}/health` gains `reviews_waiting: int` (rows in `drafted` or `none`).
- Portal: `/app/:orgSlug/reviews` page listing reviews newest first with a rating or recommended badge, the review text, the draft in an editable text area, the guard warnings as a yellow list under it, buttons "Approve and post", "Post my edit", "Skip". A "Connect Google Business Profile" button on Integrations that opens `/oauth/google-business/start` with a signed state from the runtime (same pattern as the Instagram connect button), and a location picker when the callback returns `?pick=google-business`. The settings form gains the `reviews` section from the JSON schema automatically (the schema endpoint already drives the form); verify `auto_post_min_rating` renders as a select with "Ask me every time", 4, 5.
- Static copy above the editor: "Public replies must not confirm that the reviewer was a client or mention a treatment. The warnings below are advisory."

**Tests:**
- Runtime: list filters by state and paginates; reply endpoint stores human text with warnings and enqueues post with the actor; approve on a `none` row is 409; skip resolves the linked item; health count; all routes reject a missing or wrong `X-Internal-Key` (existing helper test).
- Portal: operations unit tests with the mocked internal client for the three actions; Playwright: a seeded drafted review shows its warnings, "Approve and post" moves it to posted.

**Done when:** tests pass on both apps, `wasp build` succeeds, OpenAPI regenerated and committed, `api-surface.md` updated, the local-demo runbook gets an optional "show a review draft" step. Commit `feat(portal): reviews page with approval and google business connect`.

## Self-review against the spec

- §3 ledger: every negative review is an item with owner and due time; edits after reply are items. Positive replies are not items because no human action is required; the digest counts waiting drafts so nothing is invisible.
- §5 honesty and fixed wording: negative wording is a script; model text passes a guard or is replaced by a script; a human's text is recorded as human. No reply can promise anything (offer and dispute lexicons). The model never sees ledger or transcript data (structural test).
- §8 compliance: client-relationship and clinical lexicons; the Ontario note in the portal; review text retention tied to the platform's own visibility.
- Providers swappable: `GoogleBusinessClient` protocol with a fake; Facebook through the existing `GraphClient`.
- Secrets: OAuth client id and secret by environment variable; refresh tokens encrypted in `tenant_integrations` like Meta tokens.
- Type consistency: `Review`, `ReviewSettings`, `guard_review_reply`, `build_review_prompt`, `is_negative`, `reply_policy`, `fill_script`, `GoogleBusinessClient`, `list_recommendations`, `post_recommendation_reply`, job names `reviews.poll`, `reviews.draft`, `reviews.post`, item types `review_negative`, `review_updated` are used with the same names in every task.
