import { randomBytes } from "crypto";
import { type Invitation, type Organization } from "wasp/entities";
import { config, HttpError } from "wasp/server";
import { emailSender } from "wasp/server/email";
import {
  type AcceptInvitation,
  type CreateOrganization,
  type GetInvitation,
  type GetOrganization,
  type InviteMember,
  type ListMyOrganizations,
  type RemoveMember,
} from "wasp/server/operations";
import * as z from "zod";
import { BRAND } from "../client/brand";
import { organizationIsEntitled } from "../payment/entitlement";
import { ensureArgsSchemaOrThrowHttpError } from "../server/validation";
import {
  requireAdmin,
  requireOrgAccessBySlug,
  requireOrgOwner,
  requireUser,
} from "./access";
import { type OrgRole } from "./roles";
import {
  invitationExpiryFrom,
  invitationStatus,
  isInvitedAddress,
  normaliseEmail,
  type InvitationStatus,
} from "./invitations";

const roleSchema = z.enum(["OWNER", "STAFF"]);

const slugSchema = z
  .string()
  .min(2)
  .max(64)
  .regex(
    /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
    "A slug is lowercase letters, digits and single hyphens.",
  );

export type OrganizationSummary = {
  id: string;
  name: string;
  slug: string;
  runtimeTenantId: string;
  subscriptionStatus: string | null;
  /** Whether Stripe has ever billed this organisation. */
  hasStripeCustomer: boolean;
  /**
   * Whether *this viewer* may open the pages that need a subscription (portal
   * plan, Task C6). The server settles it here so the page and the operations
   * cannot disagree about who is let in.
   */
  entitled: boolean;
  role: OrgRole;
  isMember: boolean;
};

export type MemberView = {
  userId: string;
  email: string | null;
  role: OrgRole;
  joinedAt: Date;
};

export type InvitationView = {
  id: string;
  email: string;
  role: OrgRole;
  expiresAt: Date;
  status: InvitationStatus;
  inviteUrl: string;
};

export type OrganizationView = OrganizationSummary & {
  members: MemberView[];
  /** Only an owner (or an agency admin) is shown the pending invitations. */
  invitations: InvitationView[] | null;
};

export type InvitationSummary = {
  email: string;
  role: OrgRole;
  organizationName: string;
  status: InvitationStatus;
};

export type AcceptedInvitation = {
  organizationName: string;
  organizationSlug: string;
  role: OrgRole;
};

function inviteUrlFor(token: string): string {
  return `${config.frontendUrl.replace(/\/$/, "")}/invite/${token}`;
}

function newInvitationToken(): string {
  return randomBytes(32).toString("base64url");
}

function toInvitationView(invitation: Invitation, now: Date): InvitationView {
  return {
    id: invitation.id,
    email: invitation.email,
    role: invitation.role,
    expiresAt: invitation.expiresAt,
    status: invitationStatus(invitation, now),
    inviteUrl: inviteUrlFor(invitation.token),
  };
}

// --- creating an organisation ---------------------------------------------

const createOrganizationSchema = z.object({
  name: z.string().trim().min(2).max(120),
  slug: slugSchema,
  runtimeTenantId: slugSchema,
});

/**
 * Only the agency creates organisations: a client never signs itself up,
 * because an organisation means nothing until a runtime tenant exists.
 */
export const createOrganization: CreateOrganization<
  z.infer<typeof createOrganizationSchema>,
  Organization
> = async (rawArgs, context) => {
  requireAdmin(context);
  const args = ensureArgsSchemaOrThrowHttpError(
    createOrganizationSchema,
    rawArgs,
  );

  const clash = await context.entities.Organization.findFirst({
    where: {
      OR: [{ slug: args.slug }, { runtimeTenantId: args.runtimeTenantId }],
    },
  });
  if (clash) {
    throw new HttpError(
      409,
      "An organisation with that slug or runtime tenant already exists.",
    );
  }

  return context.entities.Organization.create({
    data: {
      name: args.name,
      slug: args.slug,
      runtimeTenantId: args.runtimeTenantId,
    },
  });
};

// --- the organisations I can open -----------------------------------------

export const listMyOrganizations: ListMyOrganizations<
  void,
  OrganizationSummary[]
