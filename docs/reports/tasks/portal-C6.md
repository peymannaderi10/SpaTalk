# portal Task C6: Billing per organisation

Status: done with deviations
Commit: <pending>
Tests: `cd portal/e2e-tests && RUNTIME_INTERNAL_URL=… npx playwright test tests/billing.spec.ts` -> 15/15; full portal suite -> 153/153 (`npx playwright test` 57, `wasp test client run` 70, `npm run test:unit` 26), green twice in a row, plus `wasp build` and `npx tsc -p tsconfig.src.json --noEmit` clean

Interfaces produced:
route `/app/:orgSlug/billing` (`OrgBillingRoute` in `portal/src/payment/payment.wasp.ts`); actions
`generateCheckoutSession({organizationId})` and `openCustomerPortal({organizationId})` in
`portal/src/payment/operations.ts`; `isEntitlingStatus`, `organizationIsEntitled`,
`subscriptionProblem`, `subscriptionRequiredMessage`, `ENTITLING_SUBSCRIPTION_STATUSES`,
`SUBSCRIPTION_REQUIRED_STATUS`, type `SubscriptionProblem` in `portal/src/payment/entitlement.ts`;
`applyStripeEvent`, `applySubscriptionChange`, types `OrganizationBillingDelegate` and
`OrganizationBillingUpdate` in `portal/src/payment/subscription.ts`; `verifyStripeEvent`,
`subscriptionChangeFor`, types `SubscriptionChange` and `PlanForPriceId` in
`portal/src/payment/stripe/events.ts`; `createStripeCheckoutSession({priceId, paymentPlanId,
organizationId, organizationSlug, organizationName, ownerEmail})` in
`portal/src/payment/stripe/checkoutUtils.ts`; `checkoutSuccessUrl`, `checkoutCanceledUrl`,
`customerPortalReturnUrl` in `portal/src/payment/paths.ts`;
`findPaymentPlanIdByPaymentProcessorPlanId` in `portal/src/payment/paymentProcessorPlans.ts`;
`SubscriptionStatus.Trialing`, `PLAN_MONTHLY_CAD`, `PLAN_PRICE_TEXT`, `PLAN_FEATURES` in
`portal/src/payment/plans.ts`; component `BillingPage`, `SubscriptionBanner` (in `OrgShell.tsx`),
`OrgShell({title, requiresSubscription, children})`; `OrganizationSummary.entitled` and
`.hasStripeCustomer`; fixture builders `checkoutSessionCompleted`, `subscriptionEvent`,
`invoiceEvent`, `unhandledEvent`, `signEvent`, `signStripePayload`, `STRIPE_TEST_WEBHOOK_SECRET`,
`STRIPE_TEST_PRICE_ID`, `STRIPE_TEST_API_KEY` in `portal/src/payment/stripe/fixtures.ts`, and
`postStripeEvent` in `portal/e2e-tests/tests/stripe.ts`; Prisma migration
`20260902151021_billing_per_organization`.

## What the tests assert

End to end (`portal/e2e-tests/tests/billing.spec.ts`, 15), against one organisation created for
the run whose runtime tenant deliberately does not exist — nothing here is about tenant data,
only about who is let in:

- an organisation that has never subscribed refuses `getTenantConversations`,
  `getTenantRequests` and `getTenantSettings` with 402 on the server, says why on the page
  ("No subscription yet") instead of showing an empty table, keeps the overview open, does not
  stop an agency admin, and has no Stripe billing portal to open yet (404);
- a signed `checkout.session.completed` naming the organisation in `client_reference_id`
  subscribes it (`active`), opens the pages the gate was closing, and gives the owner a link
  into Stripe's billing portal; the same event body signed with another secret is answered 400
  and changes nothing;
- a signed `customer.subscription.updated` with status `past_due` is recorded as past due,
  closes the client pages again with a banner naming the failed payment, and still lets the
  agency admin in;
- a signed `customer.subscription.deleted` is recorded as ended, and the billing page then
  shows "Ended" and offers the plan again;
