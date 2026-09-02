import createClient, { type Client } from "openapi-fetch";
import { env, HttpError } from "wasp/server";
import { registerSecret, scrubSecrets } from "../server/security";
import { type paths } from "./client";
import {
  fieldErrorsFrom,
  friendlyRuntimeMessage,
  summariseFieldErrors,
  type FieldError,
} from "./errors";

/**
 * The portal's only way into tenant, conversation, item and usage data.
 *
 * `client.ts` is generated from `docs/contracts/runtime-internal.openapi.json`
 * (`npm run gen:client`); this module is the one place that holds the shared
 * key and the acting user's email. No other file in the portal may fetch the
 * runtime (portal plan, Global Constraints).
 */

export type RuntimeClient = Client<paths>;

type Credentials = { baseUrl: string; key: string };

let credentials: Credentials | null = null;

/**
 * The shared key and the runtime's address, read from the environment once and
 * kept in this closure afterwards (portal plan, Task C7). Registering the key
 * as a secret is what makes it impossible to print: `installLogScrubbing` in
 * `src/server/setup.ts` redacts it from every console line thereafter.
 */
function runtimeCredentials(): Credentials {
  if (credentials === null) {
    const key = env.RUNTIME_INTERNAL_KEY;
    registerSecret(key);
    credentials = {
      baseUrl: env.RUNTIME_INTERNAL_URL.replace(/\/$/, ""),
      key,
    };
  }
  return credentials;
}

/** Only for tests: forgets the cached credentials so the next call re-reads. */
export function __resetRuntimeCredentials(): void {
  credentials = null;
}

/**
 * A typed client that presents the shared key and names the person acting, so
 * the runtime can write `portal:<email>` on the audit row itself.
 *
 * The actor is required. Every read of a transcript and every saved
 * configuration is an audited act, and an audit row that cannot name anybody is
 * not an audit row; a caller that has nobody to name has a bug, and it is
 * refused here rather than recorded as an anonymous act on the runtime.
 */
export function runtime(actorEmail: string): RuntimeClient {
  const actor = typeof actorEmail === "string" ? actorEmail.trim() : "";
  if (actor === "") {
    throw new HttpError(
      500,
      "The portal could not say who is making this change, so it did not make it.",
    );
  }

  const { baseUrl, key } = runtimeCredentials();
  return createClient<paths>({
    baseUrl,
    headers: {
      "X-Internal-Key": key,
      "X-Actor": actor,
    },
  });
}

/**
 * What `GET /healthz` answers. It is the runtime's unauthenticated liveness
 * endpoint and therefore not part of the `/internal` contract the typed client
 * is generated from, so its shape is written out here — the one thing in the
 * portal that reaches the runtime without going through `client.ts`, and it
 * stays inside this module (portal plan, Global Constraints).
 */
export type RuntimeStatus = {
  ok: boolean;
  tenants: string[];
  config_versions: Record<string, number>;
  commit: string;
};

export async function runtimeHealthz(): Promise<RuntimeStatus> {
  const url = `${runtimeCredentials().baseUrl}/healthz`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    throw new HttpError(
      502,
      friendlyRuntimeMessage(null, "the service status"),
    );
  }
  if (!response.ok) {
    throw new HttpError(
      502,
      friendlyRuntimeMessage(response.status, "the service status"),
    );
  }
  return (await response.json()) as RuntimeStatus;
}

/**
 * The five bundle files as a multipart body. `openapi-fetch` serialises JSON by
 * default; `POST /internal/tenants/from-bundle` wants file parts, and FastAPI
 * only treats a part as a file when it carries a filename.
 */
export function bundleFormData(
  parts: Record<string, string>,
  filenames: Record<string, string>,
): FormData {
  const form = new FormData();
  for (const [name, value] of Object.entries(parts)) {
    const filename = filenames[name];
    if (filename) {
      form.append(name, new Blob([value], { type: "text/plain" }), filename);
    } else {
      form.append(name, value);
    }
  }
  return form;
}

type Answer<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

/**
 * Unwraps one call. A refusal becomes an `HttpError` a page can show: the
 * status the person's browser should see, a sentence in plain words, and, for
 * a refused configuration, the fields that were wrong. The key is never in it,
 * and neither is the runtime's own error text for anything but a 422.
 */
export async function runtimeCall<T>(
  call: () => Promise<Answer<T>>,
  what: string,
): Promise<T> {
  let answer: Answer<T>;
  try {
    answer = await call();
  } catch (caught) {
    // A connection that never got made: no status, nothing to quote.
    logRuntimeFailure(what, null, caught);
    throw new HttpError(502, friendlyRuntimeMessage(null, what));
  }

  const { data, error, response } = answer;
  if (response.ok && error === undefined) {
    return data as T;
  }

  if (response.status === 422) {
    // Not a failure of the service: the person's own input was refused, and the
    // fields are theirs to see. Nothing to log.
    const fieldErrors: FieldError[] = fieldErrorsFrom(error);
    throw new HttpError(422, summariseFieldErrors(fieldErrors), {
      fieldErrors,
    });
  }

  logRuntimeFailure(what, response.status, error);

  // 401 means our key, not the person's session: never hand that status on.
  const status = response.status === 404 ? 404 : 502;
  throw new HttpError(status, friendlyRuntimeMessage(response.status, what));
}

/**
 * One line an operator can act on: what was being read and what came back. The
 * cause is scrubbed before it is printed, so a key that found its way into an
 * error message or a request dump never survives the trip to the log.
 */
function logRuntimeFailure(
  what: string,
  status: number | null,
  cause: unknown,
): void {
  const outcome = status === null ? "no answer" : `status ${status}`;
  const detail = renderCause(cause);
  console.error(
    scrubSecrets(
      `The front desk service failed on ${what}: ${outcome}${detail ? ` (${detail})` : ""}`,
    ),
  );
}

function renderCause(cause: unknown): string {
  if (cause === undefined || cause === null) {
    return "";
  }
  if (cause instanceof Error) {
    return cause.message;
  }
  if (typeof cause === "string") {
    return cause;
  }
  try {
    return (JSON.stringify(cause) ?? "").slice(0, 500);
  } catch {
    return "";
  }
}

export { type FieldError };
