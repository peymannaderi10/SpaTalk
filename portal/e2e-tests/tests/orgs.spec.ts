import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "crypto";
import {
  agencyAdmin,
  callOperation,
  createRandomUser,
  logUserIn,
  signInOrSignUp,
  signUserUp,
  verifyUserEmail,
  type User,
} from "./utils";

/**
 * Organisations, memberships and invitations, end to end: the agency creates
 * an organisation, an owner invites someone, that person accepts from a second
 * browser and lands inside, and a staff member is refused the settings both in
 * the page and by the server behind it.
 */

test.describe.configure({ mode: "serial" });

/**
 * The app runs in development mode, so the first visit to a route waits for
 * Vite to compile that page. Five seconds is not always enough on a cold
 * route; every assertion that follows a first navigation uses this instead.
 */
const FIRST_RENDER = { timeout: 30_000 };

const suffix = randomUUID().slice(0, 8);
const ORG_NAME = `Skincentrix ${suffix}`;
const ORG_SLUG = `skincentrix-${suffix}`;
const RUNTIME_TENANT_ID = `skincentrix-${suffix}`;

let adminPage: Page;
let strangerPage: Page;
let staffPage: Page;
let staff: User;
let organizationId: string;
let inviteUrl: string;

test.beforeAll(async ({ browser }) => {
  // Three separate browser contexts: three separate sessions, as three
  // different people would have.
  adminPage = await browser.newPage();
  strangerPage = await browser.newPage();
  staffPage = await browser.newPage();
  staff = createRandomUser();
});

test.afterAll(async () => {
  await adminPage.close();
  await strangerPage.close();
  await staffPage.close();
});

test.describe("organisations", () => {
  test("an agency admin creates an organisation and opens it", async () => {
    await signInOrSignUp({ page: adminPage, user: agencyAdmin });

    const created = await callOperation(
      adminPage,
      "/operations/create-organization",
      {
        name: ORG_NAME,
        slug: ORG_SLUG,
        runtimeTenantId: RUNTIME_TENANT_ID,
      },
    );

    expect(created.status).toBe(200);
    expect(created.body.slug).toBe(ORG_SLUG);
    organizationId = created.body.id;

    await adminPage.goto("/app");
    await expect(
      adminPage.getByRole("link", { name: ORG_NAME }),
    ).toBeVisible(FIRST_RENDER);

    await adminPage.goto(`/app/${ORG_SLUG}`);
    await expect(
      adminPage.getByRole("heading", { name: ORG_NAME }),
    ).toBeVisible(FIRST_RENDER);
    await expect(adminPage.getByText(RUNTIME_TENANT_ID)).toBeVisible();
  });

  test("someone who is not a member is refused the organisation", async () => {
    const stranger = createRandomUser();
    await signUserUp({ page: strangerPage, user: stranger });
    await verifyUserEmail({ page: strangerPage, user: stranger });
    await logUserIn({ page: strangerPage, user: stranger });
    await strangerPage.waitForURL("**/app");

    await strangerPage.goto(`/app/${ORG_SLUG}`);
    // The page says "Loading…" while React Query retries the refused query a
    // few times before it settles on the error, so this waits longer than the
    // default five seconds.
    await expect(
      strangerPage.getByRole("heading", {
        name: "This organisation is not open to you",
      }),
    ).toBeVisible(FIRST_RENDER);

    const refused = await callOperation(
      strangerPage,
      "/operations/get-organization",
      { slug: ORG_SLUG },
    );
    expect(refused.status).toBe(403);
  });

  test("an owner invites a staff member and gets a single-use link", async () => {
    await adminPage.goto(`/app/${ORG_SLUG}/settings/people`);
    await expect(
      adminPage.getByRole("heading", { name: `People in ${ORG_NAME}` }),
    ).toBeVisible(FIRST_RENDER);

    // Inviting is the kit's dialog now, and the role a Radix select inside it,
    // so the native `select` this used to drive is gone.
    await adminPage.getByTestId("invite-member").click();
    await adminPage.fill('input[name="email"]', staff.email);
    await adminPage.getByTestId("invite-role").click();
    await adminPage.getByRole("option", { name: "STAFF" }).click();
    await adminPage.click('button:has-text("Send invitation")');

    const link = adminPage.getByTestId("invite-url");
    await expect(link).toBeVisible(FIRST_RENDER);
    inviteUrl = (await link.getAttribute("href")) ?? "";

    expect(inviteUrl).toContain("/invite/");
  });

  test("the invited person signs up from the link and lands in the organisation", async () => {
    // Signed out, the invitation names the organisation and the address it
    // was sent to, and parks the token for the trip through signup.
    await staffPage.goto(inviteUrl, { waitUntil: "domcontentloaded" });
    await expect(
      staffPage.getByRole("heading", { name: `You are invited to ${ORG_NAME}` }),
    ).toBeVisible(FIRST_RENDER);
    await expect(staffPage.getByText(staff.email)).toBeVisible();

    await signUserUp({ page: staffPage, user: staff });
    await verifyUserEmail({ page: staffPage, user: staff });
    await logUserIn({ page: staffPage, user: staff });

    // Signed in at last, the parked invitation brings them back to accept it.
    await staffPage.waitForURL("**/invite/**", FIRST_RENDER);
    await staffPage.click('button:has-text("Accept invitation")');

    await staffPage.waitForURL(`**/app/${ORG_SLUG}`);
    await expect(
      staffPage.getByRole("heading", { name: ORG_NAME }),
    ).toBeVisible(FIRST_RENDER);
    await expect(
      staffPage.getByText("STAFF", { exact: true }),
    ).toBeVisible();

    await staffPage.goto("/app");
    await expect(
      staffPage.getByRole("link", { name: ORG_NAME }),
    ).toBeVisible(FIRST_RENDER);
  });

  test("the same invitation cannot be accepted twice", async () => {
    const token = inviteUrl.split("/invite/")[1];

    const again = await callOperation(
      staffPage,
      "/operations/accept-invitation",
      { token },
    );

    expect(again.status).toBe(410);
  });

  test("a staff member cannot change who is in the organisation", async () => {
    await staffPage.goto(`/app/${ORG_SLUG}/settings/people`);
    await expect(
      staffPage.getByRole("heading", { name: "Settings are for owners" }),
    ).toBeVisible(FIRST_RENDER);

    // The refusal is the server's, not the page's.
    const refused = await callOperation(staffPage, "/operations/invite-member", {
      organizationId,
      email: `someone-${randomUUID()}@spatalk.test`,
      role: "STAFF",
    });
    expect(refused.status).toBe(403);

    const alsoRefused = await callOperation(
      staffPage,
      "/operations/remove-member",
      { organizationId, userId: "whoever" },
    );
    expect(alsoRefused.status).toBe(403);
  });

  test("only an agency admin creates an organisation", async () => {
    const refused = await callOperation(
      staffPage,
      "/operations/create-organization",
      {
        name: "Not allowed",
        slug: `not-allowed-${randomUUID().slice(0, 8)}`,
        runtimeTenantId: `not-allowed-${randomUUID().slice(0, 8)}`,
      },
    );

    expect(refused.status).toBe(403);
  });
});
