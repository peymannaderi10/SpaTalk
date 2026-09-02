import { type EmailSender } from "@wasp.sh/spec";

import { MAIL_FROM_EMAIL, MAIL_FROM_NAME } from "./mailFrom";

/**
 * Wasp bakes the email provider into the generated app, so the choice is made
 * at compile time. The default is SMTP, which production points at Amazon SES.
 * Set `PORTAL_EMAIL_PROVIDER=Dummy` before `wasp start` or `wasp build` to get
 * Wasp's Dummy provider, which prints the message, including the email
 * verification link, to the server log instead of sending it. Development and
 * the end-to-end tests read that log.
 */
const provider: EmailSender["provider"] =
  process.env.PORTAL_EMAIL_PROVIDER === "Dummy" ? "Dummy" : "SMTP";

export const emailSender: EmailSender = {
  provider,
  defaultFrom: {
    name: MAIL_FROM_NAME,
    email: MAIL_FROM_EMAIL,
  },
};
