/**
 * Turning a runtime refusal into something a person and a form can both use.
 *
 * Kept free of any Wasp import so the settings form and its tests can read the
 * same rules the server writes them with.
 */

export type FieldError = {
  /** The path inside the tenant configuration, e.g. `["hours"]`. */
  path: string[];
  /** The first segment, which is what a settings tab is keyed by. */
  field: string;
  message: string;
};

type Detail = { loc?: unknown; msg?: unknown };

/**
 * `PUT /internal/tenants/{id}/config` answers an invalid configuration with
 * `422 {"detail": [{"loc": ["config", "hours"], "msg": …}]}`. The leading
 * `config` is the request body's own name, not a field of the configuration,
 * so it is dropped; `body` is dropped for the same reason.
 */
export function fieldErrorsFrom(body: unknown): FieldError[] {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) {
    return [];
  }
  return detail.flatMap((entry: Detail) => {
    if (!Array.isArray(entry?.loc)) {
      return [];
    }
    const path = entry.loc
      .map((part) => String(part))
      .filter((part, index) => !(index === 0 && (part === "config" || part === "body")));
    return [
      {
        path,
        field: path[0] ?? "",
        message: String(entry.msg ?? "This value was refused."),
      },
    ];
  });
}

/** A one-line summary for the top of a form. */
export function summariseFieldErrors(errors: FieldError[]): string {
  if (errors.length === 0) {
    return "The front desk service refused this change.";
  }
  return errors
    .map((error) => `${error.path.join(" → ") || "configuration"}: ${error.message}`)
    .join("; ");
}

/**
 * What a person is told when the runtime does not answer, or answers badly.
 * Never the status line, never a stack, and never anything about the key.
 */
export function friendlyRuntimeMessage(status: number | null, what: string): string {
  switch (status) {
    case 401:
    case 403:
      return `The portal is not allowed to read ${what} from the front desk service. The agency has been told.`;
    case 404:
      return `The front desk service has no ${what}.`;
    case 422:
      return `The front desk service refused this ${what}.`;
    case null:
      return `The front desk service is not answering, so ${what} cannot be shown right now.`;
    default:
      return `The front desk service could not return ${what} right now.`;
  }
}
