import { LoginForm } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "./AuthPageLayout";
import { useRedirectIfLoggedIn } from "./hooks/useRedirectIfLoggedIn";

export function LoginPage() {
  useRedirectIfLoggedIn();

  return (
    <AuthPageLayout
      title="Sign in"
      description="Enter your email and password to open your clinic's dashboard."
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
          .{" "}
          {/* Named, not linked: the platform's address is given to an agency
              admin privately rather than offered to everyone who reads this
              page. Both pages land in the same place either way. */}
          <span className="block">Platform admins sign in at /admin/login.</span>
        </>
      }
    >
      <LoginForm />
    </AuthPageLayout>
  );
}
