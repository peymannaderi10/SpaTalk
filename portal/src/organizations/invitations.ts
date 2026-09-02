/**
 * Invitation rules, kept free of Prisma and of Wasp so they can be reasoned
 * about (and unit tested) on their own. An invitation is single use and lives
 * for seven days.
 */

export const INVITATION_LIFETIME_DAYS = 7;

const MS_PER_DAY = 24 * 60 * 60 * 1000;

export type InvitationStatus = "pending" | "accepted" | "expired";

export function invitationExpiryFrom(now: Date): Date {
  return new Date(now.getTime() + INVITATION_LIFETIME_DAYS * MS_PER_DAY);
}

export function invitationStatus(
  invitation: { expiresAt: Date; acceptedAt: Date | null },
  now: Date,
): InvitationStatus {
  if (invitation.acceptedAt !== null) {
    return "accepted";
  }
  if (invitation.expiresAt.getTime() <= now.getTime()) {
    return "expired";
  }
  return "pending";
}

/** Email addresses are compared case-insensitively and without stray space. */
export function normaliseEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function isInvitedAddress(
  invitedEmail: string,
  address: string | null | undefined,
): boolean {
  if (!address) {
    return false;
  }
  return normaliseEmail(invitedEmail) === normaliseEmail(address);
}
