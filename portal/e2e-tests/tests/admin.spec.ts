import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "fs";
import { join } from "path";
import {
  agencyAdmin,
  callOperation,
  createRandomUser,
  logUserIn,
  serverRequestStatus,
  signInOrSignUp,
  signUserUp,
  verifyUserEmail,
  type User,
} from "./utils";
import { RUNTIME_DIR, runtimeGet } from "./runtime";

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

let page: Page;
let user: User;
let adminPage: Page;

/**
 * The tenant the wizard creates, from the real Skincentrix bundle with its id
 * and name changed. It must not be `skincentrix`: that tenant is seeded with
 * fixed counts and a fixed configuration version for `client.spec.ts`, and
 * importing a bundle over it would write a new version underneath that suite.
 */
const WIZARD_TENANT_ID = "skincentrix-portal-e2e";
const WIZARD_ORG_NAME = "Skincentrix Portal E2E";
const WIZARD_ORG_SLUG = "skincentrix-portal-e2e";
const WIZARD_OWNER_EMAIL = "owner@skincentrix-portal-e2e.test";

/**
 * The tenant the wizard creates from the basics alone: no bundle, the runtime's
 * starter rendered around a timezone, hours, a booking link and an owner. Its
 * id is the organisation's slug, which is what the basics path uses.
 */
const BASICS_ORG_NAME = "Basics Portal E2E";
const BASICS_ORG_SLUG = "basics-portal-e2e";
const BASICS_OWNER_EMAIL = "owner@basics-portal-e2e.test";
const BASICS_BOOKING_URL = "https://basics-portal-e2e.janeapp.com/";

/** An organisation whose runtime tenant deliberately does not exist. */
const UNKNOWN_ORG_SLUG = "not-yet-configured";
const UNKNOWN_TENANT_ID = "tenant-that-does-not-exist";

const BUNDLE_DIR = join(RUNTIME_DIR, "tenants", "skincentrix");

function bundleFile(name: string): string {
  return readFileSync(join(BUNDLE_DIR, name), "utf8");
}

/** The Skincentrix bundle, re-identified so it lands beside the seeded tenant. */
function wizardBundle(): Record<string, string> {
  return {
    tenant: bundleFile("tenant.yaml")
      .replace(/^id: .*$/m, `id: ${WIZARD_TENANT_ID}`)
      .replace(/^name: .*$/m, `name: ${WIZARD_ORG_NAME}`),
    services: bundleFile("services.yaml"),
    knowledge: bundleFile("knowledge.md"),
    scripts: bundleFile("scripts.yaml"),
    guard: bundleFile("guard.yaml"),
  };
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  user = createRandomUser();
  await signUserUp({ page, user });
  await verifyUserEmail({ page, user });
  await logUserIn({ page, user });
  await page.waitForURL("**/app");

  adminPage = await browser.newPage();
  await signInOrSignUp({ page: adminPage, user: agencyAdmin });
});

test.afterAll(async () => {
  await page.close();
  await adminPage.close();
});

test.describe("agency admin area", () => {
  test("/admin is denied to a user who is not an agency admin", async () => {
    await page.goto("/admin");

    await page.waitForURL("**/app");
    expect(new URL(page.url()).pathname).toBe("/app");
    await expect(page.getByText("Total Revenue")).toHaveCount(0);
  });

  test("the admin stats query refuses a user who is not an agency admin", async () => {
    const status = await serverRequestStatus(
      page,
      "/operations/get-daily-stats",
    );

    expect(status).toBe(403);
  });

  test("the agency queries refuse a user who is not an agency admin", async () => {
    expect(
      await serverRequestStatus(page, "/operations/get-agency-tenants"),
    ).toBe(403);
    expect(
      await serverRequestStatus(page, "/operations/get-runtime-status"),
    ).toBe(403);
    expect(
      await serverRequestStatus(page, "/operations/create-tenant-from-bundle", {
        name: "Nope",
        slug: "nope",
        ownerEmail: "nope@spatalk.test",
        bundle: wizardBundle(),
      }),
    ).toBe(403);
    expect(
      await serverRequestStatus(page, "/operations/create-tenant-from-basics", {
        name: "Nope",
        slug: "nope",
        ownerEmail: "nope@spatalk.test",
        ownerName: "",
        basics: {
          timezone: "America/Toronto",
          hours: { mon: [["09:00", "17:00"]] },
          bookingUrl: "https://nope.test/",
          publicPhone: "",
          assistantName: "Ava",
        },
      }),
    ).toBe(403);
  });
});

