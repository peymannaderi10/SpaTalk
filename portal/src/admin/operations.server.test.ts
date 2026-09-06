import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

/**
 * Onboarding a tenant from the basics (onboarding roadmap, section 4).
 *
 * `createTenantFromBasics` posts the basics to the runtime, which renders its
 * starter bundle around them and is the only judge of whether they make a
 * tenant; the portal then records the organisation and invites the owner
 * exactly as the bundle path does, through the one shared tail. Nothing here
 * reaches a runtime, a database or a mailbox: `fetch` is a stub that answers
 * for the runtime, the entities are fakes with the calls the tail makes, and
 * the invitation helper is mocked.
 */

vi.mock("wasp/server", () => {
  class HttpError extends Error {
    public statusCode: number;
    public data: unknown;

    constructor(statusCode: number, message?: string, data?: unknown) {
      super(message);
      this.statusCode = statusCode;
      this.data = data;
    }
  }
  const env = {
    RUNTIME_INTERNAL_KEY: "internal-key-0123456789abcdef",
    RUNTIME_INTERNAL_URL: "http://runtime.test:8000",
  };
  return { HttpError, env };
});

const invitations = vi.hoisted(() => ({
  createAndSendInvitation: vi.fn(),
}));

vi.mock("../organizations/operations", () => ({
  createAndSendInvitation: invitations.createAndSendInvitation,
}));

import { __resetRuntimeCredentials } from "../runtime/api";
import {
  createTenantFromBasics,
  createTenantFromBundle,
  type BasicsArgs,
} from "./operations";

type Org = {
  id: string;
  name: string;
  slug: string;
  runtimeTenantId: string;
  subscriptionStatus: string | null;
  subscriptionPlan: string | null;
};

type Call = { url: string; method: string; body: unknown };
const calls: Call[] = [];

/** A runtime that answers `from-basics` and `from-bundle` as told. */
function runtimeAnswering(status: number, body: unknown) {
  return async (input: Request) => {
    const request = input;
    const text = await request.text();
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      // multipart: keep the raw text
    }
    calls.push({ url: request.url, method: request.method, body: parsed });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
}

function entitiesWith(rows: Org[]) {
  const organizations = rows;
  return {
    rows: organizations,
    Organization: {
      async findUnique({
        where,
      }: {
        where: { runtimeTenantId?: string; slug?: string };
      }): Promise<Org | null> {
        return (
          organizations.find(
            (org) =>
              (where.runtimeTenantId !== undefined &&
                org.runtimeTenantId === where.runtimeTenantId) ||
              (where.slug !== undefined && org.slug === where.slug),
          ) ?? null
        );
      },
      async create({
        data,
      }: {
        data: { name: string; slug: string; runtimeTenantId: string };
      }): Promise<Org> {
        const org: Org = {
          id: `org-${organizations.length + 1}`,
          subscriptionStatus: null,
          subscriptionPlan: null,
          ...data,
        };
        organizations.push(org);
        return org;
      },
    },
    Membership: {},
    Invitation: {},
  };
}

function adminContext(rows: Org[] = []) {
  return {
    user: { id: "admin-1", isAdmin: true, email: "admin@spatalk.test" },
    entities: entitiesWith(rows),
  };
}

const basicsArgs: BasicsArgs = {
  name: "North Clinic",
  slug: "north-clinic",
  ownerEmail: "Owner@North.test",
  ownerName: "Dana",
  basics: {
    timezone: "America/Toronto",
    hours: {
      mon: [["09:00", "17:00"]],
      tue: [["09:00", "17:00"]],
      wed: [],
      thu: [],
      fri: [],
      sat: [["10:00", "14:00"]],
      sun: [],
    },
    bookingUrl: "https://north.janeapp.com/",
    publicPhone: "+19055550123",
    assistantName: "Mia",
  },
};

async function thrown(run: () => unknown) {
  try {
    await run();
  } catch (caught) {
    return caught as { statusCode: number; message: string };
  }
  throw new Error("expected a refusal");
}

