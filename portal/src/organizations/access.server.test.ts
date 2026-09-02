import { describe, expect, it, vi } from "vitest";

/**
 * `access.ts` throws Wasp's `HttpError`, which lives in `wasp/server` next to
 * the Prisma client and the server env validation. A unit test has neither, so
 * the module is replaced with the one class these functions use.
 */
vi.mock("wasp/server", () => {
  class HttpError extends Error {
    public statusCode: number;

    constructor(statusCode: number, message?: string) {
      super(message);
      this.statusCode = statusCode;
    }
  }

  return { HttpError };
});

import {
  requireAdmin,
  requireOrgAccess,
  requireOrgOwner,
  type OrgAccessContext,
  type OrgRole,
} from "./access";

const ORG_ID = "org-1";

const organization = {
  id: ORG_ID,
  createdAt: new Date("2026-09-01T00:00:00Z"),
  name: "Skincentrix",
  slug: "skincentrix",
  runtimeTenantId: "skincentrix",
  stripeCustomerId: null,
  subscriptionStatus: null,
  subscriptionPlan: null,
};

function contextFor({
  user,
  role,
  org = organization,
}: {
  user: { id: string; isAdmin: boolean } | null;
  role?: OrgRole;
  org?: typeof organization | null;
}): OrgAccessContext {
  return {
    user: user ?? undefined,
    entities: {
      Organization: {
        findUnique: async () => org,
      },
      Membership: {
        findUnique: async () => (role ? { role } : null),
      },
    },
  } as unknown as OrgAccessContext;
}

/** The HTTP status a refused call throws, sync or async. */
async function refusalStatus(call: () => unknown): Promise<number> {
  try {
    await call();
  } catch (error) {
    return (error as { statusCode: number }).statusCode;
  }
  throw new Error("Expected the call to be refused, but it was allowed.");
}

describe("requireOrgAccess", () => {
  it("lets a member of the organisation in with their own role", async () => {
    const { org, role } = await requireOrgAccess(
      contextFor({ user: { id: "u1", isAdmin: false }, role: "STAFF" }),
      ORG_ID,
    );

    expect(org.slug).toBe("skincentrix");
    expect(role).toBe("STAFF");
  });

  it("refuses a signed-in user who is not a member with 403", async () => {
    const status = await refusalStatus(() =>
      requireOrgAccess(
        contextFor({ user: { id: "stranger", isAdmin: false } }),
        ORG_ID,
      ),
    );

    expect(status).toBe(403);
  });

  it("lets an agency admin bypass membership, acting as an owner", async () => {
    const { org, role } = await requireOrgAccess(
      contextFor({ user: { id: "agency", isAdmin: true } }),
      ORG_ID,
    );

    expect(org.id).toBe(ORG_ID);
    expect(role).toBe("OWNER");
  });

  it("refuses a signed-out caller with 401", async () => {
    const status = await refusalStatus(() =>
      requireOrgAccess(contextFor({ user: null }), ORG_ID),
    );

    expect(status).toBe(401);
  });

  it("answers 404 for an organisation that does not exist", async () => {
    const status = await refusalStatus(() =>
      requireOrgAccess(
        contextFor({ user: { id: "u1", isAdmin: false }, org: null }),
        ORG_ID,
      ),
    );

    expect(status).toBe(404);
  });
});

describe("requireOrgOwner", () => {
  it("lets an owner through", async () => {
    const { role } = await requireOrgOwner(
      contextFor({ user: { id: "u1", isAdmin: false }, role: "OWNER" }),
      ORG_ID,
    );

    expect(role).toBe("OWNER");
  });

  it("refuses a staff member with 403", async () => {
    const status = await refusalStatus(() =>
      requireOrgOwner(
        contextFor({ user: { id: "u1", isAdmin: false }, role: "STAFF" }),
        ORG_ID,
      ),
    );

    expect(status).toBe(403);
  });

  it("lets an agency admin through", async () => {
    const { role } = await requireOrgOwner(
      contextFor({ user: { id: "agency", isAdmin: true } }),
      ORG_ID,
    );

    expect(role).toBe("OWNER");
  });
});

describe("requireAdmin", () => {
  it("returns the agency admin", () => {
    const user = requireAdmin(
      contextFor({ user: { id: "agency", isAdmin: true } }),
    );

    expect(user.id).toBe("agency");
  });

  it("refuses a signed-in user who is not an agency admin with 403", async () => {
    const status = await refusalStatus(() =>
      requireAdmin(contextFor({ user: { id: "u1", isAdmin: false } })),
    );

    expect(status).toBe(403);
  });

  it("refuses a signed-out caller with 401", async () => {
    const status = await refusalStatus(() =>
      requireAdmin(contextFor({ user: null })),
    );

    expect(status).toBe(401);
  });
});