test.describe("the onboarding wizard", () => {
  test("creates a tenant in the runtime from the five bundle files", async () => {
    const bundle = wizardBundle();

    await adminPage.goto("/admin/tenants/new");
    await expect(
      adminPage.getByRole("heading", { name: "New tenant" }),
    ).toBeVisible(FIRST_RENDER);

    // Step 1: the organisation the client signs in to.
    await adminPage.fill('input[name="organizationName"]', WIZARD_ORG_NAME);
    await adminPage.fill('input[name="organizationSlug"]', WIZARD_ORG_SLUG);
    await adminPage.getByTestId("wizard-next").click();

    // Step 2: the bundle, pasted rather than uploaded from disk. The basics are
    // the default since the basics path landed, so the bundle mode is chosen first.
    await adminPage.getByTestId("wizard-mode-bundle").click();
    for (const [slot, text] of Object.entries(bundle)) {
      await adminPage.fill(`textarea[name="bundle-${slot}"]`, text);
    }
    await adminPage.getByTestId("wizard-next").click();

    // Step 3: who owns it.
    await adminPage.fill('input[name="ownerEmail"]', WIZARD_OWNER_EMAIL);
    await adminPage.getByTestId("wizard-create").click();

    const result = adminPage.getByTestId("wizard-result");
    await expect(result).toBeVisible({ timeout: 60_000 });
    await expect(result).toContainText(WIZARD_TENANT_ID);
  });

  test("the runtime lists the tenant the wizard created", async () => {
    const tenants =
      await runtimeGet<{ id: string; name: string; version: number }[]>(
        "/internal/tenants",
      );

    const created = tenants.find((tenant) => tenant.id === WIZARD_TENANT_ID);
    expect(created).toBeDefined();
    expect(created!.name).toBe(WIZARD_ORG_NAME);
    expect(created!.version).toBeGreaterThanOrEqual(1);
  });

  test("the owner invitation is created for the address the wizard was given", async () => {
    await expect(adminPage.getByTestId("wizard-invitation")).toContainText(
      WIZARD_OWNER_EMAIL,
    );

    const org = await callOperation(adminPage, "/operations/get-organization", {
      slug: WIZARD_ORG_SLUG,
    });
    expect(org.status).toBe(200);
    expect(org.body.runtimeTenantId).toBe(WIZARD_TENANT_ID);
    expect(
      org.body.invitations.map(
        (invitation: { email: string }) => invitation.email,
      ),
    ).toContain(WIZARD_OWNER_EMAIL);
  });

  test("shows the numbers to buy and the channel to create as a checklist", async () => {
    const checklist = adminPage.getByTestId("wizard-checklist");

    await expect(checklist).toContainText("spatalk numbers add");
    await expect(checklist).toContainText(WIZARD_TENANT_ID);
    await expect(checklist).toContainText("docs/runbooks/accounts-and-env.md");
  });
});

