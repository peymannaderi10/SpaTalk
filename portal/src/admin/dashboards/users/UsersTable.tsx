import {
  IconChevronLeft,
  IconChevronRight,
  IconUsers,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useAuth } from "wasp/client/auth";
import {
  getPaginatedUsers,
  updateIsUserAdminById,
  useQuery,
} from "wasp/client/operations";
import { type User } from "wasp/entities";
import { EmptyState } from "../../../client/components/empty-state";
import { Badge } from "../../../client/components/ui/badge";
import { Button } from "../../../client/components/ui/button";
import { Input } from "../../../client/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../client/components/ui/select";
import { Switch } from "../../../client/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../../client/components/ui/table";
import { useDebounce } from "../../../client/hooks/useDebounce";

/**
 * Who has an account, and which clinics they can open.
 *
 * The table is the kit's user list (`src/features/users` in
 * `satnaing/shadcn-admin`): its toolbar of a search box and a filter, its
 * table with a badge per organisation, and its pager. The pages come from the
 * server, so the pager walks the query rather than a client-side row model.
 *
 * A person carries no subscription: a clinic does (portal plan, Task C6), so
 * the column that used to show a Stripe status shows the organisations this
 * person belongs to instead.
 */

const ADMIN_FILTERS = [
  { value: "both", label: "Everyone" },
  { value: "true", label: "Agency admins" },
  { value: "false", label: "Not admins" },
];

function AdminSwitch({ id, isAdmin }: Pick<User, "id" | "isAdmin">) {
  const { data: currentUser } = useAuth();
  const isCurrentUser = currentUser?.id === id;

  return (
    <Switch
      checked={isAdmin}
      aria-label="Agency admin"
      onCheckedChange={(value) => updateIsUserAdminById({ id: id, isAdmin: value })}
      disabled={isCurrentUser}
    />
  );
}

export function UsersTable() {
  const [currentPage, setCurrentPage] = useState(1);
  const [emailFilter, setEmailFilter] = useState<string | undefined>(undefined);
  const [isAdminFilter, setIsAdminFilter] = useState<boolean | undefined>(
    undefined,
  );
  const debouncedEmailFilter = useDebounce(emailFilter, 300);

  const skipPages = currentPage - 1;

  const { data, isLoading } = useQuery(getPaginatedUsers, {
    skipPages,
    filter: {
      ...(debouncedEmailFilter && { emailContains: debouncedEmailFilter }),
      ...(isAdminFilter !== undefined && { isAdmin: isAdminFilter }),
    },
  });

  useEffect(
    function backToPageOne() {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentPage(1);
    },
    [debouncedEmailFilter, isAdminFilter],
  );

  const totalPages = data?.totalPages ?? 1;

  return (
    <div className="flex flex-1 flex-col gap-4">
      <div
        className="flex flex-col-reverse items-start gap-2 sm:flex-row sm:items-center"
        role="toolbar"
      >
        <Input
          placeholder="Filter by email…"
          data-testid="users-search"
          className="h-8 w-37.5 lg:w-62.5"
          onChange={(event) => {
            const value = event.currentTarget.value;
            setEmailFilter(value === "" ? undefined : value);
          }}
        />
        <Select
          value={
            isAdminFilter === undefined ? "both" : isAdminFilter ? "true" : "false"
          }
          onValueChange={(value) =>
            setIsAdminFilter(value === "both" ? undefined : value === "true")
          }
        >
          <SelectTrigger className="h-8 w-44" data-testid="users-admin-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ADMIN_FILTERS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="overflow-hidden rounded-md border">
        <Table data-testid="users-table" className="min-w-xl">
          <TableHeader>
            <TableRow>
              <TableHead>Email and username</TableHead>
              <TableHead>Organisations</TableHead>
              <TableHead className="text-right">Agency admin</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="text-muted-foreground h-24 text-center"
                >
                  Loading…
                </TableCell>
              </TableRow>
            ) : (data?.users ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={3} className="p-0">
                  <EmptyState
                    title="Nobody matches that"
                    description="Clear the filters to see every account."
                    icon={IconUsers}
                    className="border-0"
                  />
                </TableCell>
              </TableRow>
            ) : (
              (data?.users ?? []).map((user) => (
                <TableRow key={user.id} data-testid="user-row">
                  <TableCell>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium">{user.email}</span>
                      <span className="text-muted-foreground text-xs">
                        {user.username}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {user.organizations.length === 0 ? (
                      <span className="text-muted-foreground text-sm">None</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {user.organizations.map((org) => (
                          <Badge
                            key={org.id}
                            variant="outline"
                            asChild
                            className="font-normal"
                          >
                            <Link to={`/app/${org.slug}`}>
                              {org.name} · {org.role === "OWNER" ? "owner" : "staff"}
                            </Link>
                          </Badge>
                        ))}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <AdminSwitch id={user.id} isAdmin={user.isAdmin} />
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-end gap-2">
        <span className="text-sm font-medium">
          Page {currentPage} of {totalPages}
        </span>
        <Button
          variant="outline"
          className="size-8 p-0"
          data-testid="users-previous"
          disabled={currentPage <= 1}
          onClick={() => setCurrentPage((page) => page - 1)}
        >
          <span className="sr-only">Go to previous page</span>
          <IconChevronLeft className="size-4" />
        </Button>
        <Button
          variant="outline"
          className="size-8 p-0"
          data-testid="users-next"
          disabled={currentPage >= totalPages}
          onClick={() => setCurrentPage((page) => page + 1)}
        >
          <span className="sr-only">Go to next page</span>
          <IconChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
