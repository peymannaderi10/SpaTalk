/**
 * Telnyx webhook signatures.
 *
 * Telnyx signs `"{timestamp}|{raw_body}"` with the account's Ed25519 key and sends the
 * signature base64-encoded in `telnyx-signature-ed25519`, with the seconds-since-epoch
 * timestamp in `telnyx-timestamp` (docs/reference/api-surface.md). Nothing here throws:
 * a malformed header, a malformed key or a stale timestamp is a `false`, so the caller
 * has exactly one way to fail.
 */

type EdKeyAlgorithm = { name: string; namedCurve?: string };

/**
 * `Ed25519` is the standard WebCrypto name; `NODE-ED25519` is the legacy name older
 * workerd builds accept. Trying both keeps the worker running on either runtime.
 */
const ED25519_ALGORITHMS: EdKeyAlgorithm[] = [
  { name: "Ed25519" },
  { name: "NODE-ED25519", namedCurve: "NODE-ED25519" },
];

const ED25519_PUBLIC_KEY_BYTES = 32;
const ED25519_SIGNATURE_BYTES = 64;
const INTEGER = /^\d+$/;

/** Decodes standard base64 into bytes; returns null for anything that is not base64. */
export function decodeBase64(value: string): Uint8Array | null {
  try {
    const binary = atob(value.trim());
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

/** Imports a raw base64 Ed25519 public key; returns null if the runtime rejects it. */
export async function importTelnyxPublicKey(publicKeyB64: string): Promise<CryptoKey | null> {
  const raw = decodeBase64(publicKeyB64);
  if (raw === null || raw.byteLength !== ED25519_PUBLIC_KEY_BYTES) return null;
  for (const algorithm of ED25519_ALGORITHMS) {
    try {
      return await crypto.subtle.importKey("raw", raw, algorithm, false, ["verify"]);
    } catch {
      // Try the next spelling of the algorithm.
    }
  }
  return null;
}

/**
 * True only when the signature was made by `publicKeyB64` over `"{timestamp}|{rawBody}"`
 * and the timestamp is within `toleranceSec` of `nowSec`.
 */
export async function verifyTelnyxSignature(
  rawBody: string,
  signatureB64: string | null,
  timestamp: string | null,
  publicKeyB64: string,
  toleranceSec = 300,
  nowSec: number = Math.floor(Date.now() / 1000),
): Promise<boolean> {
  if (!signatureB64 || !timestamp || !publicKeyB64) return false;
  if (!INTEGER.test(timestamp.trim())) return false;
  const sentAt = Number.parseInt(timestamp.trim(), 10);
  if (!Number.isFinite(sentAt) || Math.abs(nowSec - sentAt) > toleranceSec) return false;

  const signature = decodeBase64(signatureB64);
  if (signature === null || signature.byteLength !== ED25519_SIGNATURE_BYTES) return false;

  const key = await importTelnyxPublicKey(publicKeyB64);
  if (key === null) return false;

  const signed = new TextEncoder().encode(`${timestamp}|${rawBody}`);
  try {
    return await crypto.subtle.verify({ name: key.algorithm.name }, key, signature, signed);
  } catch {
    return false;
  }
}
