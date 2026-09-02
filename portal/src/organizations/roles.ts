/**
 * The two roles inside an organisation, in a module the browser can import:
 * `access.ts` reaches for Wasp's server runtime, which client code may not.
 *
 * OWNER changes settings, billing and who is in the organisation.
 * STAFF sees everything the assistant did and acts on tracked items.
 */
export type OrgRole = "OWNER" | "STAFF";

export const ORG_ROLES: readonly OrgRole[] = ["OWNER", "STAFF"] as const;
