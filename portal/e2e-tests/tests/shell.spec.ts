import { expect, test, type Page } from "@playwright/test";
import { checkoutSessionCompleted, postStripeEvent } from "./stripe";
import { agencyAdmin, callOperation, SERVER_URL, signInOrSignUp } from "./utils";

/**
 * The app shell (reskin plan, Task R1): the sidebar built from `nav.ts`, and
 * the settings tabs now that each one has a URL.
 *
 * The point of these tests is the two things a screenshot cannot show — that
 * the sidebar is reachable and operable from the keyboard alone, and that a
 * link to one settings tab opens that tab — plus the mobile sheet, which only
 * exists below the breakpoint.
 */

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

const ORG_NAME = "Skincentrix Shell";
const ORG_SLUG = "skincentrix-shell";
const RUNTIME_TENANT_ID = "skincentrix";

/** The Front desk and Setup items, in the order `nav.ts` puts them. */
const SIDEBAR_ORDER = [
  "nav-overview",
  "nav-conversations",
  "nav-requests",
  "nav-settings-hours",
  "nav-settings-services",
  "nav-settings-knowledge",
  "nav-settings-scripts",
  "nav-settings-delivery",
  "nav-settings-numbers",
  "nav-settings-integrations",
  "nav-settings-versions",
  "nav-billing",
  "nav-people",
];

let ownerPage: Page;

test.beforeAll(async ({ browser }) => {
  ownerPage = await browser.newPage();
  await signInOrSignUp({ page: ownerPage, user: agencyAdmin });

  let organizationId: string;
  const created = await callOperation(
    ownerPage,
    "/operations/create-organization",
    { name: ORG_NAME, slug: ORG_SLUG, runtimeTenantId: RUNTIME_TENANT_ID },
  );
  if (created.status === 200) {
    organizationId = created.body.id;
  } else {
    expect(created.status).toBe(409); // left behind by an earlier run
    const mine = await callOperation(
      ownerPage,
      "/operations/list-my-organizations",
    );
    organizationId = mine.body.find(
      (org: { slug: string }) => org.slug === ORG_SLUG,
    ).id;
  }

  const subscribed = await postStripeEvent(
    SERVER_URL,
    checkoutSessionCompleted({
      organizationId,
      stripeCustomerId: `cus_test_${ORG_SLUG}`,
      customerEmail: agencyAdmin.email,
    }),
  );
  expect([200, 204]).toContain(subscribed);
});

test.afterAll(async () => {
  await ownerPage.close();
});

