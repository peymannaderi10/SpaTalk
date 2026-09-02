import { CheckCircle } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useAuth } from "wasp/client/auth";
import {
  generateCheckoutSession,
  getCustomerPortalUrl,
  useQuery,
} from "wasp/client/operations";
import { routes } from "wasp/client/router";
import { Alert, AlertDescription } from "../client/components/ui/alert";
import { Button } from "../client/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardTitle,
} from "../client/components/ui/card";
import {
  PaymentPlanId,
  prettyPaymentPlanName,
  SubscriptionStatus,
} from "./plans";

interface PaymentPlanCard {
  name: string;
  price: string;
  description: string;
  features: string[];
}

export const paymentPlanCards: Record<PaymentPlanId, PaymentPlanCard> = {
  [PaymentPlanId.FrontDesk]: {
    name: prettyPaymentPlanName(PaymentPlanId.FrontDesk),
    price: "$999",
    description: "One clinic, every channel, one monthly price",
    features: [
      "Phone, SMS, web chat and Instagram",
      "Every request tracked until a person closes it",
      "Owner dashboard, transcripts and audit trail",
    ],
  },
};

export function PricingPage() {
  const [isPaymentLoading, setIsPaymentLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const { data: user } = useAuth();
  const isUserSubscribed =
    !!user &&
    !!user.subscriptionStatus &&
    user.subscriptionStatus !== SubscriptionStatus.Deleted;

  const {
    data: customerPortalUrl,
    isLoading: isCustomerPortalUrlLoading,
    error: customerPortalUrlError,
  } = useQuery(getCustomerPortalUrl, { enabled: isUserSubscribed });

  const navigate = useNavigate();

  async function handleBuyNowClick(paymentPlanId: PaymentPlanId) {
    if (!user) {
      navigate(routes.LoginRoute.to);
      return;
    }
    try {
      setIsPaymentLoading(true);

      const checkoutSession = await generateCheckoutSession(paymentPlanId);

      if (checkoutSession?.sessionUrl) {
        window.open(checkoutSession.sessionUrl, "_self");
      } else {
        throw new Error("Error generating checkout session URL");
      }
    } catch (error: unknown) {
      console.error(error);
      if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("Error processing payment. Please try again later.");
      }
      // Only reset here, not in the try block: a successful call redirects
      // this same window to Stripe.
      setIsPaymentLoading(false);
    }
  }

  const handleCustomerPortalClick = () => {
    if (!user) {
      navigate(routes.LoginRoute.to);
      return;
    }

    if (customerPortalUrlError) {
      setErrorMessage("Error fetching Customer Portal URL");
      return;
    }

    if (!customerPortalUrl) {
      setErrorMessage(`Customer Portal does not exist for user ${user.id}`);
      return;
    }

    window.open(customerPortalUrl, "_blank");
  };

  return (
    <div className="py-10 lg:mt-10">
      <div className="mx-auto max-w-3xl px-6 lg:px-8">
        <div id="pricing" className="mx-auto max-w-2xl text-center">
          <h2 className="text-foreground mt-2 text-4xl font-bold tracking-tight sm:text-5xl">
            One plan, per clinic
          </h2>
        </div>
        {errorMessage && (
          <Alert variant="destructive" className="mt-8">
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        )}
        <div className="isolate mx-auto mt-16 grid max-w-md grid-cols-1 gap-y-8">
          {Object.values(PaymentPlanId).map((planId) => (
            <Card
              key={planId}
              className="ring-primary relative flex grow flex-col justify-between overflow-hidden ring-2 transition-all duration-300 hover:shadow-lg"
            >
              <CardContent className="h-full justify-between p-8 xl:p-10">
                <div className="flex items-center justify-between gap-x-4">
                  <CardTitle
                    id={planId}
                    className="text-foreground text-lg font-semibold leading-8"
                  >
                    {paymentPlanCards[planId].name}
                  </CardTitle>
                </div>
                <p className="text-muted-foreground mt-4 text-sm leading-6">
                  {paymentPlanCards[planId].description}
                </p>
                <p className="mt-6 flex items-baseline gap-x-1">
                  <span className="text-foreground text-4xl font-bold tracking-tight">
                    {paymentPlanCards[planId].price}
                  </span>
                  <span className="text-muted-foreground text-sm font-semibold leading-6">
                    /month
                  </span>
                </p>
                <ul
                  role="list"
                  className="text-muted-foreground mt-8 space-y-3 text-sm leading-6"
                >
                  {paymentPlanCards[planId].features.map((feature) => (
                    <li key={feature} className="flex gap-x-3">
                      <CheckCircle
                        className="text-primary h-5 w-5 flex-none"
                        aria-hidden="true"
                      />
                      {feature}
                    </li>
                  ))}
                </ul>
              </CardContent>
              <CardFooter>
                {isUserSubscribed ? (
                  <Button
                    onClick={handleCustomerPortalClick}
                    disabled={isCustomerPortalUrlLoading}
                    aria-describedby="manage-subscription"
                    className="w-full"
                  >
                    Manage subscription
                  </Button>
                ) : (
                  <Button
                    onClick={() => handleBuyNowClick(planId)}
                    aria-describedby={planId}
                    className="w-full"
                    disabled={isPaymentLoading}
                  >
                    {user ? "Subscribe" : "Log in to subscribe"}
                  </Button>
                )}
              </CardFooter>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
