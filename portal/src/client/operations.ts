import { config, HttpError } from "wasp/server";
import {
  type AcknowledgeItem,
  type BlockSmsNumber,
  type DisconnectIntegration,
  type GetTenantConversations,
  type GetTenantIntegrations,
  type GetTenantOverview,
  type GetTenantRequests,
  type GetTenantSettings,
  type ReadConversation,
  type ResolveItem,
  type RollBackTenantConfig,
  type SaveTenantConfig,
  type SelectMessengerPage,
  type StartIntegrationConnect,
  type UnblockSmsNumber,
} from "wasp/server/operations";
import * as z from "zod";
import {
  requireOrgAccessBySlug,
  requireOrgOwnerBySlug,
  type OrgAccess,
  type OrgSlugAccessContext,
} from "../organizations/access";
import {
  organizationIsEntitled,
  SUBSCRIPTION_REQUIRED_STATUS,
  subscriptionRequiredMessage,
} from "../payment/entitlement";
import { runtime, runtimeCall, type RuntimeClient } from "../runtime/api";
import { type components } from "../runtime/client";
import { ensureArgsSchemaOrThrowHttpError } from "../server/validation";

/**
 * Everything the client pages know about a tenant comes through here.
 *
 * The portal holds no tenant, conversation, item or usage data of its own
 * (portal plan, Global Constraints); these operations are a thin, access-checked
 * shell over the runtime's `/internal` API. Every one of them names the acting
 * user to the runtime, which writes the audit row itself.
 */

/**
 * Wasp puts every operation's arguments and result through SuperJSON, whose
 * types reject an index signature of `unknown`. The runtime's open-ended
 * objects — an item's preferred window, a whole tenant configuration, the
 * schema itself — are plain JSON, so they are declared as such here.
 */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | JsonValue[]
  | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

type Schema = components["schemas"];
export type UsageDay = Schema["UsageDay"];
export type UsageTotals = Schema["UsageTotals"];
/** A number the tenant is not answering by SMS: a flood mute or a person's block (plan F). */
export type SmsBlock = Schema["SmsBlockOut"];
export type ConversationRow = Schema["ConversationRow"];
export type Item = Omit<Schema["ItemOut"], "preferred_window"> & {
  preferred_window: JsonObject;
};
export type ConversationDetail = Omit<Schema["ConversationDetail"], "items"> & {
  items: Item[];
};
export type LatencyDay = Schema["LatencyDay"];
export type TenantHealth = Schema["TenantHealth"];
export type ConfigVersion = Schema["ConfigVersionOut"];
export type TenantNumber = Schema["NumberOut"];

const MAX_PAGE_SIZE = 200;
/** Open work is meant to be a short list; this only stops a runaway loop. */
const MAX_PAGES = 10;

const slugArgs = z.object({ slug: z.string().min(1).max(64) });

type Sess = {
  access: OrgAccess;
  tenantId: string;
  actor: string;
  api: RuntimeClient;
};

/** What these operations need of a Wasp context: the org lookup, plus who is acting. */
type PageContext = OrgSlugAccessContext & {
  user?: { id: string; isAdmin: boolean; email?: string | null } | null;
};

/**
 * The subscription gate (portal plan, Task C6).
 *
 * Every client page except the overview needs the organisation's subscription
 * to be live; an agency admin is let through regardless. It is enforced here,
 * on the server, and not only in the page: hiding a button is not a gate.
 */
function requireSubscription(context: PageContext, access: OrgAccess): void {
  const entitled = organizationIsEntitled({
    subscriptionStatus: access.org.subscriptionStatus,
    viewerIsAgencyAdmin: context.user?.isAdmin === true,
  });
  if (!entitled) {
    throw new HttpError(
      SUBSCRIPTION_REQUIRED_STATUS,
      subscriptionRequiredMessage(access.org.name, access.org.subscriptionStatus),
    );
  }
}

async function session(
  context: PageContext,
  slug: string,
  { needsSubscription = true }: { needsSubscription?: boolean } = {},
): Promise<Sess> {
  const access = await requireOrgAccessBySlug(context, slug);
  if (needsSubscription) {
    requireSubscription(context, access);
  }
  const actor = context.user?.email ?? context.user?.id ?? "unknown";
  return {
    access,
    tenantId: access.org.runtimeTenantId,
    actor,
    api: runtime(actor),
  };
}

