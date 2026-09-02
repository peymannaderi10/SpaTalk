import Stripe from "stripe";
import { env } from "wasp/server";
import { customerPortalReturnUrl } from "../paths";
import type {
  CreateCheckoutSessionArgs,
  FetchCustomerPortalUrlArgs,
  PaymentProcessor,
} from "../paymentProcessor";
import { getPaymentProcessorPlanId } from "../paymentProcessorPlans";
import { createStripeCheckoutSession } from "./checkoutUtils";
import { stripeClient } from "./stripeClient";
import { stripeMiddlewareConfigFn, stripeWebhook } from "./webhook";

export const stripePaymentProcessor: PaymentProcessor = {
  id: "stripe",
  createCheckoutSession: async ({
    organizationId,
    organizationSlug,
    organizationName,
    ownerEmail,
    paymentPlan,
  }: CreateCheckoutSessionArgs) => {
    const checkoutSession = await createStripeCheckoutSession({
      priceId: getPaymentProcessorPlanId(paymentPlan),
      paymentPlanId: paymentPlan.id,
      organizationId,
      organizationSlug,
      organizationName,
      ownerEmail,
    });

    if (!checkoutSession.url) {
      throw new Error(
        "Stripe checkout session URL is missing. Checkout session might not be active.",
      );
    }

    return {
      session: {
        url: checkoutSession.url,
        id: checkoutSession.id,
      },
    };
  },
  fetchCustomerPortalUrl: async ({
    stripeCustomerId,
    organizationSlug,
  }: FetchCustomerPortalUrlArgs) => {
    // A no-code Stripe customer portal link, when the deployment configures
    // one, saves a round trip to Stripe.
    if (env.STRIPE_CUSTOMER_PORTAL_URL) {
      return env.STRIPE_CUSTOMER_PORTAL_URL;
    }

    const billingPortalSession =
      await stripeClient.billingPortal.sessions.create({
        customer: stripeCustomerId,
        return_url: customerPortalReturnUrl(organizationSlug),
      });

    return billingPortalSession.url;
  },
  webhook: stripeWebhook,
  webhookMiddlewareConfigFn: stripeMiddlewareConfigFn,
  fetchTotalRevenue: async () => {
    let totalRevenue = 0;
    const params: Stripe.BalanceTransactionListParams = {
      limit: 100,
      type: "charge",
    };

    let hasMore = true;
    while (hasMore) {
      const balanceTransactions =
        await stripeClient.balanceTransactions.list(params);

      for (const transaction of balanceTransactions.data) {
        totalRevenue += transaction.amount;
      }

      if (balanceTransactions.has_more) {
        params.starting_after =
          balanceTransactions.data[balanceTransactions.data.length - 1].id;
      } else {
        hasMore = false;
      }
    }

    // Revenue is in cents so we convert to dollars (or your main currency unit)
    return totalRevenue / 100;
  },
};
