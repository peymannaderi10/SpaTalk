import { Navigate } from "react-router";
import { useAuth } from "wasp/client/auth";
import { routes } from "wasp/client/router";

/**
 * The portal has no marketing site: `/` is a doorway.
 * Signed out goes to the login form, signed in goes to the app.
 */
export function RootRedirectPage() {
  const { data: user, isLoading } = useAuth();

  if (isLoading) {
    return null;
  }

  return (
    <Navigate
      to={user ? routes.AppRoute.to : routes.LoginRoute.to}
      replace
    />
  );
}