async function ownerSession(context: PageContext, slug: string): Promise<Sess> {
  const access = await requireOrgOwnerBySlug(context, slug);
  requireSubscription(context, access);
  const actor = context.user?.email ?? context.user?.id ?? "unknown";
  return {
    access,
    tenantId: access.org.runtimeTenantId,
    actor,
    api: runtime(actor),
  };
}

async function itemsInState(
  api: RuntimeClient,
  tenantId: string,
  state: "open" | "acknowledged" | "resolved" | "all",
): Promise<Item[]> {
  const collected: Item[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const batch = await runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/items", {
          params: {
            path: { tenant_id: tenantId },
            query: { state, page, page_size: MAX_PAGE_SIZE },
          },
        }),
      "the tracked requests",
    );
    collected.push(...(batch as unknown as Item[]));
    if (batch.length < MAX_PAGE_SIZE) {
      break;
    }
  }
  return collected;
}

/**
 * The runtime acknowledges or resolves an item by its number alone, so this is
 * the only thing standing between one organisation and another's ledger: an
 * item may be acted on only while it is open or acknowledged for *this*
 * organisation's tenant.
 */
async function actionableItem(
  api: RuntimeClient,
  tenantId: string,
  itemId: number,
): Promise<Item> {
  for (const state of ["open", "acknowledged"] as const) {
    const found = (await itemsInState(api, tenantId, state)).find(
      (item) => item.id === itemId,
    );
    if (found) {
      return found;
    }
  }
  throw new HttpError(404, "That request is not open in this organisation.");
}

// --- overview --------------------------------------------------------------

export type Overview = {
  tenantId: string;
  role: OrgAccess["role"];
  /** Local days in the tenant's timezone, oldest first. */
  days: UsageDay[];
  month: { from: string; to: string; totals: UsageTotals };
  health: TenantHealth;
  latency: LatencyDay[];
  overdue: Item[];
};

const overviewArgs = slugArgs;

export const getTenantOverview: GetTenantOverview<
  z.infer<typeof overviewArgs>,
  Overview
> = async (rawArgs, context) => {
  const { slug } = ensureArgsSchemaOrThrowHttpError(overviewArgs, rawArgs);
  // The one page a clinic keeps without a subscription: an owner deciding
  // whether to pay has to see what they would be paying for.
  const { api, tenantId, access } = await session(context, slug, {
    needsSubscription: false,
  });

  // No dates: the runtime answers with the last thirty days *in the tenant's
  // timezone*, and the last of them is the tenant's today. Everything else here
  // is anchored to that, so a clinic's month is never the server's month.
  const chart = await runtimeCall(
    () =>
      api.GET("/internal/tenants/{tenant_id}/usage", {
        params: { path: { tenant_id: tenantId } },
      }),
    "usage",
  );

  const today = chart.days[chart.days.length - 1]?.date ?? "";
  const monthFrom = today ? `${today.slice(0, 7)}-01` : today;

  const [month, health, latency, items] = await Promise.all([
    runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/usage", {
          params: {
            path: { tenant_id: tenantId },
            query: { from: monthFrom, to: today },
          },
        }),
      "usage",
    ),
    runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/health", {
          params: { path: { tenant_id: tenantId } },
        }),
      "the tenant's health",
    ),
    runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/latency", {
          params: { path: { tenant_id: tenantId } },
        }),
      "latency",
    ),
    itemsInState(api, tenantId, "all"),
  ]);

  const now = Date.now();
  const overdue = items
    .filter(
      (item) =>
        (item.state === "open" || item.state === "acknowledged") &&
        Date.parse(item.due_at) < now,
    )
    .sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at));

  return {
    tenantId,
    role: access.role,
    days: chart.days,
    month: { from: monthFrom, to: today, totals: month.totals },
    health,
    latency,
    overdue,
  };
};

// --- conversations ---------------------------------------------------------

const conversationsArgs = slugArgs.extend({
  channel: z.string().max(16).optional(),
  band: z.number().int().min(1).max(3).optional(),
  page: z.number().int().min(1).default(1),
});

export type Conversations = {
  items: ConversationRow[];
  total: number;
  page: number;
  pageSize: number;
};

