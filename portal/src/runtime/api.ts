import createClient, { type Client } from "openapi-fetch";
import { env, HttpError } from "wasp/server";
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

/**
 * A typed client that presents the shared key and names the person acting, so
 * the runtime can write `portal:<email>` on the audit row itself.
 */
export function runtime(actorEmail?: string | null): RuntimeClient {
  const headers: Record<string, string> = {
    "X-Internal-Key": env.RUNTIME_INTERNAL_KEY,
  };
  if (actorEmail) {
    headers["X-Actor"] = actorEmail;
  }
  return createClient<paths>({
    baseUrl: env.RUNTIME_INTERNAL_URL.replace(/\/$/, ""),
    headers,
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
  const url = `${env.RUNTIME_INTERNAL_URL.replace(/\/$/, "")}/healthz`;
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
  } catch {
    // A connection that never got made: no status, nothing to quote.
    throw new HttpError(502, friendlyRuntimeMessage(null, what));
  }

  const { data, error, response } = answer;
  if (response.ok && error === undefined) {
    return data as T;
  }

  if (response.status === 422) {
    const fieldErrors: FieldError[] = fieldErrorsFrom(error);
    throw new HttpError(422, summariseFieldErrors(fieldErrors), {
      fieldErrors,
    });
  }

  // 401 means our key, not the person's session: never hand that status on.
  const status = response.status === 404 ? 404 : 502;
  throw new HttpError(status, friendlyRuntimeMessage(response.status, what));
}

export { type FieldError };
