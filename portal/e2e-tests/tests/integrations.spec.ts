import { expect, test, type Page } from "@playwright/test";
import { Client } from "pg";
import { checkoutSessionCompleted, postStripeEvent } from "./stripe";
import { auditRows, DATABASE_URL, runtimeGet } from "./runtime";
import {
  agencyAdmin,
  callOperation,
  createRandomUser,
  logUserIn,
  SERVER_URL,
  signInOrSignUp,
  signUserUp,
  verifyUserEmail,
} from "./utils";

/**
 * The Integrations tab (instagram plan, Task D4), end to end against a running
 * runtime.
 *
 * The portal keeps no record of a Meta connection and never calls Meta: the
 * card is drawn from the runtime's `/internal/tenants/{id}/integrations`, and
 * Disconnect is the runtime deleting the row and its token. So the fixture here
 * is a row in the *runtime's* schema, and what the test checks afterwards is
 * that the same row is gone (CLAUDE.md non-negotiable 7).
 *
 * Nothing here reaches Instagram or Facebook. The seeded token is deliberately
 * unreadable ciphertext: the runtime cannot use it to call Meta, which is
 * exactly the case where a disconnect must still remove the connection.
 */

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

const ORG_NAME = "Skincentrix Client";
const ORG_SLUG = "skincentrix-client";
const RUNTIME_TENANT_ID = "skincentrix";
const IG_USER_ID = "17841400000000000";
const IG_USERNAME = "skincentrix";

let ownerPage: Page;

async function runtimeSql<T = any>(
  sql: string,
  values: unknown[] = [],
): Promise<T[]> {
  const client = new Client({ connectionString: DATABASE_URL });
  await client.connect();
  try {
    const { rows } = await client.query(sql, values);
    return rows as T[];
  } finally {
    await client.end();
  }
}

/** The connected Instagram account this tab is supposed to render. */
async function seedIntegration(): Promise<void> {
  await runtimeSql(
    `insert into runtime.tenant_integrations
       (tenant_id, provider, external_id, display_name, access_token_enc,
        token_expires_at, scopes, needs_reconnect, connected_by, created_at, updated_at)
     values ($1, 'instagram', $2, $3, 'e2e-not-a-readable-token',
        now() + interval '60 days', ARRAY['instagram_business_basic']::text[], false,
        'e2e-seed', now(), now())
     on conflict (tenant_id, provider) do update set
        external_id = excluded.external_id,
        display_name = excluded.display_name,
        access_token_enc = excluded.access_token_enc,
        token_expires_at = excluded.token_expires_at,
        needs_reconnect = false,
        updated_at = now()`,
    [RUNTIME_TENANT_ID, IG_USER_ID, IG_USERNAME],
  );
}

async function integrationRows(): Promise<{ provider: string }[]> {
  return runtimeSql(
    "select provider from runtime.tenant_integrations where tenant_id = $1",
    [RUNTIME_TENANT_ID],
  );
}

test.beforeAll(async ({ browser }) => {
  ownerPage = await browser.newPage();
  await signInOrSignUp({ page: ownerPage, user: agencyAdmin });

  const created = await callOperation(
    ownerPage,
    "/operations/create-organization",
    { name: ORG_NAME, slug: ORG_SLUG, runtimeTenantId: RUNTIME_TENANT_ID },
  );
  let organizationId: string;
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

  // Settings needs a live subscription (portal plan, Task C6).
  const subscribed = await postStripeEvent(
    SERVER_URL,
    checkoutSessionCompleted({
      organizationId,
      stripeCustomerId: `cus_test_${ORG_SLUG}`,
      customerEmail: agencyAdmin.email,
    }),
  );
  expect(subscribed).toBe(204);

  await runtimeSql("delete from runtime.tenant_integrations where tenant_id = $1", [
    RUNTIME_TENANT_ID,
  ]);
});

test.afterAll(async () => {
  await runtimeSql("delete from runtime.tenant_integrations where tenant_id = $1", [
    RUNTIME_TENANT_ID,
  ]);
  await ownerPage.close();
});

async function openIntegrations(page: Page, query = ""): Promise<void> {
  await page.goto(`/app/${ORG_SLUG}/settings${query}`);
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible(
    FIRST_RENDER,
  );
  await page.getByRole("button", { name: "Integrations", exact: true }).click();
  await expect(page.getByTestId("integrations-tab")).toBeVisible(FIRST_RENDER);
}

test("both cards say Not connected until an account is connected", async () => {
  await openIntegrations(ownerPage);

  await expect(ownerPage.getByTestId("integration-instagram-status")).toHaveText(
    "Not connected",
  );
  await expect(ownerPage.getByTestId("integration-messenger-status")).toHaveText(
    "Not connected",
  );
  await expect(
    ownerPage.getByTestId("integration-instagram-disconnect"),
  ).toHaveCount(0);
});

