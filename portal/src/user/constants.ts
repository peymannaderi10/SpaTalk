import {
  IconLayoutDashboard,
  IconSettings,
  IconShield,
} from "@tabler/icons-react";
import { routes } from "wasp/client/router";

/**
 * The user menu on the pages outside the app shell — the marketing bar and the
 * account page.
 *
 * The first entry is "Dashboard" rather than a list of organisations because
 * `/app` no longer shows one: it resolves to wherever this person's work is
 * (`src/client/entry.ts`). The admin-only entry is "Platform dashboard", the
 * same words the shell's own user menu and organisation switcher use, so an
 * agency admin reads one name for one place.
 */
export const userMenuItems = [
  {
    name: "Dashboard",
    to: routes.AppRoute.to,
    icon: IconLayoutDashboard,
    isAdminOnly: false,
    isAuthRequired: true,
  },
  {
    name: "Account Settings",
    to: routes.AccountRoute.to,
    icon: IconSettings,
    isAuthRequired: false,
    isAdminOnly: false,
  },
  {
    name: "Platform dashboard",
    to: routes.AdminRoute.to,
    icon: IconShield,
    isAuthRequired: false,
    isAdminOnly: true,
  },
] as const;