beforeEach(() => {
  calls.length = 0;
  __resetRuntimeCredentials();
  invitations.createAndSendInvitation.mockReset();
  invitations.createAndSendInvitation.mockImplementation(
    async ({ email, role }: { email: string; role: string }) => ({
      id: "inv-1",
      email,
      role,
      inviteUrl: `http://portal.test/invite/token-for-${email}`,
      expiresAt: new Date("2026-09-13T00:00:00Z"),
    }),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("createTenantFromBasics", () => {
  test("posts the basics to the runtime with the slug as the tenant id, then records the organisation and invites the owner", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(runtimeAnswering(200, { id: "north-clinic", version: 1 })),
    );
    const context = adminContext();

    const result = await createTenantFromBasics(basicsArgs, context as never);

    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].url).toBe(
      "http://runtime.test:8000/internal/tenants/from-basics",
    );
    expect(calls[0].body).toEqual({
      id: "north-clinic",
      name: "North Clinic",
      timezone: "America/Toronto",
      hours: basicsArgs.basics.hours,
      booking_url: "https://north.janeapp.com/",
      public_phone: "+19055550123",
      owner_name: "Dana",
      owner_email: "owner@north.test",
      assistant_name: "Mia",
      created_by: "admin@spatalk.test",
    });

    expect(context.entities.rows).toHaveLength(1);
    expect(context.entities.rows[0]).toMatchObject({
      name: "North Clinic",
      slug: "north-clinic",
      runtimeTenantId: "north-clinic",
    });
    expect(invitations.createAndSendInvitation).toHaveBeenCalledTimes(1);
    expect(invitations.createAndSendInvitation.mock.calls[0][0]).toMatchObject({
      org: { slug: "north-clinic" },
      email: "owner@north.test",
      role: "OWNER",
    });
    expect(result).toEqual({
      runtimeTenantId: "north-clinic",
      configVersion: 1,
      organizationId: "org-1",
      organizationSlug: "north-clinic",
      organizationCreated: true,
      invitation: {
        email: "owner@north.test",
        inviteUrl: "http://portal.test/invite/token-for-owner@north.test",
        expiresAt: new Date("2026-09-13T00:00:00Z"),
      },
    });
  });

  test("refuses anyone who is not an agency admin before anything is called", async () => {
    const fetchSpy = vi.fn(runtimeAnswering(200, { id: "x", version: 1 }));
    vi.stubGlobal("fetch", fetchSpy);
    const context = {
      user: { id: "u-2", isAdmin: false, email: "dana@clinic.test" },
      entities: entitiesWith([]),
    };

    const error = await thrown(() =>
      createTenantFromBasics(basicsArgs, context as never),
    );

    expect(error.statusCode).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(invitations.createAndSendInvitation).not.toHaveBeenCalled();
  });

  test("refuses bad arguments before the runtime is asked", async () => {
    const fetchSpy = vi.fn(runtimeAnswering(200, { id: "x", version: 1 }));
    vi.stubGlobal("fetch", fetchSpy);

    const error = await thrown(() =>
      createTenantFromBasics(
        { ...basicsArgs, basics: { ...basicsArgs.basics, bookingUrl: "nope" } },
        adminContext() as never,
      ),
    );

    expect(error.statusCode).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("hands on the runtime's refusal of a tenant that already exists as a 409, and records nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        runtimeAnswering(409, {
          detail:
            "tenant north-clinic already exists; edit it on its Settings page instead",
        }),
      ),
    );
    const context = adminContext();

    const error = await thrown(() =>
      createTenantFromBasics(basicsArgs, context as never),
    );

    expect(error.statusCode).toBe(409);
    expect(error.message).toContain("north-clinic");
    expect(error.message).toContain("already");
    expect(context.entities.rows).toHaveLength(0);
    expect(invitations.createAndSendInvitation).not.toHaveBeenCalled();
  });

  test("refuses an address another organisation holds before the runtime is asked, in the bundle path's words", async () => {
    const fetchSpy = vi.fn(
      runtimeAnswering(200, { id: "north-clinic", version: 1 }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const context = adminContext([
      {
        id: "org-9",
        name: "Someone Else",
        slug: "north-clinic",
        runtimeTenantId: "someone-else",
        subscriptionStatus: null,
        subscriptionPlan: null,
      },
    ]);

    const error = await thrown(() =>
      createTenantFromBasics(basicsArgs, context as never),
    );

    expect(error.statusCode).toBe(409);
    expect(error.message).toContain(
      "/app/north-clinic already belongs to Someone Else",
    );
    expect(error.message).toContain("someone-else");
    expect(error.message).toContain("Choose another address");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(context.entities.rows).toHaveLength(1);
  });

  test("keeps an organisation that already points at this tenant id, and still invites the owner", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(runtimeAnswering(200, { id: "north-clinic", version: 1 })),
    );
    const context = adminContext([
      {
        id: "org-4",
        name: "North Clinic (made by hand)",
        slug: "north",
        runtimeTenantId: "north-clinic",
        subscriptionStatus: null,
        subscriptionPlan: null,
      },
    ]);

    const result = await createTenantFromBasics(basicsArgs, context as never);

    expect(result.organizationCreated).toBe(false);
    expect(result.organizationSlug).toBe("north");
    expect(context.entities.rows).toHaveLength(1);
    expect(invitations.createAndSendInvitation).toHaveBeenCalledTimes(1);
  });
});

describe("the shared tail", () => {
  test("the bundle path refuses a taken address in the same words, after the runtime has the bundle", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(runtimeAnswering(200, { id: "north-clinic", version: 2 })),
    );
    const context = adminContext([
      {
        id: "org-9",
        name: "Someone Else",
        slug: "north-clinic",
        runtimeTenantId: "someone-else",
        subscriptionStatus: null,
        subscriptionPlan: null,
      },
    ]);

    const error = await thrown(() =>
      createTenantFromBundle(
        {
          name: "North Clinic",
          slug: "north-clinic",
          ownerEmail: "owner@north.test",
          bundle: {
            tenant: "id: north-clinic\n",
            services: "services: []\n",
            knowledge: "# North\n",
            scripts: "disclosure: hi\n",
            guard: "clinical: []\n",
          },
        },
        context as never,
      ),
    );

    expect(error.statusCode).toBe(409);
    expect(error.message).toContain(
      "north-clinic is now configuration version 2 in the front desk service",
    );
    expect(error.message).toContain(
      "/app/north-clinic already belongs to Someone Else",
    );
    expect(error.message).toContain("Choose another address");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      "http://runtime.test:8000/internal/tenants/from-bundle",
    );
  });
});
