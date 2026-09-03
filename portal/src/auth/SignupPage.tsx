import { SignupForm } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "./AuthPageLayout";
import { useRedirectIfLoggedIn } from "./hooks/useRedirectIfLoggedIn";

export function SignupPage() {
  useRedirectIfLoggedIn();

  return (
    <AuthPageLayout
      title="Create an account"
      description="Enter an email and a password. An invitation from a clinic, or from the agency, is what puts an organisation in it."
      footer={
        <>
          Already have an account?{" "}
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
      <SignupForm />
    </AuthPageLayout>
  );
}
