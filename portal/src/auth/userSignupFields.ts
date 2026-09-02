import { defineUserSignupFields } from "wasp/auth/providers/types";
import { env } from "wasp/server";
import { z } from "zod";

function isAdminEmail(email: string): boolean {
  return env.ADMIN_EMAILS.includes(email);
}

const emailDataSchema = z.object({
  email: z.string(),
});

export const getEmailUserFields = defineUserSignupFields({
  email: (data) => {
    const emailData = emailDataSchema.parse(data);
    return emailData.email;
  },
  username: (data) => {
    const emailData = emailDataSchema.parse(data);
    return emailData.email;
  },
  isAdmin: (data) => {
    const emailData = emailDataSchema.parse(data);
    return isAdminEmail(emailData.email);
  },
});

const googleDataSchema = z.object({
  profile: z.object({
    email: z.string(),
    email_verified: z.boolean(),
  }),
});

export const getGoogleUserFields = defineUserSignupFields({
  email: (data) => {
    const googleData = googleDataSchema.parse(data);
    return googleData.profile.email;
  },
  username: (data) => {
    const googleData = googleDataSchema.parse(data);
    return googleData.profile.email;
  },
  isAdmin: (data) => {
    const googleData = googleDataSchema.parse(data);
    if (!googleData.profile.email_verified) {
      return false;
    }
    return isAdminEmail(googleData.profile.email);
  },
});

export function getGoogleAuthConfig() {
  return {
    scopes: ["profile", "email"], // must include at least 'profile' for Google
  };
}
