import { expect, test, type Page } from "@playwright/test";
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
import {
  auditRows,
  itemState,
  runtimeGet,
  seed,
  waitForConfigVersion,
  type Seed,
} from "./runtime";

/**
 * The client pages, end to end, against a running runtime seeded by
 * `global-setup.ts`: what the overview counts, what the conversations list
 * labels and audits, what the requests page does to an item's state, and what
 * saving and rolling back settings does to the tenant's configuration.
 *
 * Every number asserted here came out of the runtime; the portal stores none of
 * it (CLAUDE.md non-negotiable 7).
 */

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

const ORG_NAME = "Skincentrix Client";
const ORG_SLUG = "skincentrix-client";
const RUNTIME_TENANT_ID = "skincentrix";

let ownerPage: Page;
let staffPage: Page;
let staff: User;
let organizationId: string;

// Read inside `beforeAll`, not at module load: Playwright collects the tests in
// a spec file before `globalSetup` has written the fixture ids.
let fixtures: Seed;
let overdueItemId: number;
let bookingItemId: number;

test.beforeAll(async ({ browser }) => {
  fixtures = seed();
  [overdueItemId, bookingItemId] = fixtures.item_ids;

  ownerPage = await browser.newPage();
  staffPage = await browser.newPage();
  staff = createRandomUser();

  await signInOrSignUp({ page: ownerPage, user: agencyAdmin });

  // The agency admin acts as an owner of every organisation, so this one page
  // covers the owner behaviours; the staff behaviours need a real member.
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
});

test.afterAll(async () => {
  await ownerPage.close();
  await staffPage.close();
});

test.describe("the overview", () => {
  test("shows this month's counts from the runtime", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/overview`);
    await expect(
      ownerPage.getByRole("heading", { name: "Overview" }),
    ).toBeVisible(FIRST_RENDER);

    await expect(ownerPage.getByTestId("tile-calls")).toHaveText("2");
    await expect(ownerPage.getByTestId("tile-call-minutes")).toHaveText("6.0");
    await expect(ownerPage.getByTestId("tile-texts")).toHaveText("4");
    await expect(ownerPage.getByTestId("tile-chats")).toHaveText("1");
    await expect(ownerPage.getByTestId("tile-open-items")).toHaveText("3");
    await expect(ownerPage.getByTestId("tile-overdue-items")).toHaveText("1");
    await expect(ownerPage.getByTestId("tile-p95-latency")).toContainText("ms");
    await expect(ownerPage.getByTestId("tile-est-cost")).toContainText("$");
  });

  test("draws a thirty-day usage chart", async () => {
    await expect(ownerPage.getByTestId("usage-chart")).toBeVisible(
      FIRST_RENDER,
    );
    await expect(ownerPage.getByTestId("usage-chart-days")).toHaveText("30");
  });

  test("lists the overdue item as needing attention", async () => {
    const list = ownerPage.getByTestId("needs-attention");
    await expect(list).toContainText(`#${overdueItemId}`);
    await expect(list).toContainText("Dana W");
    await expect(list).toContainText("Overdue");
  });
});

test.describe("the conversations page", () => {
  test("labels the band and flags health context", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/conversations`);
    await expect(
      ownerPage.getByRole("heading", { name: "Conversations" }),
    ).toBeVisible(FIRST_RENDER);

    await expect(ownerPage.getByTestId("conversation-row")).toHaveCount(4);
    await expect(ownerPage.getByText("handled", { exact: true })).toHaveCount(
      1,
    );
    await expect(
      ownerPage.getByText("sent to team", { exact: true }),
    ).toHaveCount(2);
    await expect(
      ownerPage.getByText("to a person", { exact: true }),
    ).toHaveCount(1);
    await expect(ownerPage.getByTestId("health-badge")).toHaveCount(1);
    // A list never shows a whole phone number.
    await expect(ownerPage.getByText("***0101")).toBeVisible();
    await expect(ownerPage.getByText("+19055550101")).toHaveCount(0);
  });

  test("narrows the list to one channel", async () => {
    await ownerPage.selectOption('select[aria-label="Channel"]', "sms");
    await expect(ownerPage.getByTestId("conversation-row")).toHaveCount(1);
    await ownerPage.selectOption('select[aria-label="Channel"]', "");
    await expect(ownerPage.getByTestId("conversation-row")).toHaveCount(4);
  });

  test("opening a transcript writes an audit row naming the reader", async () => {
    const before = await auditRows("conversation", fixtures.conversations.handled);

    await ownerPage
      .getByTestId("conversation-row")
      .filter({ hasText: "***0101" })
      .click();

    const drawer = ownerPage.getByTestId("transcript-drawer");
    await expect(drawer).toBeVisible(FIRST_RENDER);
    await expect(drawer).toContainText("How much is a hydrafacial?");

    await expect
      .poll(
        async () =>
          (await auditRows("conversation", fixtures.conversations.handled))
            .length,
        { timeout: 15_000 },
      )
      .toBe(before.length + 1);

    const rows = await auditRows(
      "conversation",
      fixtures.conversations.handled,
    );
    const written = rows[rows.length - 1];
    expect(written.action).toBe("read_transcript");
    expect(written.actor).toBe(`portal:${agencyAdmin.email}`);
  });
});

test.describe("the requests page", () => {
  test("shows what is open and what has been acknowledged", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/requests`);
    await expect(
      ownerPage.getByRole("heading", { name: "Requests" }),
    ).toBeVisible(FIRST_RENDER);
    await expect(ownerPage.getByTestId("request-row")).toHaveCount(3);

    await ownerPage.getByRole("button", { name: "Resolved" }).click();
    await expect(ownerPage.getByTestId("request-row")).toHaveCount(1);
    await ownerPage.getByRole("button", { name: "Open" }).click();
    await expect(ownerPage.getByTestId("request-row")).toHaveCount(3);
  });

  test("acknowledging a request changes its state in the runtime", async () => {
    await ownerPage.getByTestId(`acknowledge-${bookingItemId}`).click();
    await expect
      .poll(async () => (await itemState(bookingItemId)).state, {
        timeout: 15_000,
      })
      .toBe("acknowledged");
    // The item records the person; the audit row records the channel they
    // came through (`portal:<email>`).
    expect((await itemState(bookingItemId)).acknowledged_by).toBe(
      agencyAdmin.email,
    );
  });

  test("resolving a request moves it out of the open list", async () => {
    await ownerPage.getByTestId(`resolve-${bookingItemId}`).click();
    await expect
      .poll(async () => (await itemState(bookingItemId)).state, {
        timeout: 15_000,
      })
      .toBe("resolved");
    expect((await itemState(bookingItemId)).resolved_by).toBe(
      agencyAdmin.email,
    );

    await expect(ownerPage.getByTestId("request-row")).toHaveCount(2);
    await ownerPage.getByRole("button", { name: "Resolved" }).click();
    await expect(ownerPage.getByTestId("request-row")).toHaveCount(2);
  });
});