test("the status renders from a seeded integration", async () => {
  await seedIntegration();
  await openIntegrations(ownerPage);

  await expect(ownerPage.getByTestId("integration-instagram-status")).toHaveText(
    `Connected as ${IG_USERNAME}`,
    FIRST_RENDER,
  );
  await expect(ownerPage.getByTestId("integration-instagram")).toContainText(
    "renewed automatically",
  );
  // The other provider is untouched by the Instagram row.
  await expect(ownerPage.getByTestId("integration-messenger-status")).toHaveText(
    "Not connected",
  );
});

test("the status never carries the token to the browser", async () => {
  await openIntegrations(ownerPage);

  const shown = await ownerPage.getByTestId("integration-instagram").innerText();
  expect(shown).not.toContain("e2e-not-a-readable-token");

  const status = await callOperation(
    ownerPage,
    "/operations/get-tenant-integrations",
    { slug: ORG_SLUG },
  );
  expect(status.status).toBe(200);
  expect(JSON.stringify(status.body)).not.toContain("access_token");
  expect(JSON.stringify(status.body)).not.toContain("e2e-not-a-readable-token");
});

test("Disconnect calls the API and the card returns to Not connected", async () => {
  await openIntegrations(ownerPage);
  await expect(ownerPage.getByTestId("integration-instagram-status")).toHaveText(
    `Connected as ${IG_USERNAME}`,
    FIRST_RENDER,
  );

  await ownerPage.getByTestId("integration-instagram-disconnect").click();

  await expect(ownerPage.getByTestId("integration-instagram-status")).toHaveText(
    "Not connected",
    FIRST_RENDER,
  );
  await expect(
    ownerPage.getByTestId("integration-instagram-disconnect"),
  ).toHaveCount(0);

  // The runtime is the one that had the connection, so it is the one asked.
  expect(await integrationRows()).toEqual([]);
  const audited = await auditRows("tenant", RUNTIME_TENANT_ID);
  expect(
    audited.some(
      (row) =>
        row.action === "integration_disconnect" &&
        row.actor === `portal:${agencyAdmin.email}`,
    ),
  ).toBe(true);

  const status = await runtimeGet<{ provider: string; connected: boolean }[]>(
    `/internal/tenants/${RUNTIME_TENANT_ID}/integrations`,
  );
  expect(status.every((row) => row.connected === false)).toBe(true);
});

test("Connect asks the runtime for a signed Instagram authorisation url", async () => {
  const answer = await callOperation(
    ownerPage,
    "/operations/start-integration-connect",
    { slug: ORG_SLUG, provider: "instagram" },
  );

  expect(answer.status).toBe(200);
  const url = new URL(answer.body.url);
  expect(`${url.origin}${url.pathname}`).toBe(
    "https://www.instagram.com/oauth/authorize",
  );
  expect(url.searchParams.get("scope")).toContain(
    "instagram_business_manage_messages",
  );
  // The state is opaque to the portal, and it is what brings the browser back.
  expect(url.searchParams.get("state")).toBeTruthy();
  expect(answer.body.expiresIn).toBe(15 * 60);
});

test("a Page choice handed back by the connect flow is rendered", async () => {
  const pages = JSON.stringify([
    { id: "111", name: "Skincentrix Mississauga" },
    { id: "222", name: "Skincentrix Oakville" },
  ]);
  await openIntegrations(
    ownerPage,
    `?messenger_pending=handle-abc&messenger_pages=${encodeURIComponent(pages)}`,
  );

  await expect(ownerPage.getByTestId("messenger-page-choice")).toBeVisible();
  await expect(ownerPage.getByTestId("messenger-page-111")).toHaveText(
    "Skincentrix Mississauga",
  );
  await expect(ownerPage.getByTestId("messenger-page-222")).toHaveText(
    "Skincentrix Oakville",
  );
});

test("someone outside the organisation cannot read or remove its connections", async () => {
  const outsider = createRandomUser();
  const page = await ownerPage.context().browser()!.newPage();
  try {
    await signUserUp({ page, user: outsider });
    await verifyUserEmail({ page, user: outsider });
    await logUserIn({ page, user: outsider });
    await page.waitForURL("**/app");

    for (const path of [
      "/operations/get-tenant-integrations",
      "/operations/disconnect-integration",
      "/operations/start-integration-connect",
    ]) {
      const refused = await callOperation(page, path, {
        slug: ORG_SLUG,
        provider: "instagram",
      });
      expect(refused.status).toBeGreaterThanOrEqual(400);
    }
  } finally {
    await page.close();
  }
});
