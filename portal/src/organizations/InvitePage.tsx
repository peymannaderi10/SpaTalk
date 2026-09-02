import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router";
import { useAuth } from "wasp/client/auth";
import {
  acceptInvitation,
  getInvitation,
  useQuery,
} from "wasp/client/operations";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { Button } from "../client/components/ui/button";
import {
  forgetPendingInvitation,
  rememberPendingInvitation,
} from "./pendingInvitation";

/**
 * The public end of an invitation. Someone who has no account yet lands here
 * first: the token is remembered in the browser, they sign up, and they are
 * brought back to this page to accept.
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
    return <PageShell>Loading…</PageShell>;
  }

  if (error || !invitation) {
    return (
      <PageShell>
        <h1 className="text-foreground text-2xl font-semibold">
          This invitation link is not valid
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          Ask whoever invited you to send a new one.
        </p>
      </PageShell>
    );
  }

  if (invitation.status === "accepted") {
    return (
      <PageShell>
        <h1 className="text-foreground text-2xl font-semibold">
          This invitation has already been used
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          An invitation works once. Ask an owner of {invitation.organizationName}{" "}
          for a new one.
        </p>
      </PageShell>
    );
  }

  if (invitation.status === "expired") {
    return (
      <PageShell>
        <h1 className="text-foreground text-2xl font-semibold">
          This invitation has expired
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          An invitation is good for seven days. Ask an owner of{" "}
          {invitation.organizationName} for a new one.
        </p>
      </PageShell>
    );
  }

  if (!user) {
    return (
      <PageShell>
        <h1 className="text-foreground text-2xl font-semibold">
          You are invited to {invitation.organizationName}
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          The invitation was sent to {invitation.email}, as {invitation.role}.
          Sign up with that address, or log in if you already have an account,
          and you will come back here to accept.
        </p>
        <div className="mt-6 flex gap-3">
          <WaspRouterLink to={routes.SignupRoute.to}>
            <Button>Sign up</Button>
          </WaspRouterLink>
          <WaspRouterLink to={routes.LoginRoute.to}>
            <Button variant="outline">Log in</Button>
          </WaspRouterLink>
        </div>
      </PageShell>
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
    <PageShell>
      <h1 className="text-foreground text-2xl font-semibold">
        Join {invitation.organizationName}
      </h1>
      <p className="text-muted-foreground mt-4 text-sm">
        The invitation was sent to {invitation.email}, as {invitation.role}. You
        are signed in as {user.email ?? user.id}.
      </p>
      <div className="mt-6">
        <Button onClick={onAccept} disabled={isAccepting}>
          Accept invitation
        </Button>
      </div>
      {problem && (
        <p role="alert" className="text-destructive mt-4 text-sm">
          {problem}
        </p>
      )}
    </PageShell>
  );
}

function PageShell({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-3xl px-6 py-16">{children}</main>;
}
