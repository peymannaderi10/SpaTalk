import { LoginForm } from "wasp/client/auth";
import { AuthPageLayout } from "../auth/AuthPageLayout";
import { useRedirectIfLoggedIn } from "../auth/hooks/useRedirectIfLoggedIn";

/**
 * The platform's own front door.
 *
 * It is the same form and the same session as `/login` — there is one account
 * table and one set of credentials — so this page proves nothing about who is
 * signing in and grants nothing. What it does is separate the two audiences at
 * the door: an agency admin has an address of their own, given to them
 * privately, and lands where their work is instead of passing through a page
 * meant for a clinic.
 *
 * Both pages land on `/app`, where `entry.ts` decides: an admin goes on to
 * `/admin`, an owner into their organisation. So a clinic owner who signs in
 * here still ends up in their own dashboard, and an admin who uses `/login`
 * still reaches the platform. Nothing here is a permission check; the
 * permission check is on every operation, on the server.
 */
export function AdminLoginPage() {
  useRedirectIfLoggedIn();

  return (
    <AuthPageLayout
      title="Platform sign-in"
      description="Sign in to the agency's own dashboard."
      footer={<>Running a clinic? Your sign-in is at /login.</>}
    >
      <LoginForm />
    </AuthPageLayout>
  );
}
