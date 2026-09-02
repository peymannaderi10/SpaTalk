/**
 * The sender identity is read at compile time because Wasp bakes the email
 * sender and the auth `fromField` into the generated app. Both fall back to a
 * value that is safe in development, where the Dummy provider only prints.
 */
export const MAIL_FROM_EMAIL = process.env.MAIL_FROM ?? "no-reply@spatalk.ca";
export const MAIL_FROM_NAME = process.env.MAIL_FROM_NAME ?? "SpaTalk";
