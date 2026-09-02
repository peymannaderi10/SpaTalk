import Stripe from "stripe";
import { env } from "wasp/server";
import { CUSTOMER_PORTAL_RETURN_URL } from "../paths";
import type {
  CreateCheckoutSessionArgs,
  FetchCustomerPortalUrlArgs,
  PaymentProcessor,
} from "../paymentProcessor";
import { getPaymentProcessorPlanId } from "../paymentProcessorPlans";
import {
  fetchUserPaymentProcessorUserId,
  updateUserPaymentProcessorUserId,
} from "../user";
import {
  createStripeCheckoutSession,
  ensureStripeCustomer,
} from "./checkoutUtils";
import { stripeClient } from "./stripeClient";
import { stripeMiddlewareConfigFn, stripeWebhook } from "./webhook";

export const stripePaymentProcessor: PaymentProcessor = {
  id: "stripe",
  createCheckoutSession: async ({
    userId,
    userEmail,
    paymentPlan,
    prismaUserDelegate,
  }: CreateCheckoutSessionArgs) => {
    const customer = await ensureStripeCustomer(userEmail);

    await updateUserPaymentProcessorUserId(
      { userId, paymentProcessorUserId: customer.id },
      prismaUserDelegate,
    );

    const checkoutSession = await createStripeCheckoutSession({
      customerId: customer.id,
      priceId: getPaymentProcessorPlanId(paymentPlan),
      mode: "subscription",
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
    prismaUserDelegate,
    userId,
  }: FetchCustomerPortalUrlArgs) => {
    const paymentProcessorUserId = await fetchUserPaymentProcessorUserId(
      userId,
      prismaUserDelegate,
    );

    if (!paymentProcessorUserId) {
      return null;
    }

    // A no-code Stripe customer portal link, when the deployment configures
    // one, saves a round trip to Stripe on every page render.
    if (env.STRIPE_CUSTOMER_PORTAL_URL) {
      return env.STRIPE_CUSTOMER_PORTAL_URL;
    }

    const billingPortalSession =
      await stripeClient.billingPortal.sessions.create({
        customer: paymentProcessorUserId,
        return_url: CUSTOMER_PORTAL_RETURN_URL,
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
