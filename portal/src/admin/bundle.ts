/**
 * The five-file tenant bundle, as the onboarding wizard handles it.
 *
 * The portal never interprets a bundle: it works out which upload is which
 * file and posts all five to `POST /internal/tenants/from-bundle`, where the
 * runtime's own loader — the one `spatalk tenant import` uses — decides whether
 * it is valid (`docs/reference/tenant-config.md`). A YAML parser in the portal
 * would be a second set of rules to drift.
 */

export type BundleSlot =
  | "tenant"
  | "services"
  | "knowledge"
  | "scripts"
  | "guard";

export type BundleSlotSpec = {
  slot: BundleSlot;
  filename: string;
  /** What the founder is told this file holds. */
  description: string;
};

export const BUNDLE_SLOTS: readonly BundleSlotSpec[] = [
  {
    slot: "tenant",
    filename: "tenant.yaml",
    description: "identity, hours, escalation, delivery, numbers",
  },
  { slot: "services", filename: "services.yaml", description: "the catalogue" },
  {
    slot: "knowledge",
    filename: "knowledge.md",
    description: "prose the assistant may answer from",
  },
  {
    slot: "scripts",
    filename: "scripts.yaml",
    description: "the fixed wording",
  },
  {
    slot: "guard",
    filename: "guard.yaml",
    description: "lexicon additions",
  },
] as const;

/** The text of each file, empty where nothing has been given yet. */
export type BundleDraft = Record<BundleSlot, string>;

export function emptyBundle(): BundleDraft {
  return {
    tenant: "",
    services: "",
    knowledge: "",
    scripts: "",
    guard: "",
  };
}

/**
 * Which bundle file an upload is, by its name alone. Case and the directory it
 * was dragged from do not matter; `.yml` is accepted for `.yaml`. Anything
 * else is refused rather than guessed at, so a stray file never silently
 * becomes a tenant's scripts.
 */
export function slotForFilename(name: string): BundleSlot | null {
  const base = name.split(/[\\/]/).pop()?.trim().toLowerCase() ?? "";
  const normalised = base.replace(/\.yml$/, ".yaml");
  const found = BUNDLE_SLOTS.find((spec) => spec.filename === normalised);
  return found ? found.slot : null;
}

/** The files still needed, in the order the wizard shows them. */
export function missingSlots(draft: Partial<BundleDraft>): BundleSlot[] {
  return BUNDLE_SLOTS.filter(
    (spec) => (draft[spec.slot] ?? "").trim().length === 0,
  ).map((spec) => spec.slot);
}

export function isCompleteBundle(
  draft: Partial<BundleDraft>,
): draft is BundleDraft {
  return missingSlots(draft).length === 0;
}

export function filenameFor(slot: BundleSlot): string {
  return BUNDLE_SLOTS.find((spec) => spec.slot === slot)!.filename;
}
