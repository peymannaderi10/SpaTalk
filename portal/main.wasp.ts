import { app, page, route } from "@wasp.sh/spec";

import { App } from "./src/client/App" with { type: "ref" };
import { NotFoundPage } from "./src/client/components/NotFoundPage" with { type: "ref" };
import { RootRedirectPage } from "./src/client/RootRedirectPage" with { type: "ref" };
import { AppPage } from "./src/client/AppPage" with { type: "ref" };
import { PrivacyPage } from "./src/legal/PrivacyPage" with { type: "ref" };
import { serverEnvValidationSchema } from "./src/env" with { type: "ref" };

import { adminSpec } from "./src/admin/admin.wasp";
import { analyticsSpec } from "./src/analytics/analytics.wasp";
import { authConfig, authSpec } from "./src/auth/auth.wasp";
import { head } from "./src/client/head.wasp";
import { paymentSpec } from "./src/payment/payment.wasp";
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
    paymentSpec,
    analyticsSpec,
    adminSpec,
  ],
});
