import { type Organization } from "wasp/entities";
import { HttpError } from "wasp/server";
import {
  type CreateTenantFromBundle,
  type GetAgencyRevenue,
  type GetAgencyTenants,
  type GetRuntimeStatus,
} from "wasp/server/operations";
import * as z from "zod";
import { requireAdmin } from "../organizations/access";
import { createAndSendInvitation } from "../organizations/operations";
import {
  bundleFormData,
  runtime,
  runtimeCall,
  runtimeHealthz,
  type RuntimeClient,
  type RuntimeStatus,
} from "../runtime/api";
import { ensureArgsSchemaOrThrowHttpError } from "../server/validation";
import {
  PLAN_MONTHLY_CAD,
  lastActivityOf,
  mrrCadFor,
  type AgencyTenantRow,
} from "./agency";
import { BUNDLE_SLOTS } from "./bundle";

/**
 * What the agency sees and does: every client with its runtime numbers, the
 * onboarding of a new one from a bundle, and the state of the runtime itself.
 *
 * Only an agency admin gets past `requireAdmin`, and every runtime read here
 * goes through the same wrapper the client pages use, so the acting admin's
 * address is on the call and the shared key never leaves the server.
 */

export type { AgencyTenantRow };

const slugSchema = z
  .string()
  .min(2)
  .max(64)
  .regex(
    /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
    "A slug is lowercase letters, digits and single hyphens.",
  );

type AdminContext = {
  user?: { id: string; isAdmin: boolean; email?: string | null } | null;
};

function actorOf(context: AdminContext): string {
  return context.user?.email ?? context.user?.id ?? "unknown";
}

// --- every tenant, with this month's runtime numbers -----------------------

/**
 * The month is the *tenant's* month. The runtime answers an undated usage
 * request with the last thirty days in the tenant's own timezone, so the last
 * of those days is that clinic's today, and the month is anchored on it
 * (CLAUDE.md non-negotiable 8).
 */
async function tenantMonth(
  api: RuntimeClient,
  tenantId: string,
): Promise<
  Pick<
    AgencyTenantRow,
    "calls" | "callMinutes" | "texts" | "chats" | "estCostCad"
  >
> {
  const recent = await runtimeCall(
    () =>
      api.GET("/internal/tenants/{tenant_id}/usage", {
        params: { path: { tenant_id: tenantId } },
      }),
    "usage",
  );

  const today = recent.days[recent.days.length - 1]?.date ?? "";
  const month = today
    ? await runtimeCall(
        () =>
          api.GET("/internal/tenants/{tenant_id}/usage", {
            params: {
              path: { tenant_id: tenantId },
              query: { from: `${today.slice(0, 7)}-01`, to: today },
            },
          }),
        "usage",
      )
    : recent;

  const totals = month.totals;
  return {
    calls: totals.calls,
    callMinutes: totals.call_minutes,
    texts: totals.sms_in + totals.sms_out,
    chats: totals.chats,
    estCostCad: totals.est_cost_cad,
  };
}

async function rowFor(
  org: Organization,
  api: RuntimeClient,
): Promise<AgencyTenantRow> {
  const row: AgencyTenantRow = {
    organizationId: org.id,
    name: org.name,
    slug: org.slug,
    runtimeTenantId: org.runtimeTenantId,
    configured: false,
    problem: null,
    configVersion: null,
    calls: 0,
    callMinutes: 0,
    texts: 0,
    chats: 0,
    estCostCad: 0,
    openItems: 0,
    overdueItems: 0,
    lastActivityAt: null,
    subscriptionStatus: org.subscriptionStatus,
    subscriptionPlan: org.subscriptionPlan,
    mrrCad: mrrCadFor(org.subscriptionStatus),
  };

  try {
    const [health, usage] = await Promise.all([
      runtimeCall(
        () =>
          api.GET("/internal/tenants/{tenant_id}/health", {
            params: { path: { tenant_id: org.runtimeTenantId } },
          }),
        "the tenant's health",
      ),
      tenantMonth(api, org.runtimeTenantId),
    ]);

    return {
      ...row,
      ...usage,
      configured: true,
      configVersion: health.config_version,
      openItems: health.open_items,
      overdueItems: health.overdue_items,
      lastActivityAt: lastActivityOf(health),
    };
  } catch (caught) {
    // One organisation the runtime does not know yet must not empty the table:
    // the row says what is missing instead of claiming zeroes are real numbers.
    const message =
      caught instanceof HttpError
        ? caught.message
        : "The front desk service did not answer for this tenant.";
    return { ...row, problem: message };
  }
}

export const getAgencyTenants: GetAgencyTenants<
  void,
  AgencyTenantRow[]
> = async (_args, context) => {
  requireAdmin(context);
  const api = runtime(actorOf(context));

  const organizations = await context.entities.Organization.findMany({
    orderBy: { name: "asc" },
  });

  return Promise.all(organizations.map((org) => rowFor(org, api)));
};

// --- recurring revenue, which is the portal's own to know ------------------

export type RevenueRow = {
  organizationId: string;
  name: string;
  slug: string;
  subscriptionStatus: string | null;
  subscriptionPlan: string | null;
  mrrCad: number;
};

