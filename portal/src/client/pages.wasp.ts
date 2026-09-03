import { action, page, query, route, type Spec } from "@wasp.sh/spec";

import { ConversationsPage } from "./ConversationsPage" with { type: "ref" };
import {
  acknowledgeItem,
  blockSmsNumber,
  disconnectIntegration,
  getTenantConversations,
  getTenantIntegrations,
  getTenantOverview,
  getTenantRequests,
  getTenantSettings,
  readConversation,
  resolveItem,
  rollBackTenantConfig,
  saveTenantConfig,
  selectMessengerPage,
  startIntegrationConnect,
  unblockSmsNumber,
} from "./operations" with { type: "ref" };
import { OverviewPage } from "./OverviewPage" with { type: "ref" };
import { RequestsPage } from "./RequestsPage" with { type: "ref" };
import { SettingsPage } from "./SettingsPage" with { type: "ref" };

/**
 * The pages a client sees, and the operations behind them. Each operation
 * reaches the runtime and nothing else; the entities it declares are only what
 * `requireOrgAccess` needs to decide whether this person may look.
 */

const orgEntities = { entities: ["Organization", "Membership"] };

export const clientPagesSpec: Spec = [
  route(
    "OrgOverviewRoute",
    "/app/:orgSlug/overview",
    page(OverviewPage, { authRequired: true }),
  ),
  route(
    "OrgConversationsRoute",
    "/app/:orgSlug/conversations",
    page(ConversationsPage, { authRequired: true }),
  ),
  route(
    "OrgRequestsRoute",
    "/app/:orgSlug/requests",
    page(RequestsPage, { authRequired: true }),
  ),
  route(
    "OrgSettingsRoute",
    "/app/:orgSlug/settings",
    page(SettingsPage, { authRequired: true }),
  ),

  query(getTenantOverview, orgEntities),
  query(getTenantConversations, orgEntities),
  query(getTenantRequests, orgEntities),
  query(getTenantSettings, orgEntities),
  query(getTenantIntegrations, orgEntities),

  // Reading a transcript is an audited act, so it is an action: a query would
  // be cached and the second read would go unrecorded.
  action(readConversation, orgEntities),
  action(acknowledgeItem, orgEntities),
  action(resolveItem, orgEntities),
  // Blocking a number is a person's decision the runtime audits (plan F).
  action(blockSmsNumber, orgEntities),
  action(unblockSmsNumber, orgEntities),
  action(saveTenantConfig, orgEntities),
  action(rollBackTenantConfig, orgEntities),

  // Connecting and disconnecting a Meta account are audited acts the runtime
  // records, and both are refused to anyone but an owner.
  action(startIntegrationConnect, orgEntities),
  action(disconnectIntegration, orgEntities),
  action(selectMessengerPage, orgEntities),
];
