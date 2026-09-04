import { action, page, query, route, type Spec } from "@wasp.sh/spec";

import { AdminLoginPage } from "./AdminLoginPage" with { type: "ref" };
import { AnalyticsDashboardPage } from "./dashboards/analytics/AnalyticsDashboardPage" with { type: "ref" };
import { HealthPage } from "./HealthPage" with { type: "ref" };
import { NewTenantWizard } from "./NewTenantWizard" with { type: "ref" };
import {
  createTenantFromBundle,
  getAgencyRevenue,
  getAgencyTenants,
  getRuntimeStatus,
} from "./operations" with { type: "ref" };
import { TenantsPage } from "./TenantsPage" with { type: "ref" };
import { UsersDashboardPage } from "./dashboards/users/UsersDashboardPage" with { type: "ref" };

/**
 * The agency's own pages. Every operation here refuses anyone who is not an
 * agency admin, in the server code and not only in the layout, so a route
 * typed into the address bar is refused the same way a hidden link would be.
 */

export const adminSpec: Spec = [
  // The one page here that is not authRequired: it is where an agency admin
  // signs in. It grants nothing — the session it creates is the same session
  // `/login` creates — so it is safe to be open, and `/app` is what sends the
  // person who used it wherever their work actually is.
  route("AdminLoginRoute", "/admin/login", page(AdminLoginPage)),
  route(
    "AdminRoute",
    "/admin",
    page(AnalyticsDashboardPage, { authRequired: true }),
  ),
  route(
    "AdminUsersRoute",
    "/admin/users",
    page(UsersDashboardPage, { authRequired: true }),
  ),
  route(
    "AdminTenantsRoute",
    "/admin/tenants",
    page(TenantsPage, { authRequired: true }),
  ),
  // Declared before the list route would ever shadow it; Wasp matches exact
  // paths, but keeping them adjacent makes the pair obvious.
  route(
    "AdminNewTenantRoute",
    "/admin/tenants/new",
    page(NewTenantWizard, { authRequired: true }),
  ),
  route(
    "AdminHealthRoute",
    "/admin/health",
    page(HealthPage, { authRequired: true }),
  ),

  query(getAgencyTenants, { entities: ["Organization"] }),
  query(getAgencyRevenue, { entities: ["Organization"] }),
  // Nothing of the portal's own: it asks the runtime how it is.
  query(getRuntimeStatus, { entities: [] }),
  action(createTenantFromBundle, {
    entities: ["Organization", "Membership", "Invitation"],
  }),
];
