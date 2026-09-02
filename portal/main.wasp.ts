import { app, page, route } from "@wasp.sh/spec";

import { App } from "./src/client/App" with { type: "ref" };
import { NotFoundPage } from "./src/client/components/NotFoundPage" with { type: "ref" };
import { RootRedirectPage } from "./src/client/RootRedirectPage" with { type: "ref" };
import { AppPage } from "./src/client/AppPage" with { type: "ref" };
import { PrivacyPage } from "./src/legal/PrivacyPage" with { type: "ref" };
import { serverEnvValidationSchema } from "./src/env" with { type: "ref" };
import { portalMiddleware } from "./src/server/security" with { type: "ref" };
import { serverSetup } from "./src/server/setup" with { type: "ref" };

import { adminSpec } from "./src/admin/admin.wasp";
import { analyticsSpec } from "./src/analytics/analytics.wasp";
import { authConfig, authSpec } from "./src/auth/auth.wasp";
import { clientPagesSpec } from "./src/client/pages.wasp";
import { head } from "./src/client/head.wasp";
import { paymentSpec } from "./src/payment/payment.wasp";
import { organizationsSpec } from "./src/organizations/organizations.wasp";
import { emailSender } from "./src/server/emailSender.wasp";
import { userSpec } from "./src/user/user.wasp";

export default app({
  name: "SpaTalkPortal",
  wasp: { version: "^0.25.0" },
  title: "SpaTalk",
  head,
  auth: authConfig,
  client: {
    rootComponent: App,
  },
  server: {
    // Secrets registered and the console wrapped so none can be printed; the
    // proxy peers whose forwarded-for header may be believed.
    setupFn: serverSetup,
    // The security headers on every response and the rate limit in front of
    // login, signup and the invitation endpoints.
    middlewareConfigFn: portalMiddleware,
    envValidationSchema: serverEnvValidationSchema,
  },
  emailSender,
  spec: [
    route("RootRoute", "/", page(RootRedirectPage)),
    route("AppRoute", "/app", page(AppPage, { authRequired: true })),
    route("PrivacyRoute", "/privacy", page(PrivacyPage), { prerender: true }),
    route("NotFoundRoute", "*", page(NotFoundPage)),
    authSpec,
    userSpec,
    organizationsSpec,
    clientPagesSpec,
    paymentSpec,
    analyticsSpec,
    adminSpec,
  ],
});
