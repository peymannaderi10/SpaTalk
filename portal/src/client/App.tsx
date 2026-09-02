import { useMemo } from "react";
import { Outlet, useLocation } from "react-router";
import { routes } from "wasp/client/router";
import { PendingInvitationRedirect } from "../organizations/PendingInvitationRedirect";
import { Toaster } from "../client/components/ui/toaster";
import "./Main.css";
import { NavBar } from "./components/NavBar/NavBar";
import { appNavigationItems } from "./components/NavBar/constants";

/**
 * Wraps every page. The admin dashboard brings its own chrome, the auth pages
 * have none, and everything else gets the app navigation bar.
 */
export function App() {
  const location = useLocation();

  const shouldDisplayAppNavBar = useMemo(() => {
    return (
      location.pathname !== routes.LoginRoute.build() &&
      location.pathname !== routes.SignupRoute.build()
    );
  }, [location]);

  const isAdminDashboard = useMemo(() => {
    return location.pathname.startsWith(routes.AdminRoute.to);
  }, [location]);

  return (
    <>
      <PendingInvitationRedirect />
      <div className="bg-background text-foreground min-h-screen">
        {isAdminDashboard ? (
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
