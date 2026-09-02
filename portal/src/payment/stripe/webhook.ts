import express from "express";
import { env, type MiddlewareConfigFn } from "wasp/server";
import { type PaymentsWebhook } from "wasp/server/api";
import { UnhandledWebhookEventError } from "../errors";
import { findPaymentPlanIdByPaymentProcessorPlanId } from "../paymentProcessorPlans";
import { applyStripeEvent } from "../subscription";

/**
 * Stripe's webhook, wired to the organisation table.
 *
 * The reading and the deciding are in `../subscription.ts` and `./events.ts`,
 * which a unit test drives with signed fixture events; this file is the express
 * and Prisma half: the raw body Stripe's signature is computed over, the
 * secret, and the status codes Stripe reads.
 */

/**
 * Stripe requires a raw request to construct events successfully.
 */
export const stripeMiddlewareConfigFn: MiddlewareConfigFn = (
  middlewareConfig,
) => {
  middlewareConfig.delete("express.json");
  middlewareConfig.set(
    "express.raw",
    express.raw({ type: "application/json" }),
  );
  return middlewareConfig;
};

export const stripeWebhook: PaymentsWebhook = async (
  request,
  response,
  context,
) => {
  try {
    const { event, updated } = await applyStripeEvent({
      rawBody: request.body,
      signature: request.headers["stripe-signature"],
      secret: env.STRIPE_WEBHOOK_SECRET,
      planFor: findPaymentPlanIdByPaymentProcessorPlanId,
      organizations: context.entities.Organization,
    });

    if (updated === 0) {
      // Either the event named no organisation of ours, or it carried nothing
      // worth writing. Both are normal on a Stripe account that also serves
      // something else, and neither is Stripe's fault to retry.
      console.info(
        `Stripe webhook ${event.type} (${event.id}) matched no organisation`,
      );
    }

    return response.status(204).send();
  } catch (error) {
    if (error instanceof UnhandledWebhookEventError) {
      // Stripe sends whatever the endpoint is subscribed to, and `stripe
      // trigger` sends more than that. Answering 2XX stops it retrying.
      console.info("Unhandled Stripe webhook event: ", error.message);
      return response.status(204).send();
    }

    console.error("Stripe webhook error:", error);
    if (error instanceof Error) {
      return response.status(400).json({ error: error.message });
    }
    return response
      .status(500)
      .json({ error: "Error processing Stripe webhook event" });
  }
};