const CONVERSATIONS_PER_PAGE = 25;

export const getTenantConversations: GetTenantConversations<
  z.infer<typeof conversationsArgs>,
  Conversations
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(conversationsArgs, rawArgs);
  const { api, tenantId } = await session(context, args.slug);

  const page = await runtimeCall(
    () =>
      api.GET("/internal/tenants/{tenant_id}/conversations", {
        params: {
          path: { tenant_id: tenantId },
          query: {
            channel: args.channel || undefined,
            band: args.band,
            page: args.page,
            page_size: CONVERSATIONS_PER_PAGE,
          },
        },
      }),
    "conversations",
  );

  return {
    items: page.items,
    total: page.total,
    page: args.page,
    pageSize: CONVERSATIONS_PER_PAGE,
  };
};

const transcriptArgs = slugArgs.extend({ conversationId: z.uuid() });

/**
 * An action, not a query: reading a transcript is something a person *did*, and
 * the runtime writes an audit row naming them every time. A cached query would
 * quietly stop recording the second read.
 */
export const readConversation: ReadConversation<
  z.infer<typeof transcriptArgs>,
  ConversationDetail
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(transcriptArgs, rawArgs);
  const { api, tenantId } = await session(context, args.slug);

  const detail = (await runtimeCall(
    () =>
      api.GET("/internal/conversations/{conversation_id}", {
        params: { path: { conversation_id: args.conversationId } },
      }),
    "that conversation",
  )) as unknown as ConversationDetail;

  if (detail.conversation.tenant_id !== tenantId) {
    throw new HttpError(404, "That conversation is not in this organisation.");
  }
  return detail;
};

// --- tracked requests ------------------------------------------------------

export type Requests = {
  role: OrgAccess["role"];
  open: Item[];
  resolved: Item[];
};

export const getTenantRequests: GetTenantRequests<
  z.infer<typeof slugArgs>,
  Requests
> = async (rawArgs, context) => {
  const { slug } = ensureArgsSchemaOrThrowHttpError(slugArgs, rawArgs);
  const { api, tenantId, access } = await session(context, slug);

  const items = await itemsInState(api, tenantId, "all");
  const byDue = (a: Item, b: Item) => Date.parse(a.due_at) - Date.parse(b.due_at);

  return {
    role: access.role,
    open: items
      .filter((item) => item.state === "open" || item.state === "acknowledged")
      .sort(byDue),
    resolved: items.filter((item) => item.state === "resolved").sort(byDue),
  };
};

const itemArgs = slugArgs.extend({ itemId: z.number().int().positive() });

export const acknowledgeItem: AcknowledgeItem<
  z.infer<typeof itemArgs>,
  Item
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(itemArgs, rawArgs);
  const { api, tenantId, actor } = await session(context, args.slug);
  await actionableItem(api, tenantId, args.itemId);

  return (await runtimeCall(
    () =>
      api.POST("/internal/items/{item_id}/acknowledge", {
        params: { path: { item_id: args.itemId } },
        body: { actor },
      }),
    "that request",
  )) as unknown as Item;
};

export const resolveItem: ResolveItem<z.infer<typeof itemArgs>, Item> = async (
  rawArgs,
  context,
) => {
  const args = ensureArgsSchemaOrThrowHttpError(itemArgs, rawArgs);
  const { api, tenantId, actor } = await session(context, args.slug);
  await actionableItem(api, tenantId, args.itemId);

  return (await runtimeCall(
    () =>
      api.POST("/internal/items/{item_id}/resolve", {
        params: { path: { item_id: args.itemId } },
        body: { actor },
      }),
    "that request",
  )) as unknown as Item;
};

// --- the SMS block list (plan F, F2) ------------------------------------------
// A person's decision about a number. The runtime refuses a staff number and
// writes the audit row; the portal only carries the request and the actor.

const E164 = /^\+[1-9]\d{7,14}$/;
const blockArgs = slugArgs.extend({ phone: z.string().regex(E164) });

export const blockSmsNumber: BlockSmsNumber<
  z.infer<typeof blockArgs>,
  SmsBlock
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(blockArgs, rawArgs);
  const { api, tenantId, actor } = await session(context, args.slug);

  return (await runtimeCall(
    () =>
      api.POST("/internal/tenants/{tenant_id}/sms-blocks", {
        params: { path: { tenant_id: tenantId } },
        body: { phone: args.phone, actor },
      }),
    "that number",
  )) as unknown as SmsBlock;
};

