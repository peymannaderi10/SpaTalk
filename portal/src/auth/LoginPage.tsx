import { LoginForm } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "./AuthPageLayout";
import { useRedirectIfLoggedIn } from "./hooks/useRedirectIfLoggedIn";

export function LoginPage() {
  useRedirectIfLoggedIn();

  return (
    <AuthPageLayout
      title="Sign in"
      description="Enter your email and password to open your clinic's front desk."
      footer={
        <>
          Don't have an account yet?{" "}
          <WaspRouterLink
            to={routes.SignupRoute.to}
            className="underline underline-offset-4"
          >
            Go to signup
          </WaspRouterLink>
          . Forgot your password?{" "}
          <WaspRouterLink
            to={routes.RequestPasswordResetRoute.to}
            className="underline underline-offset-4"
          >
            Reset it
          </WaspRouterLink>
          .
        </>
      }
    >
      <LoginForm />
    </AuthPageLayout>
  );
}
