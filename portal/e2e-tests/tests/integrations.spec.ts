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
 * The Integrations tab (instagram plan, Task D4; Slack one-click connect,
 * onboarding roadmap section 3), end to end against a running runtime.
 *
 * The portal keeps no record of a connection and never calls Meta or Slack:
 * the card is drawn from the runtime's `/internal/tenants/{id}/integrations`,
 * and Disconnect is the runtime deleting the row and its token. So the fixture
 * here is a row in the *runtime's* schema, and what the test checks afterwards
 * is that the same row is gone (CLAUDE.md non-negotiable 7).
 *
 * Nothing here reaches Instagram, Facebook or Slack. The seeded tokens are
 * deliberately unreadable ciphertext: the runtime cannot use them to call the
 * provider, which is exactly the case where a disconnect must still remove
 * the connection.
 */

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

const ORG_NAME = "Skincentrix Client";
const ORG_SLUG = "skincentrix-client";
const RUNTIME_TENANT_ID = "skincentrix";
const IG_USER_ID = "17841400000000000";
const IG_USERNAME = "skincentrix";
const SLACK_TEAM_ID = "T0E2E0001";
const SLACK_DISPLAY = "Skincentrix · #front-desk";

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

/** A Slack workspace the clinic connected: channel and webhook stored, both unreadable here. */
async function seedSlackIntegration(): Promise<void> {
  await runtimeSql(
    `insert into runtime.tenant_integrations
       (tenant_id, provider, external_id, display_name, access_token_enc,
        token_expires_at, scopes, needs_reconnect, connected_by, created_at, updated_at,
        channel_id, webhook_url_enc)
     values ($1, 'slack', $2, $3, 'e2e-not-a-readable-token',
        null, ARRAY['incoming-webhook', 'chat:write']::text[], false,
        'e2e-seed', now(), now(), 'C0E2E0001', 'e2e-not-a-readable-webhook')
     on conflict (tenant_id, provider) do update set
        external_id = excluded.external_id,
        display_name = excluded.display_name,
        access_token_enc = excluded.access_token_enc,
        channel_id = excluded.channel_id,
        webhook_url_enc = excluded.webhook_url_enc,
        needs_reconnect = false,
        updated_at = now()`,
    [RUNTIME_TENANT_ID, SLACK_TEAM_ID, SLACK_DISPLAY],
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

  await runtimeSql(
    "delete from runtime.tenant_integrations where tenant_id = $1",
    [RUNTIME_TENANT_ID],
  );
});