test.describe("the settings page", () => {
  test("saving hours writes a new configuration version the runtime serves", async () => {
    await ownerPage.goto(`/app/${ORG_SLUG}/settings`);
    await expect(
      ownerPage.getByRole("heading", { name: "Settings" }),
    ).toBeVisible(FIRST_RENDER);

    const monday = ownerPage.getByTestId("hours-mon-0-start");
    await expect(monday).toHaveValue("12:00");
    await monday.fill("09:00");
    await ownerPage.getByRole("button", { name: "Save settings" }).click();

    await expect(ownerPage.getByTestId("settings-saved")).toBeVisible(
      FIRST_RENDER,
    );
    await waitForConfigVersion(RUNTIME_TENANT_ID, 2);

    const config = await runtimeGet<{ version: number; config: any }>(
      `/internal/tenants/${RUNTIME_TENANT_ID}/config`,
    );
    expect(config.version).toBe(2);
    expect(config.config.hours.mon[0][0]).toBe("09:00");
  });

  test("an invalid configuration is refused with the field named", async () => {
    await ownerPage.getByTestId("hours-mon-0-start").fill("23:00");
    await ownerPage.getByRole("button", { name: "Save settings" }).click();

    await expect(ownerPage.getByTestId("field-error-hours")).toBeVisible(
      FIRST_RENDER,
    );
    const config = await runtimeGet<{ version: number }>(
      `/internal/tenants/${RUNTIME_TENANT_ID}/config`,
    );
    expect(config.version).toBe(2);
  });

  test("rolling back restores the previous configuration", async () => {
    await ownerPage.getByRole("button", { name: "Versions" }).click();
    await expect(ownerPage.getByTestId("config-versions")).toContainText(
      "Version 2",
    );

    await ownerPage.getByTestId("rollback-1").click();
    await waitForConfigVersion(RUNTIME_TENANT_ID, 3);

    const config = await runtimeGet<{ version: number; config: any }>(
      `/internal/tenants/${RUNTIME_TENANT_ID}/config`,
    );
    expect(config.version).toBe(3);
    expect(config.config.hours.mon[0][0]).toBe("12:00");
  });

  test("the numbers tab is read only", async () => {
    await ownerPage.getByRole("button", { name: "Numbers" }).click();
    await expect(ownerPage.getByTestId("numbers-tab")).toContainText(
      "+19055550100",
    );
    await expect(ownerPage.getByTestId("numbers-tab")).toContainText(
      "+18885550100",
    );
  });
});

test.describe("a staff member", () => {
  test("joins the organisation from an invitation", async () => {
    const invitation = await callOperation(
      ownerPage,
      "/operations/invite-member",
      { organizationId, email: staff.email, role: "STAFF" },
    );
    expect(invitation.status).toBe(200);

    await signUserUp({ page: staffPage, user: staff });
    await verifyUserEmail({ page: staffPage, user: staff });
    await logUserIn({ page: staffPage, user: staff });
    await staffPage.waitForURL("**/app");

    const accepted = await callOperation(
      staffPage,
      "/operations/accept-invitation",
      { token: invitation.body.inviteUrl.split("/invite/")[1] },
    );
    expect(accepted.status).toBe(200);
  });

  test("sees the requests page", async () => {
    await staffPage.goto(`/app/${ORG_SLUG}/requests`);
    await expect(
      staffPage.getByRole("heading", { name: "Requests" }),
    ).toBeVisible(FIRST_RENDER);
    await expect(staffPage.getByTestId("request-row")).toHaveCount(2);
  });

  test("cannot save settings, in the page or on the server", async () => {
    await staffPage.goto(`/app/${ORG_SLUG}/settings`);
    await expect(
      staffPage.getByRole("heading", { name: "Settings" }),
    ).toBeVisible(FIRST_RENDER);
    await expect(
      staffPage.getByRole("button", { name: "Save settings" }),
    ).toHaveCount(0);

    const refused = await callOperation(
      staffPage,
      "/operations/save-tenant-config",
      { slug: ORG_SLUG, config: { id: RUNTIME_TENANT_ID } },
    );
    expect(refused.status).toBe(403);

    const rolledBack = await callOperation(
      staffPage,
      "/operations/roll-back-tenant-config",
      { slug: ORG_SLUG, version: 1 },
    );
    expect(rolledBack.status).toBe(403);
  });
});
