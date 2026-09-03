import { ForgotPasswordForm } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "../AuthPageLayout";

export function RequestPasswordResetPage() {
  return (
    <AuthPageLayout
      title="Forgot password"
      description="Enter your registered email and we will send you a link to reset your password."
      footer={
        <>
          Remembered it?{" "}
          <WaspRouterLink
            to={routes.LoginRoute.to}
            className="underline underline-offset-4"
          >
            Go to login
          </WaspRouterLink>
          .
        </>
      }
    >
      <ForgotPasswordForm />
    </AuthPageLayout>
  );
}
