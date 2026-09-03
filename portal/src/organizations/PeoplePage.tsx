import {
  IconDotsVertical,
  IconMailPlus,
  IconSend,
  IconShieldCheck,
  IconUser,
  IconUserOff,
  IconUsers,
} from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { type AuthUser } from "wasp/auth";
import {
  getOrganization,
  inviteMember,
  removeMember,
  useQuery,
} from "wasp/client/operations";
import { DataTable } from "../client/components/data-table";
import { EmptyState } from "../client/components/empty-state";
import { PageHeader } from "../client/components/page-header";
import { Alert, AlertDescription } from "../client/components/ui/alert";
import { Badge } from "../client/components/ui/badge";
import { Button } from "../client/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../client/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../client/components/ui/dropdown-menu";
import { Input } from "../client/components/ui/input";
import { Label } from "../client/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../client/components/ui/select";
import { OrgAppLayout } from "../client/layout/OrgAppLayout";
import { type OrgRole } from "./roles";

/**
 * Who is in the organisation, and who has been invited. An owner changes this
 * list; a staff member is refused here and by every operation behind it.
 *
 * The page is the kit's user list (`src/features/users` in
 * `satnaing/shadcn-admin`): its table with a role badge on every row, its
 * invite dialog behind a primary button, and its row action menu.
 */

type Member = { userId: string; email: string | null; role: OrgRole };
type Invitation = {
  id: string;
  email: string;
  role: string;
  status: string;
  inviteUrl: string;
};

const ROLES: { value: OrgRole; label: string; description: string }[] = [
  {
    value: "STAFF",
    label: "STAFF",
    description: "Sees everything and acts on requests.",
  },
  {
    value: "OWNER",
    label: "OWNER",
    description: "Also changes settings, billing and this list.",
  },
];

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
  const [inviteOpen, setInviteOpen] = useState(false);

  if (isLoading) {
    return (
      <PageShell slug={orgSlug}>
        <p className="text-muted-foreground text-sm">Loading…</p>
      </PageShell>
    );
  }

  if (error || !org) {
    return (
      <PageShell slug={orgSlug}>
        <PageHeader
          title="This organisation is not open to you"
          description={
            error?.message ??
            "Ask an owner of the organisation for an invitation."
          }
        />
      </PageShell>
    );
  }

  if (org.role !== "OWNER") {
    return (
      <PageShell slug={orgSlug} org={org}>
        <PageHeader
          title="Settings are for owners"
          description={`You are in ${org.name} as ${org.role}. A staff member sees everything the assistant did and can act on requests, but only an owner changes settings, billing and who is in the organisation.`}
        />
        <p className="text-sm">
          <Link
            className="underline underline-offset-4"
            to={`/app/${org.slug}`}
          >
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
      setInviteOpen(false);
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

  const memberColumns: ColumnDef<Member>[] = [
    {
      id: "email",
      accessorFn: (row) => row.email ?? "",
      header: "Email",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.email}</span>
      ),
    },
    {
      id: "role",
      accessorFn: (row) => row.role,
      header: "Role",
      cell: ({ row }) => (
        <Badge variant="outline" className="gap-1 font-normal">
          {row.original.role === "OWNER" ? (
            <IconShieldCheck className="size-3" />
          ) : (
            <IconUser className="size-3" />
          )}
          {row.original.role}
        </Badge>
      ),
    },
    {
      id: "actions",
      cell: ({ row }) =>
        row.original.userId === user.id ? null : (
          <div className="text-right">
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="size-8 p-0"
                  data-testid={`member-actions-${row.original.userId}`}
                >
                  <IconDotsVertical className="size-4" />
                  <span className="sr-only">Open menu</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                <DropdownMenuItem
                  onClick={() => onRemove(row.original.userId)}
                  data-testid={`member-remove-${row.original.userId}`}
                >
                  <IconUserOff className="size-4" />
                  Remove from {org.name}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ),
    },
  ];

  const invitationColumns: ColumnDef<Invitation>[] = [
    {
      id: "invited",
      accessorFn: (row) => row.email,
      header: "Invited",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.email}</span>
      ),
    },
    {
      id: "role",
      accessorFn: (row) => row.role,
      header: "Role",
      cell: ({ row }) => (
        <Badge variant="outline" className="font-normal">
          {row.original.role}
        </Badge>
      ),
    },
    {
      id: "state",
      accessorFn: (row) => row.status,
      header: "State",
      cell: ({ row }) => (
        <span className="text-muted-foreground">{row.original.status}</span>
      ),
    },
    {
      id: "link",
      header: "Link",
      cell: ({ row }) => (
        <a
          className="underline underline-offset-4"
          href={row.original.inviteUrl}
        >
          open
        </a>
      ),
    },
  ];

  return (
    <PageShell slug={orgSlug} org={org}>
      <PageHeader
        title={`People in ${org.name}`}
        description={`Signed in as ${user.email ?? user.id}.`}
        actions={
          <Button
            data-testid="invite-member"
            onClick={() => setInviteOpen(true)}
          >
            <IconMailPlus className="size-4" />
            Invite someone
          </Button>
        }
      />

      {problem && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {inviteUrl && (
        <Alert data-testid="invite-sent">
          <AlertDescription>
            Invitation sent. The link, valid once and for seven days:{" "}
            <a
              className="break-all underline underline-offset-4"
              href={inviteUrl}
              data-testid="invite-url"
            >
              {inviteUrl}
            </a>
          </AlertDescription>
        </Alert>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Members</h2>
        <DataTable
          columns={memberColumns}
          data={org.members as Member[]}
          toolbar={false}
          pagination={false}
          testId="member"
          empty="Nobody is in this organisation yet."
        />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Invitations</h2>
        {org.invitations && org.invitations.length > 0 ? (
          <DataTable
            columns={invitationColumns}
            data={org.invitations as Invitation[]}
            toolbar={false}
            pagination={false}
            testId="invitation"
            empty="Nobody has been invited yet."
          />
        ) : (
          <EmptyState
            title="Nobody is waiting on an invitation"
            description="An invitation is good once, and for seven days."
            icon={IconUsers}
            testId="invitations-empty"
          />
        )}
      </section>

      <Dialog
        open={inviteOpen}
        onOpenChange={(next) => {
          setInviteOpen(next);
          if (!next) {
            setProblem(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader className="text-start">
            <DialogTitle className="flex items-center gap-2">
              <IconMailPlus className="size-5" /> Invite someone
            </DialogTitle>
            <DialogDescription>
              They are emailed a single-use invitation that expires in seven
              days. The role decides what they may change.
            </DialogDescription>
          </DialogHeader>

          <form
            id="invite-member-form"
            className="space-y-4"
            onSubmit={onInvite}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                name="email"
                required
                aria-label="Email to invite"
                placeholder="name@clinic.ca"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="invite-role">Role</Label>
              <Select
                value={role}
                onValueChange={(next) => setRole(next as OrgRole)}
              >
                <SelectTrigger
                  id="invite-role"
                  aria-label="Role"
                  data-testid="invite-role"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-sm">
                {ROLES.find((option) => option.value === role)?.description}
              </p>
            </div>
          </form>

          <DialogFooter className="gap-y-2">
            <DialogClose asChild>
              <Button variant="outline" type="button">
                Cancel
              </Button>
            </DialogClose>
            <Button
              type="submit"
              form="invite-member-form"
              disabled={isInviting}
            >
              Send invitation
              <IconSend className="size-4" />
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">{children}</div>
    </OrgAppLayout>
  );
}
