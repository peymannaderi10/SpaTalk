import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";
import { useAuth } from "wasp/client/auth";
import {
  forgetPendingInvitation,
  invitationPath,
  readPendingInvitation,
} from "./pendingInvitation";

/**
 * Closes the loop for an invitation opened while signed out: the invite page
 * parked the token, and the moment the person is signed in they are taken
 * back to it. The token is forgotten as soon as they get there, so a declined
 * invitation does not follow them around the app.
 */
export function PendingInvitationRedirect() {
  const { data: user, isLoading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLoading || !user) {
      return;
    }

    const token = readPendingInvitation();
    if (!token) {
      return;
    }

    const target = invitationPath(token);
    if (location.pathname === target) {
      // Arrived: the token has done its job and is not needed again, so a
      // declined invitation does not follow the person around the app.
      forgetPendingInvitation();
      return;
    }

    // The token is kept until the invitation page is actually reached. The
    // login page redirects a freshly signed-in person to /app in the same
    // commit as this effect, and whichever navigation runs last wins; keeping
    // the token means the next render simply tries again from /app.
    navigate(target);
  }, [isLoading, user, location.pathname, navigate]);

  return null;
}
