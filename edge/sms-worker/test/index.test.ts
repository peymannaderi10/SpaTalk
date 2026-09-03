import {
  createExecutionContext,
  createScheduledController,
  env,
  reset,
  waitOnExecutionContext,
} from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import worker, { type Env } from "../src/index";
import {
  callsTo,
  jsonResponse,
  makeTelnyxKey,
  messageReceivedEvent,
  signedSmsRequest,
  stubFetch,
  textResponse,
} from "./helpers";

const RUNTIME_SMS = "POST https://runtime.test/telnyx/sms";
const RUNTIME_CHAT = "POST https://runtime.test/chat/fallback";
const TELNYX_MESSAGES = "POST https://api.telnyx.com/v2/messages";
const TENANT_TEXT = {
  tenant_id: "skincentrix",
  from: "+18885550100",
  text: "Thanks for texting Skincentrix. We will reply shortly. To book now: https://book.example/ca",
};

function envWith(overrides: Partial<Env> = {}): Env {
  return { ...env, ...overrides } as Env;
}

async function pendingKeys(): Promise<string[]> {
  const listed = await env.PENDING.list({ prefix: "pending:" });
  return listed.keys.map((key) => key.name).sort();
}

beforeEach(async () => {
  // Bindings are shared across tests in this version of the pool; start every test from
  // an empty KV with exactly one known number.
  await reset();
  await env.TENANT_TEXTS.put("+18885550100", JSON.stringify(TENANT_TEXT));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("POST /telnyx/sms", () => {
  it("forwards a validly signed message to the runtime and does not auto-reply", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({ [RUNTIME_SMS]: () => jsonResponse(200) });

    const body = messageReceivedEvent();
    const request = await signedSmsRequest({ key, body });
    const signature = request.headers.get("telnyx-signature-ed25519");
    const timestamp = request.headers.get("telnyx-timestamp");
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      request,
      envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 }),
      ctx,
    );
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    expect(callsTo(calls, RUNTIME_SMS)).toHaveLength(1);
    expect(callsTo(calls, TELNYX_MESSAGES)).toHaveLength(0);
    const forwarded = calls[0];
    expect(forwarded.body).toBe(body);
    expect(forwarded.headers["x-edge-key"]).toBe("edge-key-for-tests");
    expect(forwarded.headers["content-type"]).toBe("application/json");
    expect(forwarded.headers["telnyx-signature-ed25519"]).toBe(signature);
    expect(forwarded.headers["telnyx-timestamp"]).toBe(timestamp);
    expect(await pendingKeys()).toEqual([]);
  });

  it("rejects an invalid signature with 401 and never reaches the runtime", async () => {
    const key = await makeTelnyxKey();
    const impostor = await makeTelnyxKey();
    const calls = stubFetch({ [RUNTIME_SMS]: () => jsonResponse(200) });

    const request = await signedSmsRequest({ key: impostor });
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      request,
      envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 }),
      ctx,
    );
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(401);
    expect(calls).toHaveLength(0);
    expect(await pendingKeys()).toEqual([]);
  });

  it("auto-replies once and queues the event when the runtime is unavailable", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({
      [RUNTIME_SMS]: () => textResponse(503, "runtime down"),
      [TELNYX_MESSAGES]: () => jsonResponse(200, { data: { id: "out-1" } }),
    });

    const body = messageReceivedEvent({ messageId: "msg-offline-1" });
    const request = await signedSmsRequest({ key, body });
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      request,
      envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 }),
      ctx,
    );
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    const autoReplies = callsTo(calls, TELNYX_MESSAGES);
    expect(autoReplies).toHaveLength(1);
    expect(JSON.parse(autoReplies[0].body)).toEqual({
      from: TENANT_TEXT.from,
      to: "+19055550101",
      text: TENANT_TEXT.text,
    });
    expect(autoReplies[0].headers["authorization"]).toBe("Bearer telnyx-key-for-tests");
    expect(await pendingKeys()).toEqual(["pending:msg-offline-1"]);
    expect(await env.PENDING.get("pending:msg-offline-1")).toBe(body);
    expect(await env.PENDING.get("replied:msg-offline-1")).not.toBeNull();
  });

  it("never auto-replies twice to the same telnyx message id", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({
      [RUNTIME_SMS]: () => textResponse(503, "runtime down"),
      [TELNYX_MESSAGES]: () => jsonResponse(200, { data: { id: "out-1" } }),
    });

    const workerEnv = envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const ctx = createExecutionContext();
      const response = await worker.fetch(
        await signedSmsRequest({ key, messageId: "msg-retry-1" }),
        workerEnv,
        ctx,
      );
      await waitOnExecutionContext(ctx);
      expect(response.status).toBe(200);
    }

    expect(callsTo(calls, RUNTIME_SMS)).toHaveLength(2);
    expect(callsTo(calls, TELNYX_MESSAGES)).toHaveLength(1);
    expect(await pendingKeys()).toEqual(["pending:msg-retry-1"]);
  });

  it("queues without auto-replying when the number has no tenant text", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({ [RUNTIME_SMS]: () => textResponse(503, "runtime down") });

    const request = await signedSmsRequest({
      key,
      messageId: "msg-unknown-number",
      to: "+18885559999",
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      request,
      envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 }),
      ctx,
    );
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    expect(callsTo(calls, TELNYX_MESSAGES)).toHaveLength(0);
    expect(await pendingKeys()).toEqual(["pending:msg-unknown-number"]);
    expect(await env.PENDING.get("replied:msg-unknown-number")).toBeNull();
  });

  it("queues a delivery-report event without auto-replying", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({ [RUNTIME_SMS]: () => textResponse(503, "runtime down") });

    const request = await signedSmsRequest({
      key,
      messageId: "msg-dlr-1",
      eventType: "message.finalized",
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      request,
      envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 }),
      ctx,
    );
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    expect(callsTo(calls, TELNYX_MESSAGES)).toHaveLength(0);
    expect(await pendingKeys()).toEqual(["pending:msg-dlr-1"]);
  });
});