test.describe("the onboarding wizard, from the basics", () => {
  test("creates a tenant in the runtime from a timezone, hours, a booking link and an owner", async () => {
    await adminPage.goto("/admin/tenants/new");
    await expect(
      adminPage.getByRole("heading", { name: "New tenant" }),
    ).toBeVisible(FIRST_RENDER);

    // Step 1: the organisation the client signs in to.
    await adminPage.fill('input[name="organizationName"]', BASICS_ORG_NAME);
    await adminPage.fill('input[name="organizationSlug"]', BASICS_ORG_SLUG);
    await adminPage.getByTestId("wizard-next").click();

    // Step 2: the basics, which is the default; Toronto and weekdays nine to
    // five are already filled in, Saturday is opened here.
    await expect(adminPage.getByTestId("wizard-mode-basics")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await adminPage.getByTestId("basics-sat-open").click();
    await adminPage.fill('[data-testid="basics-sat-start"]', "10:00");
    await adminPage.fill('[data-testid="basics-sat-end"]', "14:00");
    await adminPage.fill(
      '[data-testid="basics-booking-url"]',
      BASICS_BOOKING_URL,
    );
    await adminPage.fill('[data-testid="basics-public-phone"]', "+19055550199");
    await adminPage.fill('[data-testid="basics-assistant-name"]', "Mia");
    await adminPage.getByTestId("wizard-next").click();

    // Step 3: who owns it.
    await adminPage.fill('input[name="ownerEmail"]', BASICS_OWNER_EMAIL);
    await adminPage.fill('input[name="ownerName"]', "Dana");
    await adminPage.getByTestId("wizard-create").click();

    const result = adminPage.getByTestId("wizard-result");
    await expect(result).toBeVisible({ timeout: 60_000 });
    await expect(result).toContainText(BASICS_ORG_SLUG);
    await expect(adminPage.getByTestId("wizard-invitation")).toContainText(
      BASICS_OWNER_EMAIL,
    );
  });

  test("the runtime holds the starter configuration around the basics", async () => {
    const tenants =
      await runtimeGet<{ id: string; name: string; version: number }[]>(
        "/internal/tenants",
      );
    const created = tenants.find((tenant) => tenant.id === BASICS_ORG_SLUG);
    expect(created).toBeDefined();
    expect(created!.name).toBe(BASICS_ORG_NAME);
    expect(created!.version).toBe(1);

    const { config } = await runtimeGet<{ version: number; config: any }>(
      `/internal/tenants/${BASICS_ORG_SLUG}/config`,
    );
    expect(config.timezone).toBe("America/Toronto");
    expect(config.hours.mon).toEqual([["09:00", "17:00"]]);
    expect(config.hours.sat).toEqual([["10:00", "14:00"]]);
    expect(config.hours.sun).toEqual([]);
    expect(config.booking_url_default).toBe(BASICS_BOOKING_URL);
    expect(config.public_phone).toBe("+19055550199");
    expect(config.persona.assistant_name).toBe("Mia");
    expect(config.services).toEqual([]);
    expect(config.escalation.owner_email).toBe(BASICS_OWNER_EMAIL);
    expect(config.escalation.owner_name).toBe("Dana");
    // The staff mobile is named by an environment variable, never written.
    expect(config.delivery.destinations).toEqual([
      expect.objectContaining({ kind: "email", address: BASICS_OWNER_EMAIL }),
      expect.objectContaining({
        kind: "sms",
        address_env: "BASICS_PORTAL_E2E_STAFF_SMS",
      }),
    ]);
    // The wording is the starter's, placeholders and all, never a clinic's.
    expect(config.scripts.disclosure).toContain("{assistant_name}");
    expect(config.scripts.disclosure).not.toContain("Skincentrix");
  });

  test("the same address a second time is refused, and the tenant stays at version 1", async () => {
    const again = await callOperation(
      adminPage,
      "/operations/create-tenant-from-basics",
      {
        name: BASICS_ORG_NAME,
        slug: BASICS_ORG_SLUG,
        ownerEmail: BASICS_OWNER_EMAIL,
        ownerName: "",
        basics: {
          timezone: "America/Toronto",
          hours: { mon: [["09:00", "17:00"]] },
          bookingUrl: BASICS_BOOKING_URL,
          publicPhone: "",
          assistantName: "Ava",
        },
      },
    );
    expect(again.status).toBe(409);

    const tenants =
      await runtimeGet<{ id: string; version: number }[]>("/internal/tenants");
    expect(
      tenants.find((tenant) => tenant.id === BASICS_ORG_SLUG)!.version,
    ).toBe(1);
  });
});

test.describe("the tenants table", () => {
  test("lists every organisation with its runtime usage, items and config version", async () => {
    await adminPage.goto("/admin/tenants");
    await expect(
      adminPage.getByRole("heading", { name: "Tenants" }),
    ).toBeVisible(FIRST_RENDER);

    const row = adminPage.getByTestId(`tenant-row-${WIZARD_ORG_SLUG}`);
    await expect(row).toBeVisible(FIRST_RENDER);
    await expect(
      adminPage.getByTestId(`tenant-${WIZARD_ORG_SLUG}-version`),
    ).not.toHaveText("—");
    await expect(
      adminPage.getByTestId(`tenant-${WIZARD_ORG_SLUG}-calls`),
    ).toHaveText("0");
    await expect(
      adminPage.getByTestId(`tenant-${WIZARD_ORG_SLUG}-cost`),
    ).toContainText("$");
    await expect(
      adminPage.getByTestId(`tenant-${WIZARD_ORG_SLUG}-open`),
    ).toHaveText("0");
    // Nothing has been bought yet, so the agency's own revenue line says so.
    await expect(
      adminPage.getByTestId(`tenant-${WIZARD_ORG_SLUG}-subscription`),
    ).toContainText("No subscription");
  });

  test("says so when the runtime has never heard of an organisation's tenant", async () => {
    const created = await callOperation(
      adminPage,
      "/operations/create-organization",
      {
        name: "Not Yet Configured",
        slug: UNKNOWN_ORG_SLUG,
        runtimeTenantId: UNKNOWN_TENANT_ID,
      },
    );
    expect([200, 409]).toContain(created.status);

    await adminPage.goto("/admin/tenants");
    const cell = adminPage.getByTestId(`tenant-${UNKNOWN_ORG_SLUG}-version`);
    await expect(cell).toBeVisible(FIRST_RENDER);
    await expect(
      adminPage.getByTestId(`tenant-row-${UNKNOWN_ORG_SLUG}`),
    ).toContainText("Not configured");
  });

  test("sorts on the column that was clicked", async () => {
    await adminPage.goto("/admin/tenants");
    await expect(adminPage.getByTestId("tenants-table")).toBeVisible(
      FIRST_RENDER,
    );

    await adminPage.getByTestId("sort-name").click();
    const ascending = await adminPage
      .getByTestId("tenant-name")
      .allInnerTexts();
    await adminPage.getByTestId("sort-name").click();
    const descending = await adminPage
      .getByTestId("tenant-name")
      .allInnerTexts();

    expect(ascending.length).toBeGreaterThan(1);
    expect(descending).toEqual([...ascending].reverse());
  });
});

test.describe("the health page", () => {
  test("renders the runtime's queue numbers and the deployed commit", async () => {
    const health = await runtimeGet<{
      queued_jobs: number;
      dead_jobs: number;
    }>("/internal/health");

    await adminPage.goto("/admin/health");
    await expect(
      adminPage.getByRole("heading", { name: "Runtime health" }),
    ).toBeVisible(FIRST_RENDER);

    await expect(adminPage.getByTestId("health-queued-jobs")).toHaveText(
      String(health.queued_jobs),
    );
    await expect(adminPage.getByTestId("health-dead-jobs")).toHaveText(
      String(health.dead_jobs),
    );
    await expect(
      adminPage.getByTestId("health-oldest-queued-age"),
    ).toBeVisible();
    // The commit is empty unless the image was built with GIT_COMMIT, and the
    // page must say that rather than show a blank.
    await expect(adminPage.getByTestId("health-commit")).not.toBeEmpty();
    await expect(adminPage.getByTestId("health-tenants")).toContainText(
      WIZARD_TENANT_ID,
    );
  });
});

test.describe("the analytics page", () => {
  test("shows recurring revenue per tenant beside the template's own numbers", async () => {
    await adminPage.goto("/admin");
    await expect(adminPage.getByTestId("mrr-total")).toBeVisible(FIRST_RENDER);
    await expect(
      adminPage.getByTestId(`mrr-row-${WIZARD_ORG_SLUG}`),
    ).toContainText("No subscription");
  });
});
