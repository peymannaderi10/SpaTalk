/**
 * Where signing in lands.
 *
 * People who use this portal work for one business. `/app` — the route Wasp
 * sends them to after authentication — is therefore not a page to read but a
 * decision to make: an agency admin belongs on the platform's own dashboard,
 * a person who belongs to one organisation belongs in it, and only the person
 * an admin has added to several has anything to choose between.
 *
 * The decision lives here, as a function of what is known and nothing else, so
 * `entry.test.ts` can state all four outcomes without a browser and `AppPage`
 * only has to act on the answer.
 */

/** The one field the decision needs from an organisation. */
export type EntryOrganization = { slug: string };

export type EntryDestination =
  /** Go here instead; `/app` is not a place to stay. */
  | { kind: "redirect"; to: string }
  /** This person is in no organisation: say so, and say who invites them. */
  | { kind: "none" }
  /** Several organisations, so only they can say which one they meant. */
  | { kind: "choose" };

/** The agency's own dashboard. */
export const PLATFORM_HOME = "/admin";

/** One business's home, from its slug. The one place this path is written. */
export function orgHomePath(slug: string): string {
  return `/app/${encodeURIComponent(slug)}`;
}

export function entryDestination({
  isAdmin,
  organizations,
}: {
  isAdmin: boolean;
  organizations: readonly EntryOrganization[];
}): EntryDestination {
  // An admin is a member of client organisations as a matter of course — it is
  // how they open a client's pages — so being in one says nothing about where
  // their own work is. The platform is.
  if (isAdmin) {
    return { kind: "redirect", to: PLATFORM_HOME };
  }
  if (organizations.length === 0) {
    return { kind: "none" };
  }
  if (organizations.length === 1) {
    return { kind: "redirect", to: orgHomePath(organizations[0].slug) };
  }
  return { kind: "choose" };
}