export type AgencyRevenue = {
  rows: RevenueRow[];
  totalMrrCad: number;
  payingCount: number;
  /** The list price the total was computed with; Stripe holds the price of record. */
  planMonthlyCad: number;
};

export const getAgencyRevenue: GetAgencyRevenue<void, AgencyRevenue> = async (
  _args,
  context,
) => {
  requireAdmin(context);

  const organizations = await context.entities.Organization.findMany({
    orderBy: { name: "asc" },
  });

  const rows: RevenueRow[] = organizations.map((org) => ({
    organizationId: org.id,
    name: org.name,
    slug: org.slug,
    subscriptionStatus: org.subscriptionStatus,
    subscriptionPlan: org.subscriptionPlan,
    mrrCad: mrrCadFor(org.subscriptionStatus),
  }));

  return {
    rows,
    totalMrrCad: rows.reduce((sum, row) => sum + row.mrrCad, 0),
    payingCount: rows.filter((row) => row.mrrCad > 0).length,
    planMonthlyCad: PLAN_MONTHLY_CAD,
  };
};

// --- the runtime itself ----------------------------------------------------

export type RuntimePlatformHealth = {
  ok: boolean;
  queued_jobs: number;
  oldest_queued_age_s: number | null;
  dead_jobs: number;
};

export type RuntimeStatusView = {
  health: RuntimePlatformHealth;
  status: RuntimeStatus;
};

export const getRuntimeStatus: GetRuntimeStatus<
  void,
  RuntimeStatusView
> = async (_args, context) => {
  requireAdmin(context);
  const api = runtime(actorOf(context));

  const [health, status] = await Promise.all([
    runtimeCall(() => api.GET("/internal/health", {}), "the service's queue"),
    runtimeHealthz(),
  ]);

  return { health, status };
};

// --- onboarding a tenant from its bundle -----------------------------------

const bundleSchema = z.object({
  tenant: z.string().min(1),
  services: z.string().min(1),
  knowledge: z.string().min(1),
  scripts: z.string().min(1),
  guard: z.string().min(1),
});

const createTenantSchema = z.object({
  name: z.string().trim().min(2).max(120),
  slug: slugSchema,
  ownerEmail: z.string().trim().toLowerCase().pipe(z.email()),
  bundle: bundleSchema,
});

export type NewTenant = {
  runtimeTenantId: string;
  configVersion: number;
  organizationId: string;
  organizationSlug: string;
  /** False when the organisation was already there and the bundle was a re-upload. */
  organizationCreated: boolean;
  invitation: { email: string; inviteUrl: string; expiresAt: Date };
};

/**
 * The agency's onboarding step, in the order that leaves the least mess: check
 * the name is free, let the runtime decide whether the bundle is a tenant, then
 * record the organisation and invite its owner. The runtime's loader is the
 * only thing that reads the bundle, so a bundle that imports from the CLI
 * imports here (portal plan C5, `docs/reference/tenant-config.md`).
 */
export const createTenantFromBundle: CreateTenantFromBundle<
  z.infer<typeof createTenantSchema>,
  NewTenant
> = async (rawArgs, context) => {
  requireAdmin(context);
  const args = ensureArgsSchemaOrThrowHttpError(createTenantSchema, rawArgs);
  const actor = actorOf(context);

  const filenames = Object.fromEntries(
    BUNDLE_SLOTS.map((spec) => [spec.slot, spec.filename]),
  );
  const parts = {
    tenant: args.bundle.tenant,
    services: args.bundle.services,
    knowledge: args.bundle.knowledge,
    scripts: args.bundle.scripts,
    guard: args.bundle.guard,
    created_by: actor,
  };

  const api = runtime(actor);
  const created = await runtimeCall(
    () =>
      api.POST("/internal/tenants/from-bundle", {
        body: parts,
        bodySerializer: () => bundleFormData(parts, filenames),
      }),
    "this bundle",
  );

  // A re-uploaded bundle is a new version of a tenant that already has an
  // organisation; that organisation is kept rather than duplicated, and the
  // name and address typed into the wizard are left alone.
  const existing = await context.entities.Organization.findUnique({
    where: { runtimeTenantId: created.id },
  });

  if (!existing) {
    const takenSlug = await context.entities.Organization.findUnique({
      where: { slug: args.slug },
    });
    if (takenSlug) {
      throw new HttpError(
        409,
        `${created.id} is now configuration version ${created.version} in the front desk ` +
          `service, but /app/${args.slug} already belongs to ${takenSlug.name}, whose tenant ` +
          `is ${takenSlug.runtimeTenantId}. Choose another address and create the ` +
          `organisation again; the bundle does not have to change.`,
      );
    }
  }

  const org =
    existing ??
    (await context.entities.Organization.create({
      data: {
        name: args.name,
        slug: args.slug,
        runtimeTenantId: created.id,
      },
    }));

  const invitation = await createAndSendInvitation({
    entities: context.entities,
    org,
    email: args.ownerEmail,
    role: "OWNER",
  });

  return {
    runtimeTenantId: created.id,
    configVersion: created.version,
    organizationId: org.id,
    organizationSlug: org.slug,
    organizationCreated: existing === null,
    invitation: {
      email: invitation.email,
      inviteUrl: invitation.inviteUrl,
      expiresAt: invitation.expiresAt,
    },
  };
};