> = async (_args, context) => {
  const user = requireUser(context);

  const memberships = await context.entities.Membership.findMany({
    where: { userId: user.id },
    include: { organization: true },
    orderBy: { createdAt: "asc" },
  });

  const mine = new Map<string, OrganizationSummary>(
    memberships.map((membership) => [
      membership.organizationId,
      {
        id: membership.organization.id,
        name: membership.organization.name,
        slug: membership.organization.slug,
        runtimeTenantId: membership.organization.runtimeTenantId,
        subscriptionStatus: membership.organization.subscriptionStatus,
        hasStripeCustomer: membership.organization.stripeCustomerId !== null,
        entitled: organizationIsEntitled({
          subscriptionStatus: membership.organization.subscriptionStatus,
          viewerIsAgencyAdmin: user.isAdmin,
        }),
        role: membership.role,
        isMember: true,
      },
    ]),
  );

  if (!user.isAdmin) {
    return [...mine.values()];
  }

  // An agency admin bypasses membership, so every organisation is theirs to
  // open. The ones they are a member of keep their real role.
  const all = await context.entities.Organization.findMany({
    orderBy: { name: "asc" },
  });

  return all.map(
    (org) =>
      mine.get(org.id) ?? {
        id: org.id,
        name: org.name,
        slug: org.slug,
        runtimeTenantId: org.runtimeTenantId,
        subscriptionStatus: org.subscriptionStatus,
        hasStripeCustomer: org.stripeCustomerId !== null,
        entitled: organizationIsEntitled({
          subscriptionStatus: org.subscriptionStatus,
          viewerIsAgencyAdmin: user.isAdmin,
        }),
        role: "OWNER" as const,
        isMember: false,
      },
  );
};

// --- one organisation, with its people ------------------------------------

const getOrganizationSchema = z.object({ slug: slugSchema });

export const getOrganization: GetOrganization<
  z.infer<typeof getOrganizationSchema>,
  OrganizationView
> = async (rawArgs, context) => {
  const { slug } = ensureArgsSchemaOrThrowHttpError(
    getOrganizationSchema,
    rawArgs,
  );
  const { org, role } = await requireOrgAccessBySlug(context, slug);

  const memberships = await context.entities.Membership.findMany({
    where: { organizationId: org.id },
    include: { user: true },
    orderBy: { createdAt: "asc" },
  });

  const members: MemberView[] = memberships.map((membership) => ({
    userId: membership.userId,
    email: membership.user.email,
    role: membership.role,
    joinedAt: membership.createdAt,
  }));

  let invitations: InvitationView[] | null = null;
  if (role === "OWNER") {
    const now = new Date();
    const rows = await context.entities.Invitation.findMany({
      where: { organizationId: org.id, acceptedAt: null },
      orderBy: { createdAt: "desc" },
    });
    invitations = rows.map((invitation) => toInvitationView(invitation, now));
  }

  return {
    id: org.id,
    name: org.name,
    slug: org.slug,
    runtimeTenantId: org.runtimeTenantId,
    subscriptionStatus: org.subscriptionStatus,
    hasStripeCustomer: org.stripeCustomerId !== null,
    entitled: organizationIsEntitled({
      subscriptionStatus: org.subscriptionStatus,
      viewerIsAgencyAdmin: context.user?.isAdmin === true,
    }),
    role,
    isMember: members.some((member) => member.userId === context.user?.id),
    members,
    invitations,
  };
};

// --- invitations -----------------------------------------------------------

const inviteMemberSchema = z.object({
  organizationId: z.string().min(1),
  email: z.string().trim().toLowerCase().pipe(z.email()),
  role: roleSchema,
});

export const inviteMember: InviteMember<
  z.infer<typeof inviteMemberSchema>,
  InvitationView
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(inviteMemberSchema, rawArgs);
  const { org } = await requireOrgOwner(context, args.organizationId);

  return createAndSendInvitation({
    entities: context.entities,
    org,
    email: args.email,
    role: args.role,
  });
};

type InvitationEntities = {
  Membership: {
    findFirst(args: unknown): Promise<{ id: string } | null>;
  };
  Invitation: {
    findFirst(args: unknown): Promise<Invitation | null>;
    create(args: { data: Record<string, unknown> }): Promise<Invitation>;
  };
};

/**
 * The one place an invitation is minted: single use, seven days, emailed, and
 * returned with the link so whoever asked for it can hand it over. The
 * onboarding wizard invites an owner through this too, so an invitation the
 * agency creates is the same object as one an owner creates.
 *
 * The caller has already decided that this person may invite.
 */
export async function createAndSendInvitation({
  entities,
  org,
  email: rawEmail,
  role,
}: {
  entities: InvitationEntities;
  org: Organization;
  email: string;
  role: OrgRole;
}): Promise<InvitationView> {
  const email = normaliseEmail(rawEmail);
  const now = new Date();

  const alreadyIn = await entities.Membership.findFirst({
    where: { organizationId: org.id, user: { email } },
  });
  if (alreadyIn) {
    throw new HttpError(409, "That person is already in this organisation.");
  }

  const pending = await entities.Invitation.findFirst({
    where: {
      organizationId: org.id,
      email,
      role,
      acceptedAt: null,
      expiresAt: { gt: now },
    },
    orderBy: { createdAt: "desc" },
  });

  const invitation =
    pending ??
    (await entities.Invitation.create({
      data: {
        email,
        role,
        organizationId: org.id,
        token: newInvitationToken(),
        expiresAt: invitationExpiryFrom(now),
      },
    }));

  const view = toInvitationView(invitation, now);
  await sendInvitationEmail({ to: email, org, inviteUrl: view.inviteUrl });

  return view;
}

