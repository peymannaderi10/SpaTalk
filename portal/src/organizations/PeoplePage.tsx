import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { type AuthUser } from "wasp/auth";
import {
  getOrganization,
  inviteMember,
  removeMember,
  useQuery,
} from "wasp/client/operations";
import { Button } from "../client/components/ui/button";
import { Input } from "../client/components/ui/input";
import { OrgAppLayout } from "../client/layout/OrgAppLayout";
import { type OrgRole } from "./roles";

/**
 * Who is in the organisation, and who has been invited. An owner changes this
 * list; a staff member is refused here and by every operation behind it.
 */
export function PeoplePage({ user }: { user: AuthUser }) {
  const { orgSlug = "" } = useParams();
  const {
    data: org,
    isLoading,
    error,
    refetch,
  } = useQuery(getOrganization, { slug: orgSlug });

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("STAFF");
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [isInviting, setIsInviting] = useState(false);

  if (isLoading) {
    return <PageShell slug={orgSlug}>Loading…</PageShell>;
  }

  if (error || !org) {
    return (
      <PageShell slug={orgSlug}>
        <h1 className="text-foreground text-2xl font-semibold">
          This organisation is not open to you
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          {error?.message ??
            "Ask an owner of the organisation for an invitation."}
        </p>
      </PageShell>
    );
  }

  if (org.role !== "OWNER") {
    return (
      <PageShell slug={orgSlug} org={org}>
        <h1 className="text-foreground text-2xl font-semibold">
          Settings are for owners
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          You are in {org.name} as {org.role}. A staff member sees everything
          the assistant did and can act on requests, but only an owner changes
          settings, billing and who is in the organisation.
        </p>
        <p className="mt-6 text-sm">
          <Link className="underline" to={`/app/${org.slug}`}>
            Back to {org.name}
          </Link>
        </p>
      </PageShell>
    );
  }

  async function onInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem(null);
    setInviteUrl(null);
    setIsInviting(true);
    try {
      const invitation = await inviteMember({
        organizationId: org!.id,
        email,
        role,
      });
      setInviteUrl(invitation.inviteUrl);
      setEmail("");
      await refetch();
    } catch (caught) {
      setProblem(messageOf(caught));
    } finally {
      setIsInviting(false);
    }
  }

  async function onRemove(userId: string) {
    setProblem(null);
    try {
      await removeMember({ organizationId: org!.id, userId });
      await refetch();
    } catch (caught) {
      setProblem(messageOf(caught));
    }
  }

  return (
    <PageShell slug={orgSlug} org={org}>
      <h1 className="text-foreground text-2xl font-semibold">
        People in {org.name}
      </h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Signed in as {user.email ?? user.id}.
      </p>

      <section className="mt-10">
        <h2 className="text-foreground text-lg font-medium">Members</h2>
        <table className="mt-3 w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-2 font-normal">Email</th>
              <th className="py-2 font-normal">Role</th>
              <th className="py-2 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {org.members.map((member) => (
              <tr key={member.userId} className="border-border border-t">
                <td className="py-2">{member.email}</td>
                <td className="py-2">{member.role}</td>
                <td className="py-2 text-right">
                  {member.userId === user.id ? null : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onRemove(member.userId)}
                    >
                      Remove
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-lg font-medium">Invite someone</h2>
        <form className="mt-3 flex flex-wrap items-center gap-3" onSubmit={onInvite}>
          <Input
            type="email"
            name="email"
            required
            aria-label="Email to invite"
            placeholder="name@clinic.ca"
            className="w-72"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Role</span>
            <select
              aria-label="Role"
              className="border-border bg-background text-foreground rounded-md border px-2 py-1 text-sm"
              value={role}
              onChange={(event) => setRole(event.target.value as OrgRole)}
            >
              <option value="STAFF">STAFF</option>
              <option value="OWNER">OWNER</option>
            </select>
          </label>
          <Button type="submit" disabled={isInviting}>
            Send invitation
          </Button>
        </form>

        {problem && (
          <p role="alert" className="text-destructive mt-3 text-sm">
            {problem}
          </p>
        )}

        {inviteUrl && (
          <p className="mt-3 text-sm">
            Invitation sent. The link, valid once and for seven days:{" "}
            <a className="underline" href={inviteUrl} data-testid="invite-url">
              {inviteUrl}
            </a>
          </p>
        )}

        {org.invitations && org.invitations.length > 0 && (
          <table className="mt-6 w-full text-left text-sm">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-2 font-normal">Invited</th>
                <th className="py-2 font-normal">Role</th>
                <th className="py-2 font-normal">State</th>
                <th className="py-2 font-normal">Link</th>
              </tr>
            </thead>
            <tbody>
              {org.invitations.map((invitation) => (
                <tr key={invitation.id} className="border-border border-t">
                  <td className="py-2">{invitation.email}</td>
                  <td className="py-2">{invitation.role}</td>
                  <td className="py-2">{invitation.status}</td>
                  <td className="py-2">
                    <a className="underline" href={invitation.inviteUrl}>
                      open
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <p className="mt-10 text-sm">
        <Link className="underline" to={`/app/${org.slug}`}>
          Back to {org.name}
        </Link>
      </p>
    </PageShell>
  );
}

function messageOf(caught: unknown): string {
  if (caught instanceof Error && caught.message) {
    return caught.message;
  }
  return "That did not work. Try again.";
}

/**
 * People is a sidebar item under Account, so the page renders inside the app
 * shell like every other page in an organisation. Every branch of this file —
 * loading, refused, not an owner, and the list itself — goes through here, so
 * a refusal keeps the navigation rather than dropping the reader on a page
 * with no way out.
 */
function PageShell({
  slug,
  org,
  children,
}: {
  slug: string;
  org?: { name: string; slug: string; role: OrgRole };
  children: ReactNode;
}) {
  return (
    <OrgAppLayout
      orgSlug={org?.slug ?? slug}
      orgName={org?.name}
      role={org?.role}
      breadcrumbs={[{ label: "People" }]}
    >
      {children}
    </OrgAppLayout>
  );
}
