/**
 * SpaTalk SMS front door.
 *
 * Telnyx posts inbound messages here instead of straight at the runtime. The worker
 * verifies the Telnyx signature, forwards the raw body to the runtime, and — only when
 * the runtime does not accept it — sends the tenant's fixed offline reply once and keeps
 * the event for replay. It never composes wording of its own: every string it can send
 * comes from KV, written there by `spatalk edge sync-texts` from the tenant's
 * `scripts.offline_reply`.
 *
 * Routes: POST /telnyx/sms, POST /chat/fallback, PUT /admin/tenant-texts.
 * Cron: every 5 minutes, replay whatever is still pending.
 */
import { verifyTelnyxSignature } from "./telnyx-signature";

export interface Env {
  /** Base URL of the runtime, e.g. https://api.spatalk.ca */
  RUNTIME_URL: string;
  /** Shared secret proving to the runtime that a request came through this worker. */
  EDGE_SHARED_KEY: string;
  /** Telnyx account Ed25519 public key, base64. */
  TELNYX_PUBLIC_KEY: string;
  /** Telnyx API key, used only for the offline auto-reply. */
  TELNYX_API_KEY: string;
  /** `<to E.164>` -> `{tenant_id, from, text}` */
  TENANT_TEXTS: KVNamespace;
  /** `pending:<message_id>`, `pending:chat:<uuid>`, `replied:<message_id>` */
  PENDING: KVNamespace;
}

/** The offline auto-reply for one of our numbers. */
export interface TenantText {
  tenant_id: string;
  from: string;
  text: string;
}

const SMS_PATH = "/telnyx/sms";
const CHAT_FALLBACK_PATH = "/chat/fallback";
const ADMIN_TENANT_TEXTS_PATH = "/admin/tenant-texts";
const TELNYX_MESSAGES_URL = "https://api.telnyx.com/v2/messages";

const FORWARD_TIMEOUT_MS = 8_000;
const SIGNATURE_TOLERANCE_S = 300;
const PENDING_TTL_S = 24 * 60 * 60;
const REPLIED_TTL_S = 7 * 24 * 60 * 60;

const PENDING_PREFIX = "pending:";
const PENDING_CHAT_PREFIX = "pending:chat:";
const REPLIED_PREFIX = "replied:";

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === SMS_PATH) {
      return handleTelnyxSms(request, env);
    }
    if (request.method === "POST" && url.pathname === CHAT_FALLBACK_PATH) {
      return handleChatFallback(request, env);
    }
    if (request.method === "PUT" && url.pathname === ADMIN_TENANT_TEXTS_PATH) {
      return handleAdminTenantTexts(request, env);
    }
    return json({ error: "not found" }, 404);
  },

  async scheduled(
    _controller: ScheduledController,
    env: Env,
    _ctx: ExecutionContext,
  ): Promise<void> {
    await replayPending(env);
  },
} satisfies ExportedHandler<Env>;

// --- routes -----------------------------------------------------------------

async function handleTelnyxSms(request: Request, env: Env): Promise<Response> {
  const rawBody = await request.text();
  const signature = request.headers.get("telnyx-signature-ed25519");
  const timestamp = request.headers.get("telnyx-timestamp");

  const signed = await verifyTelnyxSignature(
    rawBody,
    signature,
    timestamp,
    env.TELNYX_PUBLIC_KEY,
    SIGNATURE_TOLERANCE_S,
  );
  if (!signed) return json({ error: "invalid signature" }, 401);

  const response = await forwardToRuntime(env, SMS_PATH, rawBody, {
    "telnyx-signature-ed25519": signature ?? "",
    "telnyx-timestamp": timestamp ?? "",
  });
  if (response !== null && isAccepted(response)) {
    await discard(response);
    return json({ ok: true, forwarded: true });
  }
  if (response !== null) await discard(response);

  await handleRuntimeUnavailable(env, rawBody);
  // 200 even though the runtime refused it: a retry from Telnyx would become a second
  // auto-reply, and the event is safe in KV until the replay cron gets it through.
  return json({ ok: true, queued: true });
}

async function handleChatFallback(request: Request, env: Env): Promise<Response> {
  const rawBody = await request.text();
  const response = await forwardToRuntime(env, CHAT_FALLBACK_PATH, rawBody);
  if (response !== null && isAccepted(response)) {
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
    });
  }
  if (response !== null) await discard(response);

  await env.PENDING.put(`${PENDING_CHAT_PREFIX}${crypto.randomUUID()}`, rawBody, {
    expirationTtl: PENDING_TTL_S,
  });
  return json({ queued: true }, 202);
}

async function handleAdminTenantTexts(request: Request, env: Env): Promise<Response> {
  const presented = request.headers.get("X-Edge-Key") ?? "";
  if (env.EDGE_SHARED_KEY === "" || !constantTimeEquals(presented, env.EDGE_SHARED_KEY)) {
    return json({ error: "unauthorized" }, 401);
  }

  const body = await parseJson(await request.text());
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return json({ error: "expected an object of {number: {tenant_id, from, text}}" }, 400);
  }

  const entries = Object.entries(body as Record<string, unknown>);
  const texts: [string, TenantText][] = [];
  for (const [number, value] of entries) {
    const text = asTenantText(value);
    if (text === null) return json({ error: `invalid tenant text for ${number}` }, 400);
    texts.push([number, text]);
  }
  for (const [number, text] of texts) {
    await env.TENANT_TEXTS.put(number, JSON.stringify(text));
  }
  return json({ ok: true, count: texts.length });
}