export const unblockSmsNumber: UnblockSmsNumber<
  z.infer<typeof blockArgs>,
  { removed: boolean }
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(blockArgs, rawArgs);
  const { api, tenantId, actor } = await session(context, args.slug);

  return (await runtimeCall(
    () =>
      api.DELETE("/internal/tenants/{tenant_id}/sms-blocks/{phone}", {
        params: { path: { tenant_id: tenantId, phone: args.phone }, query: { actor } },
      }),
    "that number",
  )) as unknown as { removed: boolean };
};

// --- settings --------------------------------------------------------------

export type Settings = {
  tenantId: string;
  role: OrgAccess["role"];
  version: number;
  config: JsonObject;
  /** The runtime's pydantic models, as JSON schema: the forms are built from it. */
  schema: JsonObject;
  versions: ConfigVersion[];
  numbers: TenantNumber[];
  /** Blocked and muted numbers, from the runtime's block list (plan F). */
  blocks: SmsBlock[];
};

export const getTenantSettings: GetTenantSettings<
  z.infer<typeof slugArgs>,
  Settings
> = async (rawArgs, context) => {
  const { slug } = ensureArgsSchemaOrThrowHttpError(slugArgs, rawArgs);
  const { api, tenantId, access } = await session(context, slug);

  const [current, versions, schema, tenants, blocks] = await Promise.all([
    runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/config", {
          params: { path: { tenant_id: tenantId } },
        }),
      "the settings",
    ),
    runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/config/versions", {
          params: { path: { tenant_id: tenantId } },
        }),
      "the settings history",
    ),
    runtimeCall(
      () => api.GET("/internal/schema/tenant-config", {}),
      "the settings schema",
    ),
    runtimeCall(() => api.GET("/internal/tenants", {}), "the tenants"),
    runtimeCall(
      () =>
        api.GET("/internal/tenants/{tenant_id}/sms-blocks", {
          params: { path: { tenant_id: tenantId } },
        }),
      "the blocked numbers",
    ),
  ]);

  const summary = tenants.find((tenant) => tenant.id === tenantId);

  return {
    tenantId,
    role: access.role,
    version: current.version,
    config: current.config as JsonObject,
    schema: schema as JsonObject,
    versions,
    numbers: summary?.numbers ?? [],
    blocks: blocks as unknown as SmsBlock[],
  };
};

const saveArgs = slugArgs.extend({
  config: z.record(z.string(), z.unknown()),
});

export type SaveArgs = { slug: string; config: JsonObject };

export const saveTenantConfig: SaveTenantConfig<
  SaveArgs,
  { version: number }
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(
    saveArgs,
    rawArgs,
  ) as SaveArgs;
  const { api, tenantId, actor } = await ownerSession(context, args.slug);

  // The whole configuration is stored as the new version: this is a save, not
  // a patch, and what comes back from `GET config` is what a form was filled in
  // with (portal plan Task C3, notes for neighbours).
  return runtimeCall(
    () =>
      api.PUT("/internal/tenants/{tenant_id}/config", {
        params: { path: { tenant_id: tenantId } },
        body: { config: args.config, created_by: actor },
      }),
    "these settings",
  );
};

const rollbackArgs = slugArgs.extend({
  version: z.number().int().positive(),
});

export const rollBackTenantConfig: RollBackTenantConfig<
  z.infer<typeof rollbackArgs>,
  { version: number }
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(rollbackArgs, rawArgs);
  const { api, tenantId, actor } = await ownerSession(context, args.slug);

  // Nothing is deleted: the runtime writes a new version equal to the old one.
  return runtimeCall(
    () =>
      api.POST("/internal/tenants/{tenant_id}/config/rollback", {
        params: { path: { tenant_id: tenantId } },
        body: { version: args.version, created_by: actor },
      }),
    "these settings",
  );
};

// --- integrations ----------------------------------------------------------

/**
 * Instagram and Facebook Page connections (instagram plan, Task D4).
 *
 * The portal stores nothing about them and never speaks to Meta: it reads the
 * status from the runtime, and a Connect is a runtime-signed authorisation URL
 * the browser is sent to. No token, encrypted or otherwise, crosses this
 * boundary — the runtime does not return one and this page has no use for one.
 */
