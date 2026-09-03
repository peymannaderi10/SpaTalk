import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useAuth } from "wasp/client/auth";
import {
  acceptInvitation,
  getInvitation,
  useQuery,
} from "wasp/client/operations";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { AuthPageLayout } from "../auth/AuthPageLayout";
import { Alert, AlertDescription } from "../client/components/ui/alert";
import { Button } from "../client/components/ui/button";
import {
  forgetPendingInvitation,
  rememberPendingInvitation,
} from "./pendingInvitation";

/**
 * The public end of an invitation. Someone who has no account yet lands here
 * first: the token is remembered in the browser, they sign up, and they are
 * brought back to this page to accept.
 *
 * It is a signed-out page, so it wears the kit's auth layout: the mark, the
 * product's name, and one card saying what this invitation is.
 */
export function InvitePage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const { data: user, isLoading: isUserLoading } = useAuth();
  const {
    data: invitation,
    isLoading,
    error,
  } = useQuery(getInvitation, { token });

  const [problem, setProblem] = useState<string | null>(null);
  const [isAccepting, setIsAccepting] = useState(false);

  useEffect(() => {
    if (!isUserLoading && !user && token) {
      rememberPendingInvitation(token);
    }
  }, [isUserLoading, user, token]);

  if (isLoading || isUserLoading) {
    return (
      <AuthPageLayout title="Invitation" description="Reading the invitation…">
        <p className="text-muted-foreground text-sm">Loading…</p>
      </AuthPageLayout>
    );
  }

  if (error || !invitation) {
    return (
      <AuthPageLayout
        title="This invitation link is not valid"
        description="Ask whoever invited you to send a new one."
      >
        <Button variant="outline" asChild>
          <WaspRouterLink to={routes.LoginRoute.to}>Go to login</WaspRouterLink>
        </Button>
      </AuthPageLayout>
    );
  }

  if (invitation.status === "accepted") {
    return (
      <AuthPageLayout
        title="This invitation has already been used"
        description={`An invitation works once. Ask an owner of ${invitation.organizationName} for a new one.`}
      >
        <Button variant="outline" asChild>
          <WaspRouterLink to={routes.LoginRoute.to}>Go to login</WaspRouterLink>
        </Button>
      </AuthPageLayout>
    );
  }

  if (invitation.status === "expired") {
    return (
      <AuthPageLayout
        title="This invitation has expired"
        description={`An invitation is good for seven days. Ask an owner of ${invitation.organizationName} for a new one.`}
      >
        <Button variant="outline" asChild>
          <WaspRouterLink to={routes.LoginRoute.to}>Go to login</WaspRouterLink>
        </Button>
      </AuthPageLayout>
    );
  }

  if (!user) {
    return (
      <AuthPageLayout
        title={`You are invited to ${invitation.organizationName}`}
        description={`The invitation was sent to ${invitation.email}, as ${invitation.role}. Sign up with that address, or log in if you already have an account, and you will come back here to accept.`}
      >
        <div className="flex gap-3">
          <Button asChild>
            <WaspRouterLink to={routes.SignupRoute.to}>Sign up</WaspRouterLink>
          </Button>
          <Button variant="outline" asChild>
            <WaspRouterLink to={routes.LoginRoute.to}>Log in</WaspRouterLink>
          </Button>
        </div>
      </AuthPageLayout>
    );
  }

  async function onAccept() {
    setProblem(null);
    setIsAccepting(true);
    try {
      const accepted = await acceptInvitation({ token });
      forgetPendingInvitation();
      navigate(`/app/${accepted.organizationSlug}`);
    } catch (caught) {
      setProblem(
        caught instanceof Error && caught.message
          ? caught.message
          : "That did not work. Try again.",
      );
    } finally {
      setIsAccepting(false);
    }
  }

  return (
    <AuthPageLayout
      title={`Join ${invitation.organizationName}`}
      description={`The invitation was sent to ${invitation.email}, as ${invitation.role}. You are signed in as ${user.email ?? user.id}.`}
    >
      <div className="space-y-4">
        <Button onClick={onAccept} disabled={isAccepting}>
          Accept invitation
        </Button>
        {problem && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
      </div>
    </AuthPageLayout>
  );
}