test.describe("the sidebar", () => {
  test("carries every page an owner can open, and marks the one they are on", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/overview`);
    await expect(
      ownerPage.getByRole("heading", { name: "Overview" }),
    ).toBeVisible(FIRST_RENDER);

    for (const testId of SIDEBAR_ORDER) {
      await expect(ownerPage.getByTestId(testId)).toBeVisible();
    }

    // The agency admin is an admin as well as an owner here, and the platform
    // section is still not in this shell: a clinic's navigation is about the
    // clinic. The way back is the organisation switcher's last entry.
    await expect(ownerPage.getByTestId("nav-admin-tenants")).toHaveCount(0);
    await ownerPage.getByTestId("org-switcher").click();
    await expect(ownerPage.getByTestId("org-switcher-platform")).toBeVisible();
    await ownerPage.keyboard.press("Escape");

    await expect(ownerPage.getByTestId("nav-overview")).toHaveAttribute(
      "data-active",
      "true",
    );
    await expect(ownerPage.getByTestId("nav-requests")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  test("is reachable and operable from the keyboard alone", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/overview`);
    await expect(
      ownerPage.getByRole("heading", { name: "Overview" }),
    ).toBeVisible(FIRST_RENDER);

    // Tab from the top of the document and record what the focus lands on.
    await ownerPage.locator("body").click({ position: { x: 2, y: 2 } });
    const focused: string[] = [];
    for (let step = 0; step < 30; step += 1) {
      await ownerPage.keyboard.press("Tab");
      const testId = await ownerPage.evaluate(
        () => document.activeElement?.getAttribute("data-testid") ?? "",
      );
      if (testId) {
        focused.push(testId);
      }
    }

    // The organisation switcher comes first, because it is the top of the
    // sidebar, and the navigation follows it in the order `nav.ts` declares.
    expect(focused).toContain("org-switcher");
    const navOrder = focused.filter((testId) =>
      SIDEBAR_ORDER.includes(testId),
    );
    expect(navOrder).toEqual(SIDEBAR_ORDER.slice(0, navOrder.length));
    expect(navOrder.length).toBeGreaterThan(3);
    expect(focused.indexOf("org-switcher")).toBeLessThan(
      focused.indexOf("nav-overview"),
    );

    // Enter on a focused item goes there, exactly as a click would.
    await ownerPage.getByTestId("nav-requests").focus();
    await ownerPage.keyboard.press("Enter");
    await expect(ownerPage).toHaveURL(new RegExp(`/app/${ORG_SLUG}/requests$`));
    await expect(
      ownerPage.getByRole("heading", { name: "Requests" }),
    ).toBeVisible(FIRST_RENDER);
    await expect(ownerPage.getByTestId("nav-requests")).toHaveAttribute(
      "data-active",
      "true",
    );
  });

  test("opens the command palette from the header and closes it again", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/overview`);
    await ownerPage.getByTestId("command-palette-open").click();

    const palette = ownerPage.getByRole("dialog");
    await expect(palette).toBeVisible(FIRST_RENDER);
    await expect(palette).toContainText("Conversations");

    await ownerPage.keyboard.press("Escape");
    await expect(palette).toBeHidden();
  });

  test("is a sheet behind a trigger on a 390 px screen", async () => {
    await ownerPage.setViewportSize({ width: 390, height: 844 });
    try {
      await ownerPage.goto(`/app/${ORG_SLUG}/overview`);
      await expect(
        ownerPage.getByRole("heading", { name: "Overview" }),
      ).toBeVisible(FIRST_RENDER);

      // Nothing of the navigation is on the page until it is asked for…
      await expect(ownerPage.getByTestId("nav-requests")).toBeHidden();
      await ownerPage.getByTestId("sidebar-toggle").click();
      // …and then all of it is, in the sheet.
      await expect(ownerPage.getByTestId("nav-requests")).toBeVisible();

      await ownerPage.getByTestId("nav-requests").click();
      await expect(
        ownerPage.getByRole("heading", { name: "Requests" }),
      ).toBeVisible(FIRST_RENDER);
      // Choosing a page closes the sheet behind you.
      await expect(ownerPage.getByTestId("nav-requests")).toBeHidden();
    } finally {
      await ownerPage.setViewportSize({ width: 1280, height: 720 });
    }
  });
});

test.describe("the settings tabs", () => {
  test("open from the sidebar, and each one has its own URL", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/settings?tab=numbers`);
    await expect(ownerPage.getByTestId("numbers-tab")).toBeVisible(
      FIRST_RENDER,
    );
    await expect(ownerPage.getByTestId("nav-settings-numbers")).toHaveAttribute(
      "data-active",
      "true",
    );
    await expect(ownerPage.getByTestId("nav-settings-hours")).toHaveAttribute(
      "data-active",
      "false",
    );

    await ownerPage.getByTestId("nav-settings-versions").click();
    await expect(ownerPage).toHaveURL(/[?&]tab=versions/);
    await expect(ownerPage.getByTestId("config-versions")).toBeVisible(
      FIRST_RENDER,
    );

    // The buttons above the tab content write the same parameter, so the URL
    // and the tab never disagree about which one is open.
    await ownerPage.getByRole("button", { name: "Numbers" }).click();
    await expect(ownerPage).toHaveURL(/[?&]tab=numbers/);
    await expect(ownerPage.getByTestId("numbers-tab")).toBeVisible();
  });

  test("open on hours when the URL says nothing, as they always did", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/settings`);
    await expect(ownerPage.getByTestId("hours-mon-0-start")).toBeVisible(
      FIRST_RENDER,
    );
    await expect(ownerPage.getByTestId("nav-settings-hours")).toHaveAttribute(
      "data-active",
      "true",
    );
  });
});
