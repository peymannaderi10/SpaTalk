import * as z from "zod";
import { paymentPlansSchema } from "../env";

export const stripeEnvSchema = paymentPlansSchema.extend({
  STRIPE_API_KEY: z.string({ error: "STRIPE_API_KEY is required" }),
  STRIPE_WEBHOOK_SECRET: z.string({
    error: "STRIPE_WEBHOOK_SECRET is required",
  }),
  // A Stripe no-code customer portal link. Left empty, the app creates a
  // billing portal session through the API instead.
  STRIPE_CUSTOMER_PORTAL_URL: z.string().default(""),
});
