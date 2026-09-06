/**
 * The catalog's keys.
 *
 * `services[].id` is the runtime's closed key: the tool enums the model may
 * name a service by, `items.service_id`, the booking links. It has to exist,
 * and it must never change once a service has one, so the clinic never types
 * it. A new service takes its id from its name, made unique among the
 * tenant's ids, and keeps it from then on.
 */

/** The longest id a service may have. */
export const SERVICE_ID_MAX = 40;

/**
 * A name as an id: lowercase, letters and digits only, words joined by
 * underscores, trimmed, at most `SERVICE_ID_MAX` long. Accents are dropped
 * rather than turned into underscores, so "Café Peel" is `cafe_peel`.
 */
export function slugifyServiceId(name: string): string {
  const words = name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  return trimTo(words.join("_"), SERVICE_ID_MAX);
}

/**
 * The id a new service named `name` gets among the ids already `taken`:
 * the slug itself, or the slug with `_2`, `_3`, … until one is free. The
 * suffix fits inside the limit, so a long name is shortened to make room.
 */
export function uniqueServiceId(name: string, taken: Iterable<string>): string {
  const base = slugifyServiceId(name);
  if (!base) return "";
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const suffix = `_${n}`;
    const candidate = trimTo(base, SERVICE_ID_MAX - suffix.length) + suffix;
    if (!used.has(candidate)) return candidate;
  }
}

function trimTo(id: string, max: number): string {
  return id.slice(0, max).replace(/_+$/, "");
}
