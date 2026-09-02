import { action, page, query, route, type Spec } from "@wasp.sh/spec";

import { InvitePage } from "./InvitePage" with { type: "ref" };
import { OrgHomePage } from "./OrgHomePage" with { type: "ref" };
import {
  acceptInvitation,
  createOrganization,
  getInvitation,
  getOrganization,
  inviteMember,
  listMyOrganizations,
  removeMember,
} from "./operations" with { type: "ref" };
import { PeoplePage } from "./PeoplePage" with { type: "ref" };

export const organizationsSpec: Spec = [
  // Public: an invited person opens this before they have an account.
  route("InviteRoute", "/invite/:token", page(InvitePage)),
  route(
    "OrgHomeRoute",
    "/app/:orgSlug",
    page(OrgHomePage, { authRequired: true }),
  ),
  route(
    "OrgPeopleRoute",
    "/app/:orgSlug/settings/people",
    page(PeoplePage, { authRequired: true }),
  ),
  query(listMyOrganizations, { entities: ["Organization", "Membership"] }),
  query(getOrganization, {
    entities: ["Organization", "Membership", "Invitation"],
  }),
  query(getInvitation, { entities: ["Invitation"], auth: false }),
  action(createOrganization, { entities: ["Organization"] }),
  action(inviteMember, {
    entities: ["Organization", "Membership", "Invitation"],
  }),
  action(acceptInvitation, {
    entities: ["Organization", "Membership", "Invitation"],
  }),
  action(removeMember, { entities: ["Organization", "Membership"] }),
];
