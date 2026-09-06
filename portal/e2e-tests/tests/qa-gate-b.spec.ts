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
 * QA gate B: switching organisations.
 *
 * The gate's portal row names "login, org switch". Logging in is covered by
 * `auth.spec.ts`; the switcher had no test at all, in this suite or in the
 * client one, so this is that proof: a person who belongs to two organisations
 * is offered exactly those two, and picking the other one lands on its pages.
 *
 * The switcher moved with the reskin (Task R1) from a `select` in the
 * navigation bar to a menu at the top of the sidebar, so the three assertions
 * that read `option` elements now open the menu instead. What they assert is
 * unchanged, and `aria-label="Organisation"` came with it.
 *
 * It is also the second half of the authorisation row from the client's side.
 * `orgs.spec.ts` proves a stranger is refused one organisation; here a member
 * of two is never even offered a third that exists in the same database.
 */

test.describe.configure({ mode: "serial" });

const FIRST_RENDER = { timeout: 30_000 };

const suffix = randomUUID().slice(0, 8);

const FIRST = {
  name: `Aurora Skin ${suffix}`,
  slug: `aurora-skin-${suffix}`,
  tenant: `aurora-skin-${suffix}`,
};
const SECOND = {
  name: `Bayview Laser ${suffix}`,
  slug: `bayview-laser-${suffix}`,
  tenant: `bayview-laser-${suffix}`,
};
/** An organisation the client is never invited to. */
const UNRELATED = {
  name: `Cedar Clinic ${suffix}`,
  slug: `cedar-clinic-${suffix}`,
  tenant: `cedar-clinic-${suffix}`,
};

let adminPage: Page;
let clientPage: Page;
let client: User;
const invitationTokens: string[] = [];

test.beforeAll(async ({ browser }) => {
  adminPage = await browser.newPage();
  clientPage = await browser.newPage();
  client = createRandomUser();
});

test.afterAll(async () => {
  await adminPage.close();
  await clientPage.close();
});

test.describe("switching between organisations", () => {
  test("a client is invited into two of the three organisations that exist", async () => {
    await signInOrSignUp({ page: adminPage, user: agencyAdmin });

    for (const org of [FIRST, SECOND, UNRELATED]) {
      const created = await callOperation(
        adminPage,
        "/operations/create-organization",
        { name: org.name, slug: org.slug, runtimeTenantId: org.tenant },
      );
      expect(created.status).toBe(200);
    }

    for (const org of [FIRST, SECOND]) {
      const invited = await callOperation(adminPage, "/operations/invite-member", {
        organizationId: (
          await callOperation(adminPage, "/operations/get-organization", {
            slug: org.slug,
          })
        ).body.id,
        email: client.email,
        role: "STAFF",
      });
      expect(invited.status).toBe(200);
      const url: string = invited.body.inviteUrl;
      expect(url).toContain("/invite/");
      invitationTokens.push(url.split("/invite/")[1]);
    }
    expect(invitationTokens).toHaveLength(2);
  });

  test("the switcher offers exactly the organisations that person belongs to", async () => {
    await signUserUp({ page: clientPage, user: client });
    await verifyUserEmail({ page: clientPage, user: client });
    await logUserIn({ page: clientPage, user: client });
    await clientPage.waitForURL("**/app");

    for (const token of invitationTokens) {
      const accepted = await callOperation(
        clientPage,
        "/operations/accept-invitation",
        { token },
      );
      expect(accepted.status).toBe(200);
    }

    await clientPage.goto(`/app/${FIRST.slug}`);
    await expect(
      clientPage.getByRole("heading", { name: FIRST.name }),
    ).toBeVisible(FIRST_RENDER);

    const switcher = clientPage.getByTestId("org-switcher");
    await expect(switcher).toBeVisible();
    await expect(clientPage.getByLabel("Organisation")).toBeVisible();

    await switcher.click();
    const offered = await clientPage
      .getByRole("menuitem")
      .allTextContents();
    expect(offered).toContain(FIRST.name);
    expect(offered).toContain(SECOND.name);
    // The third organisation exists, and is none of this person's business.
    expect(offered).not.toContain(UNRELATED.name);
    await clientPage.keyboard.press("Escape");
    // Radix keeps the closing menu mounted for its exit animation, and a
    // click on the trigger inside that window is swallowed by the departing
    // layer (seen 2026-09-06); the next test opens it again, so wait it out.
    await expect(clientPage.getByRole("menu")).toHaveCount(0);
  });

  test("picking the other one lands on its pages", async () => {
    await clientPage.getByTestId("org-switcher").click();
    await clientPage.getByTestId(`org-switcher-${SECOND.slug}`).click();

    await clientPage.waitForURL(`**/app/${SECOND.slug}`, FIRST_RENDER);
    await expect(
      clientPage.getByRole("heading", { name: SECOND.name }),
    ).toBeVisible(FIRST_RENDER);
    await expect(
      clientPage.getByRole("heading", { name: FIRST.name }),
    ).toHaveCount(0);
    await expect(clientPage.getByTestId("org-switcher")).toContainText(
      SECOND.name,
    );
  });

  test("the organisation it was never offered stays refused by the server", async () => {
    await clientPage.goto(`/app/${UNRELATED.slug}`);
    await expect(
      clientPage.getByRole("heading", {
        name: "This organisation is not open to you",
      }),
    ).toBeVisible(FIRST_RENDER);

    const refused = await callOperation(
      clientPage,
      "/operations/get-organization",
      { slug: UNRELATED.slug },
    );
    expect(refused.status).toBe(403);
  });
});
