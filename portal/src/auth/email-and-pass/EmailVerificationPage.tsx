import { VerifyEmailForm } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "../AuthPageLayout";

export function EmailVerificationPage() {
  return (
    <AuthPageLayout
      title="Verify your email"
      description="Open the link we sent you, and this page says so."
      footer={
        <>
          If everything is okay,{" "}
          <WaspRouterLink
            to={routes.LoginRoute.to}
            className="underline underline-offset-4"
          >
            go to login
          </WaspRouterLink>
          .
        </>
      }
    >
      <VerifyEmailForm />
    </AuthPageLayout>
  );
}
