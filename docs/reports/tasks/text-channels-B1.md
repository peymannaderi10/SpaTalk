# text-channels Task B1: Cloudflare Worker in front of the SMS webhook

Status: done with deviations
Commit: the single commit whose message is `feat(edge): sms webhook worker with offline auto-reply and replay` (hash reported to the orchestrator; a hash cannot be written into the commit that carries it)
Tests: `cd edge/sms-worker && npm test` -> 23/23 (2 files: `test/signature.test.ts` 7, `test/index.test.ts` 16). Full suite for this app is the same command -> 23/23. `npx tsc --noEmit` -> exit 0. `npx wrangler deploy --dry-run` -> exit 0, "Total Upload: 10.54 KiB / gzip: 3.26 KiB". `npm ci` from a deleted `node_modules` -> 87 packages, then 23/23 again.
Interfaces produced: `edge/sms-worker` worker with `POST /telnyx/sms`, `POST /chat/fallback`, `PUT /admin/tenant-texts` and a `*/5 * * * *` `scheduled` replay; `src/index.ts` exports `default` (`ExportedHandler<Env>`), `interface Env { RUNTIME_URL, EDGE_SHARED_KEY, TELNYX_PUBLIC_KEY, TELNYX_API_KEY, TENANT_TEXTS: KVNamespace, PENDING: KVNamespace }`, `interface TenantText { tenant_id, from, text }`; `src/telnyx-signature.ts` exports `verifyTelnyxSignature(rawBody, signatureB64, timestamp, publicKeyB64, toleranceSec = 300, nowSec = now)`, `importTelnyxPublicKey(publicKeyB64)`, `decodeBase64(value)`.

## What it does

`POST /telnyx/sms` verifies the Ed25519 signature over `"{timestamp}|{raw_body}"` with a 300 s
tolerance (401 and nothing else on failure), forwards the raw body to
`${RUNTIME_URL}/telnyx/sms` with `Content-Type: application/json`, `X-Edge-Key` and the two
original Telnyx headers under an 8 s timeout, and answers 200 on 2xx. On a timeout or a non-2xx
it looks up `TENANT_TEXTS[to]`, and if that number is ours and `replied:<message_id>` is absent,
sends that tenant's fixed offline wording once through `POST https://api.telnyx.com/v2/messages`;
either way it stores the raw event under `pending:<message_id>` (24 h TTL) and still answers 200,
because a Telnyx retry would otherwise become a second reply. The cron replays every
`pending:*` key, deleting on 2xx and leaving it otherwise. `POST /chat/fallback` passes the
runtime's answer through when it is up and queues under `pending:chat:<uuid>` with 202
`{"queued": true}` when it is not. `PUT /admin/tenant-texts` replaces the KV entries given, behind
a constant-time `X-Edge-Key` check.

The worker composes no wording of its own: the only text it can ever send is the tenant's
`scripts.offline_reply`, pushed into KV by `spatalk edge sync-texts` (Task B6).

## Tests: failing before, passing after

Written first, run against stubs that returned `false` / `501`: `18 failed | 5 passed (23)` — the
5 that passed were the negative cases a stub satisfies by accident (401, 404, "rejects …").
After the implementation: `23 passed (23)`.

Named after the behaviours they prove:

- `test/signature.test.ts` — accepts a signature the telnyx account key made over `timestamp|body`;
  rejects a signature made over a different body; rejects a signature made under a different
  timestamp; rejects a timestamp outside the 300 second tolerance (and accepts it at 3600);
  rejects a signature from another key pair; rejects a missing header, a non-numeric timestamp or
  an unconfigured public key; rejects malformed base64 instead of throwing.
- `test/index.test.ts` — forwards a validly signed message to the runtime and does not auto-reply
  (asserting the forwarded body is byte-identical and the four headers are present); rejects an
  invalid signature with 401 and never reaches the runtime (zero outbound calls, zero KV writes);
  auto-replies once and queues the event when the runtime is unavailable (asserting the Telnyx
  body is exactly `{from, to, text}` from KV and the bearer token); never auto-replies twice to the
  same telnyx message id; queues without auto-replying when the number has no tenant text; queues a
  delivery-report event without auto-replying; deletes a pending event once the runtime accepts it;
  keeps a pending event when the runtime is still failing; replays a queued chat fallback to the
  chat endpoint; passes the runtime's answer through when the runtime is up; queues the form and
  answers 202 when the runtime is unreachable; rejects a request without the edge key; rejects a
  request whose edge key is wrong; replaces the tenant texts given when the edge key matches;
  rejects a body that is not a map of tenant texts; answers 404 on an unknown route.