- an event for a Stripe customer no organisation owns is answered 204 and changes nothing.

Unit, Node runner (`npm run test:unit`, `src/payment/subscription.server.test.ts`, 15): the same
fixture events, signed and put through the same verification, against a fake organisation table —
a completed checkout links the organisation that paid to its Stripe customer and subscribes it,
names the organisation from `client_reference_id` rather than the email, changes nothing when no
organisation is named, and links the customer without claiming a subscription when the session is
unpaid; `trialing`, `past_due` and "active but cancelled at period end" are each recorded as
themselves; a status the portal has no wording for (`incomplete`) leaves the organisation alone;
`invoice.paid` and `invoice.payment_failed` move it to active and past due; an event signed with
another secret, an unsigned event, an unhandled event type, and an event for somebody else's
customer each change nothing.

Unit, browser runner (`wasp test client run`, `src/payment/entitlement.test.ts`, 15): `active` and
`trialing` open the client pages, a subscription cancelled at period end stays open until it ends,
`past_due`, `deleted`, no subscription at all and an unknown status close them, an agency admin is
let through without any subscription, and the banner wording names a failed payment as a payment,
tells an organisation that never subscribed that it never subscribed rather than that it lapsed,
and never says or implies that anything of the clinic's was deleted.

## Red before green

- Server unit: `npm run test:unit` with `subscription.server.test.ts` written and the module
  absent -> `Error: Cannot find module './subscription' imported from
  .../src/payment/subscription.server.test.ts`, `1 failed | 1 passed`. Green afterwards: 26/26.
- Browser unit: `wasp test client run` with `entitlement.test.ts` written ->
  `src/payment/entitlement.test.ts(6,8): error TS2307: Cannot find module './entitlement'` and
  `src/payment/entitlement.test.ts(24,49): error TS2339: Property 'Trialing' does not exist on
  type 'typeof SubscriptionStatus'`, SDK build exit code 2. Green afterwards: 70/70.
- End to end: rather than stash a change that spans a Prisma migration (the C4 approach would have
  left the database ahead of the code), the two behaviours the spec is about were neutralised in
  place — `isEntitlingStatus` made to return true, and `applySubscriptionChange` made to return 0
  without writing. `npx playwright test tests/billing.spec.ts` then gave
  `1 failed, 12 did not run`: `get-tenant-conversations should need a subscription ... Expected:
  402 Received: 404` (with no gate the operation goes on to the runtime, which does not have that
  tenant). Both files were restored from copies taken before the edit and the whole suite re-run.

Two things came out of the first green attempts:

1. **The customer had to stop being created up front.** The template called
   `ensureStripeCustomer(userEmail)` before checkout and wrote the id onto the `User`. Stripe
   refuses a Checkout Session that carries both `customer` and `customer_email`, and the plan
   asks for `customer_email = owner`, so the customer is now created by Stripe during checkout
   and its id arrives on `checkout.session.completed` — which is exactly why that event has to be
   handled, and why `client_reference_id` is the only honest link back to a clinic.
2. **`client.spec.ts` had to subscribe its organisation.** Its staff member is not an agency
   admin, so with the gate in place the requests and settings tests were being refused 402. Its
   `beforeAll` now posts one signed `checkout.session.completed` for that organisation. Left
   unfixed this would have looked like a flake in someone else's suite.

## Deviations

1. **`cancel_at_period_end` is on the entitling list, which the plan's wording ("client pages
   other than Overview require `subscriptionStatus in (active, trialing)`") does not name.** A
   clinic that cancels has paid for the period it is in; closing its pages the same day takes
   away something already bought, and would be a support incident on the first cancellation. The
   list is `ENTITLING_SUBSCRIPTION_STATUSES` in `src/payment/entitlement.ts`, with the reason in a
   comment. The plan's two named tests are unaffected: a past-due organisation is refused and gets
   the banner, and an admin bypasses.