describe("scheduled replay", () => {
  it("deletes a pending event once the runtime accepts it", async () => {
    const body = messageReceivedEvent({ messageId: "msg-replay-ok" });
    await env.PENDING.put("pending:msg-replay-ok", body);
    const calls = stubFetch({ [RUNTIME_SMS]: () => jsonResponse(200) });

    const controller = createScheduledController({
      scheduledTime: new Date(),
      cron: "*/5 * * * *",
    });
    const ctx = createExecutionContext();
    await worker.scheduled(controller, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    const replays = callsTo(calls, RUNTIME_SMS);
    expect(replays).toHaveLength(1);
    expect(replays[0].body).toBe(body);
    expect(replays[0].headers["x-edge-key"]).toBe("edge-key-for-tests");
    expect(await pendingKeys()).toEqual([]);
  });

  it("keeps a pending event when the runtime is still failing", async () => {
    await env.PENDING.put("pending:msg-replay-fail", messageReceivedEvent());
    const calls = stubFetch({ [RUNTIME_SMS]: () => textResponse(500, "still down") });

    const controller = createScheduledController({
      scheduledTime: new Date(),
      cron: "*/5 * * * *",
    });
    const ctx = createExecutionContext();
    await worker.scheduled(controller, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(callsTo(calls, RUNTIME_SMS)).toHaveLength(1);
    expect(await pendingKeys()).toEqual(["pending:msg-replay-fail"]);
  });

  it("replays a queued chat fallback to the chat endpoint", async () => {
    const key = "pending:chat:11111111-2222-3333-4444-555555555555";
    await env.PENDING.put(key, JSON.stringify({ tenant_id: "skincentrix" }));
    const calls = stubFetch({ [RUNTIME_CHAT]: () => jsonResponse(200) });

    const controller = createScheduledController({
      scheduledTime: new Date(),
      cron: "*/5 * * * *",
    });
    const ctx = createExecutionContext();
    await worker.scheduled(controller, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(callsTo(calls, RUNTIME_CHAT)).toHaveLength(1);
    expect(await pendingKeys()).toEqual([]);
  });
});

describe("POST /chat/fallback", () => {
  it("passes the runtime's answer through when the runtime is up", async () => {
    const calls = stubFetch({ [RUNTIME_CHAT]: () => jsonResponse(200) });

    const request = new Request("https://edge.test/chat/fallback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: "skincentrix", name: "Dana", contact: "+19055550101" }),
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(request, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    expect(callsTo(calls, RUNTIME_CHAT)).toHaveLength(1);
    expect(calls[0].headers["x-edge-key"]).toBe("edge-key-for-tests");
    expect(await pendingKeys()).toEqual([]);
  });

  it("queues the form and answers 202 when the runtime is unreachable", async () => {
    stubFetch({
      [RUNTIME_CHAT]: () => {
        throw new Error("connection refused");
      },
    });

    const body = JSON.stringify({ tenant_id: "skincentrix", name: "Dana", contact: "dana@x.test" });
    const request = new Request("https://edge.test/chat/fallback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(request, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ queued: true });
    const keys = await pendingKeys();
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/^pending:chat:[0-9a-f-]{36}$/);
    expect(await env.PENDING.get(keys[0])).toBe(body);
  });
});

describe("PUT /admin/tenant-texts", () => {
  it("rejects a request without the edge key", async () => {
    const request = new Request("https://edge.test/admin/tenant-texts", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ "+18885550111": TENANT_TEXT }),
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(request, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(401);
    expect(await env.TENANT_TEXTS.get("+18885550111")).toBeNull();
  });

  it("rejects a request whose edge key is wrong", async () => {
    const request = new Request("https://edge.test/admin/tenant-texts", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Edge-Key": "not-the-key" },
      body: JSON.stringify({ "+18885550111": TENANT_TEXT }),
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(request, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(401);
    expect(await env.TENANT_TEXTS.get("+18885550111")).toBeNull();
  });

  it("replaces the tenant texts given when the edge key matches", async () => {
    const replacement = { ...TENANT_TEXT, text: "New offline wording." };
    const request = new Request("https://edge.test/admin/tenant-texts", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Edge-Key": "edge-key-for-tests" },
      body: JSON.stringify({ "+18885550100": replacement, "+18885550111": TENANT_TEXT }),
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(request, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, count: 2 });
    expect(await env.TENANT_TEXTS.get("+18885550100", "json")).toEqual(replacement);
    expect(await env.TENANT_TEXTS.get("+18885550111", "json")).toEqual(TENANT_TEXT);
  });

  it("rejects a body that is not a map of tenant texts", async () => {
    const request = new Request("https://edge.test/admin/tenant-texts", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Edge-Key": "edge-key-for-tests" },
      body: JSON.stringify({ "+18885550100": { tenant_id: "skincentrix" } }),
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(request, envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(400);
    expect(await env.TENANT_TEXTS.get("+18885550100", "json")).toEqual(TENANT_TEXT);
  });
});

describe("unknown routes", () => {
  it("answers 404", async () => {
    const ctx = createExecutionContext();
    const response = await worker.fetch(new Request("https://edge.test/nope"), envWith(), ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(404);
  });
});

describe("offline replies during a flood (plan F)", () => {
  async function offline(key: Awaited<ReturnType<typeof makeTelnyxKey>>, messageId: string, from: string) {
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      await signedSmsRequest({ key, messageId, from }),
      envWith({ TELNYX_PUBLIC_KEY: key.publicKeyB64 }),
      ctx,
    );
    await waitOnExecutionContext(ctx);
    expect(response.status).toBe(200);
  }

  it("replies once per sender per hour, not once per text, and queues every text", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({
      [RUNTIME_SMS]: () => textResponse(503, "runtime down"),
      [TELNYX_MESSAGES]: () => jsonResponse(200, { data: { id: "out-1" } }),
    });

    await offline(key, "msg-flood-1", "+19055550101");
    await offline(key, "msg-flood-2", "+19055550101");
    await offline(key, "msg-flood-3", "+19055550101");

    expect(callsTo(calls, TELNYX_MESSAGES)).toHaveLength(1);
    expect(await pendingKeys()).toEqual([
      "pending:msg-flood-1",
      "pending:msg-flood-2",
      "pending:msg-flood-3",
    ]);
    expect(await env.PENDING.get("replied:sender:+19055550101")).not.toBeNull();
  });

  it("gives a second sender its own reply", async () => {
    const key = await makeTelnyxKey();
    const calls = stubFetch({
      [RUNTIME_SMS]: () => textResponse(503, "runtime down"),
      [TELNYX_MESSAGES]: () => jsonResponse(200, { data: { id: "out-1" } }),
    });

    await offline(key, "msg-a", "+19055550101");
    await offline(key, "msg-b", "+19055550102");

    const replies = callsTo(calls, TELNYX_MESSAGES).map((call) => JSON.parse(call.body).to);
    expect(replies.sort()).toEqual(["+19055550101", "+19055550102"]);
  });

  it("never replies to a blocked sender, but still queues the event for replay", async () => {
    await env.TENANT_TEXTS.put("blocked:+19055550101", "2026-09-03T00:00:00Z");
    const key = await makeTelnyxKey();
    const calls = stubFetch({
      [RUNTIME_SMS]: () => textResponse(503, "runtime down"),
      [TELNYX_MESSAGES]: () => jsonResponse(200, { data: { id: "out-1" } }),
    });

    await offline(key, "msg-blocked-1", "+19055550101");

    expect(callsTo(calls, TELNYX_MESSAGES)).toHaveLength(0);
    expect(await pendingKeys()).toEqual(["pending:msg-blocked-1"]);
  });
});

describe("PUT /admin/blocked-numbers", () => {
  function put(body: unknown, key = "edge-key-for-tests"): Request {
    return new Request("https://edge.test/admin/blocked-numbers", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Edge-Key": key },
      body: JSON.stringify(body),
    });
  }

  it("rejects a request without the right edge key", async () => {
    const ctx = createExecutionContext();
    const response = await worker.fetch(put({ numbers: [] }, "wrong"), envWith(), ctx);
    await waitOnExecutionContext(ctx);
    expect(response.status).toBe(401);
  });

  it("writes the list given and prunes numbers no longer on it", async () => {
    await env.TENANT_TEXTS.put("blocked:+19055550999", "stale");
    const ctx = createExecutionContext();
    const response = await worker.fetch(
      put({ numbers: ["+19055550101", "+19055550102"] }),
      envWith(),
      ctx,
    );
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, count: 2 });
    expect(await env.TENANT_TEXTS.get("blocked:+19055550101")).not.toBeNull();
    expect(await env.TENANT_TEXTS.get("blocked:+19055550102")).not.toBeNull();
    expect(await env.TENANT_TEXTS.get("blocked:+19055550999")).toBeNull();
    // The tenant text itself is untouched.
    expect(await env.TENANT_TEXTS.get("+18885550100", "json")).toEqual(TENANT_TEXT);
  });

  it("rejects a body without an array of E.164 numbers", async () => {
    for (const body of [{ numbers: "nope" }, { numbers: ["905-555-0101"] }, {}]) {
      const ctx = createExecutionContext();
      const response = await worker.fetch(put(body), envWith(), ctx);
      await waitOnExecutionContext(ctx);
      expect(response.status).toBe(400);
    }
  });
});