Every test in `index.test.ts` drives the real `worker.fetch` / `worker.scheduled` inside workerd
with real KV; only the outbound `fetch` is stubbed.

Deviations:

- **`@cloudflare/vitest-pool-workers` 0.22.0 has no `./config` entry point and no
  `defineWorkersConfig`.** 0.22.0 is the only line that supports the installed Vitest 4 (its
  peer range is `vitest: ^4.1.0`), and it moved configuration to a Vite plugin. `vitest.config.ts`
  is therefore `defineConfig({ plugins: [cloudflareTest({ wrangler: {...}, miniflare: {...} })] })`.
  Evidence: `npm test` first failed with `Error: Missing "./config" specifier in
  "@cloudflare/vitest-pool-workers"`, and
  `node -e "console.log(JSON.stringify(require('./node_modules/@cloudflare/vitest-pool-workers/package.json').exports))"`
  -> `{".": {...}, "./types": {...}, "./codemods/vitest-v3-to-v4": {...}}`. The package's own
  codemod (`dist/codemods/vitest-v3-to-v4.mjs`) performs exactly this rewrite:
  `const pluginCall = j.callExpression(j.identifier("cloudflareTest"), [workersProp.value])`.
- **The same version removed `fetchMock` from `cloudflare:test`**, so the plan's implied undici
  `MockAgent` interception is not available. Outbound calls are stubbed with
  `vi.stubGlobal("fetch", …)` in `test/helpers.ts` (`stubFetch(routes)`), which records every call
  (method, URL, headers, body) and throws on a route that was not declared — the same guarantee
  `disableNetConnect()` gave. Evidence:
  `grep -o "export {[^}]*}" node_modules/@cloudflare/vitest-pool-workers/dist/worker/lib/cloudflare/test.mjs`
  -> `export { SELF, abortAllDurableObjects, …, createScheduledController, env, …, reset, …,
  waitOnExecutionContext }` with no `fetchMock`, and `grep -rln fetchMock node_modules/@cloudflare/vitest-pool-workers/`
  -> no matches.
- **Storage is not isolated per test in this version**, so `beforeEach` calls `reset()` from
  `cloudflare:test` ("Deletes all data from all attached bindings"). Evidence: before adding it,
  7 tests failed with keys accumulating across tests, e.g.
  `expected [ 'pending:msg-offline-1', …(1) ] to deeply equal [ 'pending:msg-retry-1' ]`.
- **`compatibility_date = "2026-08-22"`, not today's date.** The workerd bundled with wrangler
  4.128.0 refuses a newer one. Evidence: with `2026-09-01`, `MiniflareCoreError
  [ERR_RUNTIME_FAILURE]: … This Worker requires compatibility date "2026-09-01", but the newest
  date supported by this server binary is "2026-08-22"`. Bump it only together with a wrangler
  upgrade.
- **`verifyTelnyxSignature` takes a sixth, optional `nowSec` parameter** (default
  `Math.floor(Date.now() / 1000)`) so the tolerance window is testable without faking time. The
  plan's five-argument call shape is unchanged and is what `src/index.ts` uses.
- **Files beyond the plan's list**, all inside `edge/sms-worker/`: `vitest.config.ts` (the pool
  requires it), `test/helpers.ts` (key pairs, payload fixtures, the fetch stub),
  `package-lock.json` (`npm ci` requires it), `.dev.vars.example` (the runbook tells the founder to
  create `.dev.vars`), and `.gitignore` containing `worker-configuration.d.ts` — that file is
  generated by `wrangler types` and is 591 KB / 15,369 lines, so `npm run typecheck` regenerates it
  (`wrangler types && tsc --noEmit`) instead of the repository carrying it.
- **`PENDING` values are the raw event body and nothing else**, matching
  `docs/reference/data-model.md` ("raw event to replay"), so a replay carries `X-Edge-Key` and no
  Telnyx headers. That is also the only thing that can work: a replayed signature is minutes to
  hours old and would fail the runtime's own 300 s tolerance. The runtime must therefore have
  `EDGE_SHARED_KEY` configured for replays to be accepted; B2 behaviour 1 already accepts the edge
  key as an alternative to the signature.
- **The `replied:<message_id>` marker is written before the Telnyx send, not after.** Claiming the
  id first means a failure or a crash mid-send can never produce a second reply, which is the
  Global Constraint ("never replies twice to the same Telnyx message id"). A refused send is
  logged with `console.warn` and the event is still queued for replay.
