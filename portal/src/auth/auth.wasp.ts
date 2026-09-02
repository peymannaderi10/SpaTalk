import {
  page,
  route,
  type Auth,
  type AuthMethods,
  type Spec,
} from "@wasp.sh/spec";

import { LoginPage } from "./LoginPage" with { type: "ref" };
import { SignupPage } from "./SignupPage" with { type: "ref" };
import { EmailVerificationPage } from "./email-and-pass/EmailVerificationPage" with { type: "ref" };
import { PasswordResetPage } from "./email-and-pass/PasswordResetPage" with { type: "ref" };
import { RequestPasswordResetPage } from "./email-and-pass/RequestPasswordResetPage" with { type: "ref" };
import {
  getPasswordResetEmailContent,
  getVerificationEmailContent,
} from "./email-and-pass/emails" with { type: "ref" };
import {
  getEmailUserFields,
  getGoogleAuthConfig,
  getGoogleUserFields,
} from "./userSignupFields" with { type: "ref" };

import { MAIL_FROM_EMAIL, MAIL_FROM_NAME } from "../server/mailFrom";

const emailAuthMethod: NonNullable<AuthMethods["email"]> = {
  fromField: {
    name: MAIL_FROM_NAME,
    email: MAIL_FROM_EMAIL,
  },
  emailVerification: {
    clientRoute: "EmailVerificationRoute",
    getEmailContentFn: getVerificationEmailContent,
  },
  passwordReset: {
    clientRoute: "PasswordResetRoute",
    getEmailContentFn: getPasswordResetEmailContent,
  },
  userSignupFields: getEmailUserFields,
};

const googleAuthMethod: NonNullable<AuthMethods["google"]> = {
  userSignupFields: getGoogleUserFields,
  configFn: getGoogleAuthConfig,
};

/**
 * Google sign-in stays wired but is only compiled into the app when both
 * halves of the credential are present, so a deploy without a Google project
 * does not fail at server start.
 */
const isGoogleAuthConfigured = Boolean(
  process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET,
);

export const authConfig: Auth = {
  userEntity: "User",
  methods: {
    email: emailAuthMethod,
    ...(isGoogleAuthConfigured ? { google: googleAuthMethod } : {}),
  },
  onAuthFailedRedirectTo: "/login",
  onAuthSucceededRedirectTo: "/app",
};

export const authSpec: Spec = [
  route("LoginRoute", "/login", page(LoginPage)),
  route("SignupRoute", "/signup", page(SignupPage)),
  route(
    "RequestPasswordResetRoute",
    "/request-password-reset",
    page(RequestPasswordResetPage),
  ),
  route("PasswordResetRoute", "/password-reset", page(PasswordResetPage)),
  route(
    "EmailVerificationRoute",
    "/email-verification",
    page(EmailVerificationPage),
  ),
];