test.afterAll(async () => {
  await runtimeSql(
    "delete from runtime.tenant_integrations where tenant_id = $1",
    [RUNTIME_TENANT_ID],
  );
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

test("every card says Not connected until something is connected", async () => {
  await openIntegrations(ownerPage);

  await expect(
    ownerPage.getByTestId("integration-instagram-status"),
  ).toHaveText("Not connected");
  await expect(
    ownerPage.getByTestId("integration-messenger-status"),
  ).toHaveText("Not connected");
  await expect(ownerPage.getByTestId("integration-slack-status")).toHaveText(
    "Not connected",
  );
  await expect(
    ownerPage.getByTestId("integration-instagram-disconnect"),
  ).toHaveCount(0);
  await expect(
    ownerPage.getByTestId("integration-slack-disconnect"),
  ).toHaveCount(0);
});

test("the status renders from a seeded integration", async () => {
  await seedIntegration();
  await openIntegrations(ownerPage);

  await expect(
    ownerPage.getByTestId("integration-instagram-status"),
  ).toHaveText(`Connected as ${IG_USERNAME}`, FIRST_RENDER);
  await expect(ownerPage.getByTestId("integration-instagram")).toContainText(
    "renewed automatically",
  );
  // The other provider is untouched by the Instagram row.
  await expect(
    ownerPage.getByTestId("integration-messenger-status"),
  ).toHaveText("Not connected");
});

test("the status never carries the token to the browser", async () => {
  await openIntegrations(ownerPage);

  const shown = await ownerPage
    .getByTestId("integration-instagram")
    .innerText();
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
  await expect(
    ownerPage.getByTestId("integration-instagram-status"),
  ).toHaveText(`Connected as ${IG_USERNAME}`, FIRST_RENDER);

  await ownerPage.getByTestId("integration-instagram-disconnect").click();

  await expect(
    ownerPage.getByTestId("integration-instagram-status"),
  ).toHaveText("Not connected", FIRST_RENDER);
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

// ----- the Slack card (onboarding roadmap, section 3) -----------------------------

test("the Slack status renders from a seeded workspace, with nothing secret", async () => {
  await seedSlackIntegration();
  await openIntegrations(ownerPage);

  await expect(ownerPage.getByTestId("integration-slack-status")).toHaveText(
    `Connected as ${SLACK_DISPLAY}`,
    FIRST_RENDER,
  );
  await expect(ownerPage.getByTestId("integration-slack")).toContainText(
    "Connected by e2e-seed",
  );
  await expect(ownerPage.getByTestId("integration-slack-invite")).toBeVisible();
  // A bot token is not renewed like a Meta token; the card must not claim it is.
  await expect(ownerPage.getByTestId("integration-slack")).not.toContainText(
    "renewed automatically",
  );
  // The Meta cards are untouched by the Slack row.
  await expect(
    ownerPage.getByTestId("integration-instagram-status"),
  ).toHaveText("Not connected");

  const shown = await ownerPage.getByTestId("integration-slack").innerText();
  expect(shown).not.toContain("e2e-not-a-readable-token");
  expect(shown).not.toContain("e2e-not-a-readable-webhook");
  expect(shown).not.toContain("C0E2E0001");

  const status = await callOperation(
    ownerPage,
    "/operations/get-tenant-integrations",
    { slug: ORG_SLUG },
  );
  expect(status.status).toBe(200);
  const body = JSON.stringify(status.body);
  expect(body).not.toContain("access_token");
  expect(body).not.toContain("webhook_url");
  expect(body).not.toContain("channel_id");
  expect(body).not.toContain("e2e-not-a-readable-token");
  expect(body).not.toContain("e2e-not-a-readable-webhook");
});

test("Disconnect removes the Slack workspace and the card returns to Not connected", async () => {
  await openIntegrations(ownerPage);
  await expect(ownerPage.getByTestId("integration-slack-status")).toHaveText(
    `Connected as ${SLACK_DISPLAY}`,
    FIRST_RENDER,
  );

  await ownerPage.getByTestId("integration-slack-disconnect").click();

  await expect(ownerPage.getByTestId("integration-slack-status")).toHaveText(
    "Not connected",
    FIRST_RENDER,
  );
  await expect(
    ownerPage.getByTestId("integration-slack-disconnect"),
  ).toHaveCount(0);

  // The runtime had the row (and the unreadable token, which it could not
  // revoke); the disconnect still removes it.
  expect(await integrationRows()).toEqual([]);
  const audited = await auditRows("tenant", RUNTIME_TENANT_ID);
  expect(
    audited.filter(
      (row) =>
        row.action === "integration_disconnect" &&
        row.actor === `portal:${agencyAdmin.email}`,
    ).length,
  ).toBeGreaterThanOrEqual(2);
});

test("Connect asks the runtime for a signed Slack authorisation url", async () => {
  const status = await callOperation(
    ownerPage,
    "/operations/get-tenant-integrations",
    { slug: ORG_SLUG },
  );
  const slack = status.body.integrations.find(
    (row: { provider: string }) => row.provider === "slack",
  );
  test.skip(
    slack?.configured !== true,
    "SLACK_CLIENT_ID and SLACK_CLIENT_SECRET are not set on this runtime",
  );

  const answer = await callOperation(
    ownerPage,
    "/operations/start-integration-connect",
    { slug: ORG_SLUG, provider: "slack" },
  );

  expect(answer.status).toBe(200);
  const url = new URL(answer.body.url);
  expect(`${url.origin}${url.pathname}`).toBe(
    "https://slack.com/oauth/v2/authorize",
  );
  expect(url.searchParams.get("scope")).toContain("chat:write");
  expect(url.searchParams.get("scope")).toContain("incoming-webhook");
  expect(url.searchParams.get("redirect_uri")).toMatch(/\/slack\/callback$/);
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
    `?messenger_pending=handle-abc&messenger_pages=${encodeURIComponent(
      pages,
    )}`,
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

    for (const provider of ["instagram", "slack"]) {
      for (const path of [
        "/operations/get-tenant-integrations",
        "/operations/disconnect-integration",
        "/operations/start-integration-connect",
      ]) {
        const refused = await callOperation(page, path, {
          slug: ORG_SLUG,
          provider,
        });
        expect(refused.status).toBeGreaterThanOrEqual(400);
      }
    }
  } finally {
    await page.close();
  }
});