// --- offline path -----------------------------------------------------------

/**
 * The runtime did not accept the event. Auto-reply once with the tenant's offline
 * wording if we know the number, then keep the raw event for the replay cron.
 */
async function handleRuntimeUnavailable(env: Env, rawBody: string): Promise<void> {
  const event = await parseJson(rawBody);
  const data = asRecord(asRecord(event)?.data);
  const payload = asRecord(data?.payload);
  const messageId = asString(payload?.id) ?? asString(data?.id);

  if (asString(data?.event_type) === "message.received" && messageId !== null) {
    await maybeAutoReply(env, payload, messageId);
  }

  const key = `${PENDING_PREFIX}${messageId ?? crypto.randomUUID()}`;
  await env.PENDING.put(key, rawBody, { expirationTtl: PENDING_TTL_S });
}

async function maybeAutoReply(
  env: Env,
  payload: Record<string, unknown> | null,
  messageId: string,
): Promise<void> {
  const to = asString(asRecord(asArray(payload?.to)?.[0])?.phone_number);
  const sender = asString(asRecord(payload?.from)?.phone_number);
  if (to === null || sender === null) return;

  const tenantText = asTenantText(await env.TENANT_TEXTS.get(to, "json"));
  if (tenantText === null) return;

  const alreadyReplied = await env.PENDING.get(`${REPLIED_PREFIX}${messageId}`);
  if (alreadyReplied !== null) return;

  // Claim the message id before sending: one attempt per message id, ever.
  await env.PENDING.put(`${REPLIED_PREFIX}${messageId}`, new Date().toISOString(), {
    expirationTtl: REPLIED_TTL_S,
  });

  try {
    const response = await fetch(TELNYX_MESSAGES_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.TELNYX_API_KEY}`,
      },
      body: JSON.stringify({ from: tenantText.from, to: sender, text: tenantText.text }),
      signal: AbortSignal.timeout(FORWARD_TIMEOUT_MS),
    });
    if (!isAccepted(response)) {
      console.warn(`telnyx auto-reply refused: ${response.status} for ${messageId}`);
    }
    await discard(response);
  } catch (error) {
    console.warn(`telnyx auto-reply failed for ${messageId}: ${String(error)}`);
  }
}

/** Cron: push everything still queued at the runtime, oldest key first. */
async function replayPending(env: Env): Promise<void> {
  let cursor: string | undefined;
  do {
    const listed = await env.PENDING.list({ prefix: PENDING_PREFIX, cursor });
    for (const key of listed.keys) {
      const rawBody = await env.PENDING.get(key.name);
      if (rawBody === null) continue;
      const path = key.name.startsWith(PENDING_CHAT_PREFIX) ? CHAT_FALLBACK_PATH : SMS_PATH;
      // Replays carry the edge key only: a Telnyx signature is minutes old by now and
      // would fail the runtime's 300 s tolerance.
      const response = await forwardToRuntime(env, path, rawBody);
      if (response === null) continue;
      const accepted = isAccepted(response);
      await discard(response);
      if (accepted) await env.PENDING.delete(key.name);
    }
    cursor = listed.list_complete ? undefined : listed.cursor;
  } while (cursor !== undefined);
}

// --- helpers ----------------------------------------------------------------

/** POSTs to the runtime; null means the request never produced a response. */
async function forwardToRuntime(
  env: Env,
  path: string,
  body: string,
  extraHeaders: Record<string, string> = {},
): Promise<Response | null> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Edge-Key": env.EDGE_SHARED_KEY,
  };
  for (const [name, value] of Object.entries(extraHeaders)) {
    if (value !== "") headers[name] = value;
  }
  try {
    return await fetch(`${trimTrailingSlash(env.RUNTIME_URL)}${path}`, {
      method: "POST",
      headers,
      body,
      signal: AbortSignal.timeout(FORWARD_TIMEOUT_MS),
    });
  } catch (error) {
    console.warn(`runtime unreachable for ${path}: ${String(error)}`);
    return null;
  }
}

function isAccepted(response: Response): boolean {
  return response.status >= 200 && response.status < 300;
}

async function discard(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // Already consumed or already cancelled.
  }
}

function trimTrailingSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function parseJson(raw: string): Promise<unknown> {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function asTenantText(value: unknown): TenantText | null {
  const record = asRecord(value);
  if (record === null) return null;
  const tenantId = asString(record.tenant_id);
  const from = asString(record.from);
  const text = asString(record.text);
  if (tenantId === null || from === null || text === null) return null;
  return { tenant_id: tenantId, from, text };
}

/** Compares two secrets without leaking their length through timing. */
function constantTimeEquals(a: string, b: string): boolean {
  const encoder = new TextEncoder();
  const left = encoder.encode(a);
  const right = encoder.encode(b);
  let diff = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let i = 0; i < length; i += 1) {
    diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  }
  return diff === 0;
}