async function sendInvitationEmail({
  to,
  org,
  inviteUrl,
}: {
  to: string;
  org: Organization;
  inviteUrl: string;
}): Promise<void> {
  await emailSender.send({
    to,
    subject: `You have been invited to ${org.name} on ${BRAND.name}`,
    text:
      `You have been invited to the ${org.name} front desk on ${BRAND.name}.\n\n` +
      `Open this link to accept, signing up first if you do not have an account yet:\n${inviteUrl}\n\n` +
      `The invitation can be used once and expires in seven days.`,
    html: `
        <p>You have been invited to the ${org.name} front desk on ${BRAND.name}.</p>
        <p><a href="${inviteUrl}">Accept the invitation</a></p>
        <p>The invitation can be used once and expires in seven days.</p>
    `,
  });
}

const invitationTokenSchema = z.object({ token: z.string().min(1).max(200) });

/**
 * Public on purpose: someone who has not signed up yet opens the link first
 * and needs to see who invited them, and at which address.
 */
export const getInvitation: GetInvitation<
  z.infer<typeof invitationTokenSchema>,
  InvitationSummary
> = async (rawArgs, context) => {
  const { token } = ensureArgsSchemaOrThrowHttpError(
    invitationTokenSchema,
    rawArgs,
  );

  const invitation = await context.entities.Invitation.findUnique({
    where: { token },
    include: { organization: true },
  });
  if (!invitation) {
    throw new HttpError(404, "This invitation link is not valid.");
  }

  return {
    email: invitation.email,
    role: invitation.role,
    organizationName: invitation.organization.name,
    status: invitationStatus(invitation, new Date()),
  };
};

export const acceptInvitation: AcceptInvitation<
  z.infer<typeof invitationTokenSchema>,
  AcceptedInvitation
> = async (rawArgs, context) => {
  const { token } = ensureArgsSchemaOrThrowHttpError(
    invitationTokenSchema,
    rawArgs,
  );
  const user = requireUser(context);

  const invitation = await context.entities.Invitation.findUnique({
    where: { token },
    include: { organization: true },
  });
  if (!invitation) {
    throw new HttpError(404, "This invitation link is not valid.");
  }

  const status = invitationStatus(invitation, new Date());
  if (status === "accepted") {
    throw new HttpError(410, "This invitation has already been used.");
  }
  if (status === "expired") {
    throw new HttpError(410, "This invitation has expired.");
  }

  if (!isInvitedAddress(invitation.email, context.user?.email)) {
    throw new HttpError(
      403,
      `This invitation was sent to ${invitation.email}. Sign in with that address to accept it.`,
    );
  }

  await context.entities.Membership.upsert({
    where: {
      userId_organizationId: {
        userId: user.id,
        organizationId: invitation.organizationId,
      },
    },
    update: { role: invitation.role },
    create: {
      userId: user.id,
      organizationId: invitation.organizationId,
      role: invitation.role,
    },
  });

  await context.entities.Invitation.update({
    where: { id: invitation.id },
    data: { acceptedAt: new Date() },
  });

  return {
    organizationName: invitation.organization.name,
    organizationSlug: invitation.organization.slug,
    role: invitation.role,
  };
};

// --- removing a member -----------------------------------------------------

const removeMemberSchema = z.object({
  organizationId: z.string().min(1),
  userId: z.string().min(1),
});

export const removeMember: RemoveMember<
  z.infer<typeof removeMemberSchema>,
  { removed: true }
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(removeMemberSchema, rawArgs);
  const { org } = await requireOrgOwner(context, args.organizationId);

  const membership = await context.entities.Membership.findUnique({
    where: {
      userId_organizationId: {
        userId: args.userId,
        organizationId: org.id,
      },
    },
  });
  if (!membership) {
    throw new HttpError(404, "That person is not in this organisation.");
  }

  if (membership.role === "OWNER") {
    const owners = await context.entities.Membership.count({
      where: { organizationId: org.id, role: "OWNER" },
    });
    if (owners <= 1) {
      throw new HttpError(
        409,
        "An organisation keeps at least one owner. Invite another owner first.",
      );
    }
  }

  await context.entities.Membership.delete({
    where: { id: membership.id },
  });

  return { removed: true };
};
