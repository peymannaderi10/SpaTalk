/** Test helpers: Ed25519 key pairs, Telnyx payloads, and an outbound fetch stub. */
import { vi } from "vitest";

type EdKeyAlgorithm = { name: string; namedCurve?: string };

const ED25519_ALGORITHMS: EdKeyAlgorithm[] = [
  { name: "Ed25519" },
  { name: "NODE-ED25519", namedCurve: "NODE-ED25519" },
];

export function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export interface TelnyxTestKey {
  publicKeyB64: string;
  sign(rawBody: string, timestamp: string): Promise<string>;
}

/** A throwaway Ed25519 key pair standing in for the Telnyx account key. */
export async function makeTelnyxKey(): Promise<TelnyxTestKey> {
  let pair: CryptoKeyPair | null = null;
  let lastError: unknown = null;
  for (const algorithm of ED25519_ALGORITHMS) {
    try {
      pair = (await crypto.subtle.generateKey(algorithm, true, [
        "sign",
        "verify",
      ])) as CryptoKeyPair;
      break;
    } catch (error) {
      lastError = error;
    }
  }
  if (pair === null) throw lastError ?? new Error("no Ed25519 implementation available");
  const keyPair = pair;
  const exported = (await crypto.subtle.exportKey("raw", keyPair.publicKey)) as ArrayBuffer;
  const raw = new Uint8Array(exported);
  return {
    publicKeyB64: toBase64(raw),
    async sign(rawBody: string, timestamp: string): Promise<string> {
      const signature = await crypto.subtle.sign(
        { name: keyPair.privateKey.algorithm.name },
        keyPair.privateKey,
        new TextEncoder().encode(`${timestamp}|${rawBody}`),
      );
      return toBase64(new Uint8Array(signature));
    },
  };
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export interface MessageEventOptions {
  messageId?: string;
  from?: string;
  to?: string;
  text?: string;
  eventType?: string;
}

/** The shape docs/reference/api-surface.md pins for the Telnyx messaging webhook. */
export function messageReceivedEvent(options: MessageEventOptions = {}): string {
  const {
    messageId = "msg-uuid",
    from = "+19055550101",
    to = "+18885550100",
    text = "How much is a facial?",
    eventType = "message.received",
  } = options;
  return JSON.stringify({
    data: {
      event_type: eventType,
      id: "evt-uuid",
      occurred_at: "2026-09-02T14:00:00.000Z",
      payload: {
        id: messageId,
        direction: "inbound",
        type: "SMS",
        text,
        from: { phone_number: from, carrier: "Rogers", line_type: "Wireless" },
        to: [{ phone_number: to, status: "webhook_delivered" }],
        received_at: "2026-09-02T14:00:00.000Z",
        messaging_profile_id: "mp-uuid",
      },
    },
  });
}

export interface SignedRequestOptions extends MessageEventOptions {
  key: TelnyxTestKey;
  body?: string;
  timestamp?: string;
  url?: string;
}

export async function signedSmsRequest(options: SignedRequestOptions): Promise<Request> {
  const body = options.body ?? messageReceivedEvent(options);
  const timestamp = options.timestamp ?? String(nowSeconds());
  const signature = await options.key.sign(body, timestamp);
  return new Request(options.url ?? "https://edge.test/telnyx/sms", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "telnyx-signature-ed25519": signature,
      "telnyx-timestamp": timestamp,
    },
    body,
  });
}

export interface FetchCall {
  key: string;
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string;
}

export type FetchRoute = (call: FetchCall) => Response | Promise<Response>;

/**
 * Replaces the global `fetch` for one test. Every outbound call is recorded; a call
 * to a route that was not declared throws, the way `disableNetConnect` would.
 */
export function stubFetch(routes: Record<string, FetchRoute>): FetchCall[] {
  const calls: FetchCall[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = new Request(input as RequestInfo, init);
    const url = new URL(request.url);
    const headers: Record<string, string> = {};
    request.headers.forEach((value, name) => {
      headers[name.toLowerCase()] = value;
    });
    const call: FetchCall = {
      key: `${request.method} ${url.origin}${url.pathname}`,
      url: request.url,
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? "" : await request.text(),
    };
    calls.push(call);
    const route = routes[call.key];
    if (route === undefined) throw new Error(`unexpected outbound fetch: ${call.key}`);
    return route(call);
  });
  return calls;
}

export function jsonResponse(status: number, body: unknown = { ok: true }): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function textResponse(status: number, body: string): Response {
  return new Response(body, { status });
}

export function callsTo(calls: FetchCall[], key: string): FetchCall[] {
  return calls.filter((call) => call.key === key);
}
