import { ResetPasswordForm } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "../AuthPageLayout";

export function PasswordResetPage() {
  return (
    <AuthPageLayout
      title="Choose a new password"
      description="This link works once, and only for a short while."
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
      <ResetPasswordForm />
    </AuthPageLayout>
  );
}