2. **`trialing` is stored as `trialing`.** open-saas mapped Stripe's `trialing` onto its own
   `active`, so the plan's condition could never have been literally true. `SubscriptionStatus`
   gained a `Trialing` member and the webhook records Stripe's own word, which the agency's
   revenue table also needs: a trial is access, not money.
3. **The gate answers 402 Payment Required, not 403.** 403 is already what a non-member and a
   STAFF member acting as an owner get (C2), and the page has to tell those two cases apart to
   choose between "ask for an invitation" and "the subscription lapsed".
4. **The plan's "webhook (open-saas's handler)" was rewritten rather than re-pointed.** The
   template's handler was three Prisma updates keyed to `User.paymentProcessorUserId`, and its
   price-to-plan lookup threw on an unknown price. The reading and deciding are now in
   `src/payment/stripe/events.ts` and `src/payment/subscription.ts`, free of Wasp, Prisma and the
   environment, so the whole path from a signed body to a written row is a unit test with no
   network — which is the only way to test this without a Stripe account.
5. **`invoice.payment_failed` is handled, which the plan does not list.**
   `docs/reference/api-surface.md` names it under "Stripe webhook events used", and the reference
   wins. It sets `past_due`. No conflict was otherwise found between the four reference documents
   and this task.
6. **A Stripe event that matches no organisation is answered 204, not retried into a 400.** Every
   write is `updateMany`, so a foreign customer id is a count of zero and a log line. A `update`
   would have thrown P2025 and made Stripe retry a foreign event until it gave up.
7. **`User` lost `paymentProcessorUserId`, `subscriptionStatus`, `subscriptionPlan` and
   `datePaid`** (migration `20260902151021_billing_per_organization`), as the C1 and C2 reports
   said C6 would. That reached four files outside `src/payment/**`: `src/user/operations.ts` (the
   admin user list no longer filters or selects a subscription; it returns each person's
   organisations and role instead), `src/admin/dashboards/users/UsersTable.tsx` (the "Subscription
   Status" and "Stripe ID" columns and the status filter are replaced by an "Organisations"
   column), `src/user/AccountPage.tsx` (a person has no plan; the page lists the clinics they can
   open, each with its subscription state and, for an owner, a link to its billing page), and
   `src/analytics/stats.ts` (`DailyStats.paidUserCount` counts paying *organisations*; the column
   keeps its name because open-saas's chart reads it, and the job's entity list gained
   `Organization`).
8. **`/checkout` and `CheckoutResultPage.tsx` are gone.** Stripe now returns to
   `/app/:orgSlug/billing?checkout=success|canceled`, so an owner who pays for two clinics lands
   back on the one they paid for; the template's page redirected to `/account`, which is no longer
   where a subscription lives. C1's report lists `/checkout` as a produced route: it no longer
   exists, and nothing linked to it.
9. **`PLAN_MONTHLY_CAD` moved from `src/admin/agency.ts` (a C5 file) to `src/payment/plans.ts`,
   and `agency.ts` re-exports it**; `isPayingStatus` there now delegates to `isEntitlingStatus`.
   The pricing page, the billing page and the agency's MRR line were otherwise about to hold three
   copies of the same number and two copies of the same status list. C5's `agency.test.ts` passes
   unchanged (13/13).
10. **`getCustomerPortalUrl` became the action `openCustomerPortal`.** It creates a single-use
    Stripe billing portal session, so as a query it would have called Stripe on every render of
    every page that read it — and with no Stripe key in development, thrown there. It now runs
    when the owner clicks.
11. **Stripe fixture builders live in `src/payment/stripe/fixtures.ts`, under `src`.** Both suites
    need one definition of the event shapes, and Wasp compiles user code from `src` alone: a test
    file under `src` importing `../../e2e-tests/...` fails to resolve (evidence:
    `src/payment/subscription.server.test.ts(11,8): error TS2307: Cannot find module
    '../../e2e-tests/tests/stripe'`). Nothing in the running portal imports the module; the file
    says so at the top. `e2e-tests/tests/stripe.ts` re-exports it and adds the HTTP half.
