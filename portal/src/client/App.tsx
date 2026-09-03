import { useMemo } from "react";
import { Outlet, useLocation } from "react-router";
import { routes } from "wasp/client/router";
import { PendingInvitationRedirect } from "../organizations/PendingInvitationRedirect";
import { Toaster } from "../client/components/ui/toaster";
import "./Main.css";
import { NavBar } from "./components/NavBar/NavBar";
import { appNavigationItems } from "./components/NavBar/constants";

/**
 * Wraps every page. An organisation's pages and the agency's pages bring the
 * app shell — sidebar, header, command palette — so they get the page and
 * nothing else around it; the auth pages have no chrome; everything left is
 * the marketing side of the site and gets the navigation bar.
 */
export function App() {
  const location = useLocation();

  const shouldDisplayAppNavBar = useMemo(() => {
    return (
      location.pathname !== routes.LoginRoute.build() &&
      location.pathname !== routes.SignupRoute.build()
    );
  }, [location]);

  const hasItsOwnShell = useMemo(() => {
    return (
      location.pathname.startsWith(routes.AdminRoute.to) ||
      // `/app` itself is the list of organisations and has no sidebar; every
      // page inside one does.
      /^\/app\/[^/]+/.test(location.pathname)
    );
  }, [location]);

  return (
    <>
      <PendingInvitationRedirect />
      <div className="bg-background text-foreground min-h-screen">
        {hasItsOwnShell ? (
          <Outlet />
        ) : (
          <>
            {shouldDisplayAppNavBar && (
              <NavBar navigationItems={appNavigationItems} />
            )}
            <div className="max-w-(--breakpoint-2xl) mx-auto">
              <Outlet />
            </div>
          </>
        )}
      </div>
      <Toaster position="bottom-right" />
    </>
  );
}
