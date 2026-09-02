import { describe, expect, it } from "vitest";

import { verifyTelnyxSignature } from "../src/telnyx-signature";
import { makeTelnyxKey, messageReceivedEvent, nowSeconds } from "./helpers";

describe("verifyTelnyxSignature", () => {
  it("accepts a signature the telnyx account key made over timestamp|body", async () => {
    const key = await makeTelnyxKey();
    const body = messageReceivedEvent();
    const timestamp = String(nowSeconds());
    const signature = await key.sign(body, timestamp);

    expect(await verifyTelnyxSignature(body, signature, timestamp, key.publicKeyB64, 300)).toBe(
      true,
    );
  });

  it("rejects a signature made over a different body", async () => {
    const key = await makeTelnyxKey();
    const timestamp = String(nowSeconds());
    const signature = await key.sign(messageReceivedEvent({ text: "original" }), timestamp);

    const tampered = messageReceivedEvent({ text: "tampered" });
    expect(await verifyTelnyxSignature(tampered, signature, timestamp, key.publicKeyB64, 300)).toBe(
      false,
    );
  });

  it("rejects a signature made under a different timestamp", async () => {
    const key = await makeTelnyxKey();
    const body = messageReceivedEvent();
    const timestamp = String(nowSeconds());
    const signature = await key.sign(body, timestamp);

    const replayed = String(nowSeconds() - 10);
    expect(await verifyTelnyxSignature(body, signature, replayed, key.publicKeyB64, 300)).toBe(
      false,
    );
  });

  it("rejects a timestamp outside the 300 second tolerance", async () => {
    const key = await makeTelnyxKey();
    const body = messageReceivedEvent();
    const stale = String(nowSeconds() - 301);
    const signature = await key.sign(body, stale);

    expect(await verifyTelnyxSignature(body, signature, stale, key.publicKeyB64, 300)).toBe(false);
    expect(await verifyTelnyxSignature(body, signature, stale, key.publicKeyB64, 3600)).toBe(true);
  });

  it("rejects a signature from another key pair", async () => {
    const key = await makeTelnyxKey();
    const other = await makeTelnyxKey();
    const body = messageReceivedEvent();
    const timestamp = String(nowSeconds());
    const signature = await key.sign(body, timestamp);

    expect(await verifyTelnyxSignature(body, signature, timestamp, other.publicKeyB64, 300)).toBe(
      false,
    );
  });

  it("rejects a missing header, a non-numeric timestamp or an unconfigured public key", async () => {
    const key = await makeTelnyxKey();
    const body = messageReceivedEvent();
    const timestamp = String(nowSeconds());
    const signature = await key.sign(body, timestamp);

    expect(await verifyTelnyxSignature(body, null, timestamp, key.publicKeyB64, 300)).toBe(false);
    expect(await verifyTelnyxSignature(body, signature, null, key.publicKeyB64, 300)).toBe(false);
    expect(await verifyTelnyxSignature(body, signature, "not-a-number", key.publicKeyB64, 300)).toBe(
      false,
    );
    expect(await verifyTelnyxSignature(body, signature, timestamp, "", 300)).toBe(false);
  });

  it("rejects malformed base64 instead of throwing", async () => {
    const key = await makeTelnyxKey();
    const body = messageReceivedEvent();
    const timestamp = String(nowSeconds());

    expect(await verifyTelnyxSignature(body, "!!!not-base64!!!", timestamp, key.publicKeyB64, 300))
      .toBe(false);
    expect(
      await verifyTelnyxSignature(body, await key.sign(body, timestamp), timestamp, "short", 300),
    ).toBe(false);
  });
});