- **The offline work is awaited rather than deferred with `ctx.waitUntil`**, so the 200 the worker
  returns to Telnyx is only sent once the auto-reply and the pending write have actually happened.
  Two KV writes and one HTTP call fit comfortably inside the request; deferring them would let the
  worker answer 200 for work that never ran.
- **`wrangler.toml` carries placeholder KV namespace ids** (`0000…ttxt`, `0000…pending`) with the
  `wrangler kv namespace create` commands in a comment above them, and `workers_dev = true` so the
  first deploy produces the `*.workers.dev` URL the Telnyx messaging profile points at
  (`docs/runbooks/accounts-and-env.md` step 6). `--dry-run` does not validate the ids; a real
  deploy will, which is the founder's step, not an agent's.
- **Reference-versus-plan check: no disagreement found.** `docs/reference/data-model.md`'s KV table
  is implemented exactly — `TENANT_TEXTS[<to E.164>] = {tenant_id, from, text}`,
  `PENDING["pending:<message_id>"]` and `PENDING["pending:chat:<uuid>"]` at 24 h,
  `PENDING["replied:<message_id>"]` at 7 days — and `docs/reference/api-surface.md`'s edge row
  (`POST /telnyx/sms`, `POST /chat/fallback`, `PUT /admin/tenant-texts`; "Telnyx signature;
  `X-Edge-Key`") matches the three routes and their auth. The Telnyx webhook fixture in
  `test/helpers.ts` is that document's payload verbatim, including the Ed25519 rule
  ("over `{timestamp}|{raw_body}`, base64 in the header, reject if `|now - timestamp| > 300 s`").

Notes for neighbours:

- **Task B2 — what actually arrives at the runtime's `POST /telnyx/sms`.** A live event carries
  `Content-Type: application/json`, `X-Edge-Key`, `telnyx-signature-ed25519` and `telnyx-timestamp`,
  with the body byte-identical to what Telnyx sent (the worker never re-serialises it, so a
  signature check on the runtime side still verifies). A **replayed** event carries only
  `Content-Type` and `X-Edge-Key` — no Telnyx headers — up to 24 h later. So the runtime's edge-key
  branch cannot be optional in production, and the dedup on `payload.id` is load-bearing: the
  worker answers Telnyx 200 whatever happens, so it can never learn that a request it timed out on
  was in fact processed, and it will replay it.
- **Task B2 — the offline reply is not the runtime's follow-up.** When the runtime is down the
  customer has already received `scripts.offline_reply` from the worker before the runtime ever
  sees the message. The replayed inbound will run the brain as normal, so the customer may get the
  offline line and then the real answer minutes later. Nothing in the worker suppresses that.
- **Task B6 (`spatalk edge sync-texts`) — the admin contract.** `PUT {worker}/admin/tenant-texts`,
  header `X-Edge-Key: $EDGE_SHARED_KEY`, body `{"<E.164>": {"tenant_id": …, "from": …, "text": …}}`.
  All three fields must be non-empty strings or the whole request is 400 and nothing is written;
  a valid request answers `{"ok": true, "count": n}`. Entries are replaced, never merged, and
  numbers not in the body are left alone — there is no delete, so retiring a number means
  overwriting it. An unset `EDGE_SHARED_KEY` on the worker rejects every admin call.
- **Task B4 (widget) — the fallback has two success shapes.** Through the worker, the widget gets
  the runtime's own body passed through (200 `{"ok": true}`) when the runtime is up, and 202
  `{"queued": true}` when it is not. Both mean "we have it"; only the 202 means the conversation
  and the `callback` item do not exist yet.
- **Task B6 (CI) — `npm ci && npm test` in `edge/sms-worker` is enough, and needs no secrets.**
  Every test generates its own Ed25519 key pair and stubs the network. If CI also runs
  `npm run typecheck`, note that it shells out to `wrangler types` first (the generated
  `worker-configuration.d.ts` is gitignored), which needs no Cloudflare credentials.
- **Runtime suite at the time of this commit.** `uv run pytest -q` in `runtime/` reported
  `3 failed, 225 passed, 1 skipped`. All three failures are in `runtime/tests/test_text_service.py`
  and `runtime/tests/test_text_sms.py`, which are untracked files from Task B2's in-flight work
  (`git status --short` shows `?? runtime/tests/test_text_service.py`, `?? runtime/spatalk/text/`,
  and modified `runtime/spatalk/models.py`). This task adds, modifies and imports no Python at all;
  its commit is scoped to `edge/sms-worker/` and this report.
