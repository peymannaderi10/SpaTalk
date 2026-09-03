import { type AuthUser } from "wasp/auth";
import { PageHeader } from "../../../client/components/page-header";
import { DefaultLayout } from "../../layout/DefaultLayout";
import { UsersTable } from "./UsersTable";

export function UsersDashboardPage({ user }: { user: AuthUser }) {
  return (
    <DefaultLayout user={user}>
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="Users"
          description="Everyone with an account, and the clinics they can open."
        />
        <UsersTable />
      </div>
    </DefaultLayout>
  );
}