export type Integration = Schema["IntegrationOut"];

export type Integrations = {
  role: OrgAccess["role"];
  integrations: Integration[];
};

const providerArgs = slugArgs.extend({
  provider: z.enum(["instagram", "messenger"]),
});

export const getTenantIntegrations: GetTenantIntegrations<
  z.infer<typeof slugArgs>,
  Integrations
> = async (rawArgs, context) => {
  const { slug } = ensureArgsSchemaOrThrowHttpError(slugArgs, rawArgs);
  const { api, tenantId, access } = await session(context, slug);

  const integrations = await runtimeCall(
    () =>
      api.GET("/internal/tenants/{tenant_id}/integrations", {
        params: { path: { tenant_id: tenantId } },
      }),
    "the connected accounts",
  );

  return { role: access.role, integrations: integrations as Integration[] };
};

/**
 * Where Meta sends the browser once the account is connected: this
 * organisation's own settings page, built here rather than taken from the
 * client, so the only address the runtime will ever sign is one of ours.
 */
function settingsReturnUrl(slug: string, provider: string): string {
  const base = config.frontendUrl.replace(/\/$/, "");
  return `${base}/app/${encodeURIComponent(slug)}/settings?connected=${provider}`;
}

export const startIntegrationConnect: StartIntegrationConnect<
  z.infer<typeof providerArgs>,
  { url: string; expiresIn: number }
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(providerArgs, rawArgs);
  // Connecting an account is the owner's decision, and the URL is minted per
  // click because the runtime's signed state is good for fifteen minutes.
  const { api, tenantId } = await ownerSession(context, args.slug);

  const answer = await runtimeCall(
    () =>
      api.GET(
        "/internal/tenants/{tenant_id}/integrations/{provider}/connect-url",
        {
          params: {
            path: { tenant_id: tenantId, provider: args.provider },
            query: { return_to: settingsReturnUrl(args.slug, args.provider) },
          },
        },
      ),
    "the connection link",
  );

  return { url: answer.url, expiresIn: answer.expires_in };
};

export const disconnectIntegration: DisconnectIntegration<
  z.infer<typeof providerArgs>,
  Integrations
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(providerArgs, rawArgs);
  const { api, tenantId, access } = await ownerSession(context, args.slug);

  await runtimeCall(
    () =>
      api.DELETE("/internal/tenants/{tenant_id}/integrations/{provider}", {
        params: { path: { tenant_id: tenantId, provider: args.provider } },
      }),
    "that connection",
  );

  // The card is redrawn from the runtime, never from what the button assumed.
  const integrations = await runtimeCall(
    () =>
      api.GET("/internal/tenants/{tenant_id}/integrations", {
        params: { path: { tenant_id: tenantId } },
      }),
    "the connected accounts",
  );

  return { role: access.role, integrations: integrations as Integration[] };
};

const pageSelectArgs = slugArgs.extend({
  pending: z.string().min(1).max(256),
  pageId: z.string().min(1).max(64),
});

/**
 * Finish a Page connection when the owner administers more than one Page.
 *
 * The runtime parked the Pages behind an opaque, single-use handle for fifteen
 * minutes (instagram plan, Task D3) because the OAuth code cannot be exchanged
 * twice; this is the choice landing back on it. A refused handle means the
 * connection has to be started again, and the runtime says so.
 */
export const selectMessengerPage: SelectMessengerPage<
  z.infer<typeof pageSelectArgs>,
  Integrations
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(pageSelectArgs, rawArgs);
  const { api, tenantId, access } = await ownerSession(context, args.slug);

  await runtimeCall(
    () =>
      api.POST(
        "/internal/tenants/{tenant_id}/integrations/messenger/select",
        {
          params: { path: { tenant_id: tenantId } },
          body: { pending: args.pending, page_id: args.pageId },
        },
      ),
    "that Page",
  );

  const integrations = await runtimeCall(
    () =>
      api.GET("/internal/tenants/{tenant_id}/integrations", {
        params: { path: { tenant_id: tenantId } },
      }),
    "the connected accounts",
  );

  return { role: access.role, integrations: integrations as Integration[] };
};
