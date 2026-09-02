import { type Organization } from "wasp/entities";
import { HttpError } from "wasp/server";
import { type OrgRole } from "./roles";

/**
 * Every server operation that takes an organisation goes through here first.
 * An agency admin (`User.isAdmin`) bypasses membership and acts as an OWNER;
 * everybody else needs a Membership row.
 */

export { type OrgRole };

export type OrgAccess = {
  org: Organization;
  role: OrgRole;
};

type OrgUser = {
  id: string;
  isAdmin: boolean;
};

type MembershipDelegate = {
  findUnique(args: {
    where: {
      userId_organizationId: { userId: string; organizationId: string };
    };
  }): Promise<{ role: OrgRole } | null>;
};

export type OrgAccessContext = {
  user?: OrgUser | null;
  entities: {
    Organization: {
      findUnique(args: { where: { id: string } }): Promise<Organization | null>;
    };
    Membership: MembershipDelegate;
  };
};

export type OrgSlugAccessContext = {
  user?: OrgUser | null;
  entities: {
    Organization: {
      findUnique(args: {
        where: { slug: string };
      }): Promise<Organization | null>;
    };
    Membership: MembershipDelegate;
  };
};

export type AuthenticatedContext = {
  user?: OrgUser | null;
};

export function requireUser(context: AuthenticatedContext): OrgUser {
  if (!context.user) {
    throw new HttpError(401, "You must be signed in.");
  }
  return context.user;
}

export function requireAdmin(context: AuthenticatedContext): OrgUser {
  const user = requireUser(context);
  if (!user.isAdmin) {
    throw new HttpError(403, "Only an agency admin can do this.");
  }
  return user;
}

export async function requireOrgAccess(
  context: OrgAccessContext,
  organizationId: string,
): Promise<OrgAccess> {
  const user = requireUser(context);
  const org = await context.entities.Organization.findUnique({
    where: { id: organizationId },
  });
  return accessTo(user, org, context.entities.Membership);
}

export async function requireOrgAccessBySlug(
  context: OrgSlugAccessContext,
  slug: string,
): Promise<OrgAccess> {
  const user = requireUser(context);
  const org = await context.entities.Organization.findUnique({
    where: { slug },
  });
  return accessTo(user, org, context.entities.Membership);
}

/** Access plus the OWNER powers: settings, billing, and who is in the org. */
export async function requireOrgOwner(
  context: OrgAccessContext,
  organizationId: string,
): Promise<OrgAccess> {
  return asOwner(await requireOrgAccess(context, organizationId));
}

export async function requireOrgOwnerBySlug(
  context: OrgSlugAccessContext,
  slug: string,
): Promise<OrgAccess> {
  return asOwner(await requireOrgAccessBySlug(context, slug));
}

function asOwner(access: OrgAccess): OrgAccess {
  if (access.role !== "OWNER") {
    throw new HttpError(403, "Only an owner of this organisation can do this.");
  }
  return access;
}

async function accessTo(
  user: OrgUser,
  org: Organization | null,
  memberships: MembershipDelegate,
): Promise<OrgAccess> {
  if (!org) {
    throw new HttpError(404, "No such organisation.");
  }

  if (user.isAdmin) {
    return { org, role: "OWNER" };
  }

  const membership = await memberships.findUnique({
    where: {
      userId_organizationId: { userId: user.id, organizationId: org.id },
    },
  });

  if (!membership) {
    throw new HttpError(403, "You are not a member of this organisation.");
  }

  return { org, role: membership.role };
}