12. **`playwright.config.ts` (a C1 file) pins four Stripe variables** for the app it starts —
    `STRIPE_WEBHOOK_SECRET`, `STRIPE_API_KEY`, `STRIPE_PRICE_ID_FRONTDESK` and a no-code
    `STRIPE_CUSTOMER_PORTAL_URL` — so the suite does not depend on a developer's `.env.server` and
    no test reaches Stripe. The pinned key is not a real key and is never used to call the API.
13. **Files beyond the plan's list.** `src/payment/{entitlement.ts, subscription.ts,
    BillingPage.tsx, stripe/events.ts, stripe/fixtures.ts}` and three test files; the four
    de-user-keyed files in deviation 7; `src/client/OrgShell.tsx` and `src/client/OverviewPage.tsx`
    (the banner and the one page that keeps working without a subscription);
    `src/client/operations.ts` (the gate, in `session()`/`ownerSession()`, exactly where C4's
    report said it belonged); `src/organizations/operations.ts` (`entitled` and
    `hasStripeCustomer` on the organisation summary, computed on the server so the page and the
    operations cannot disagree); `schema.prisma` and the migration;
    `e2e-tests/{playwright.config.ts, tests/client.spec.ts, README.md}`.
14. **Prettier was run only on the files this task wrote, plus the files it edited that were
    already formatted at HEAD.** `src/analytics/stats.ts`, `src/client/operations.ts`,
    `src/client/OverviewPage.tsx` and `e2e-tests/tests/client.spec.ts` fail `prettier --check` at
    C5's commit and are left as unformatted as they were found, so the diff is this task's change
    and not a reformat. Evidence: `prettier --check` over the HEAD copies of the twelve edited
    files warns on exactly those four.
15. **Tests were derived from the task's Behaviour and Tests lists, not given verbatim** (this is
    a contract-level plan), and are named after the behaviours. Two of the fifteen end-to-end
    tests — the two about the Stripe billing portal link, behaviour 3 — were written after the
    first green run, when it was clear that behaviour had no test; their 404-before /
    200-after pairing is what proves them.

## Notes for neighbours

- **C7**: the gate is `requireSubscription` in `src/client/operations.ts`; a rate limit on
  `/payments-webhook` must not exist, or Stripe's retries will be throttled into failures.
  `STRIPE_WEBHOOK_SECRET` and `STRIPE_API_KEY` are read through `env` from `wasp/server` and never
  logged; the log-scrub test C7 owes should cover the webhook's `console.error` path, which prints
  the Stripe error object (it contains the payload and the signature header, but not the secret).
  Still open from C2 and C4: React Query retries a refused query three times, so the 402 banner
  takes a few seconds to appear on a cold page.
- **C8**: `portal/package-lock.json` oscillates and is deliberately not part of this commit.
  Running the e2e suite regenerates the Wasp SDK workspace with the Dummy email provider, which
  drops `nodemailer` from the lock; `wasp build` with SMTP puts it back. It was restored to C5's
  version here. A CI job that runs `npm ci` after the e2e job would want the SMTP version, so the
  lock should be checked out clean between the two.
- **C8**: the portal suite is still five commands and needs nothing new — `playwright.config.ts`
  supplies the Stripe values itself. `wasp db migrate-dev` must run before the e2e job, as before;
  there is one new migration.
- **C5's tenants table and revenue card** now show real values as soon as an organisation is
  subscribed. `mrrCadFor(status, monthlyCad?)` still takes an amount, so if the real Stripe amount
  should be shown, store it on `Organization` in `applySubscriptionChange` and pass it; the
  arithmetic does not change.
- **The founder's Stripe steps are unchanged and still owed** (`docs/runbooks/accounts-and-env.md`
  § 10): create the product and the recurring price, put its id in `STRIPE_PRICE_ID_FRONTDESK`,
  and point a webhook endpoint at `https://app-api.<domain>/payments-webhook` subscribed to
  `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted`, `invoice.paid` and `invoice.payment_failed`. Nothing in this
  task called Stripe.
