import * as z from "zod";

export const paymentPlansSchema = z.object({
  STRIPE_PRICE_ID_FRONTDESK: z.string({
    error: "STRIPE_PRICE_ID_FRONTDESK is required",
  }),
});
