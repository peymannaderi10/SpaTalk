import {
  IconLayoutDashboard,
  IconSettings,
  IconShield,
} from "@tabler/icons-react";
import { routes } from "wasp/client/router";

export const userMenuItems = [
  {
    name: "Organisations",
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
    name: "Admin Dashboard",
    to: routes.AdminRoute.to,
    icon: IconShield,
    isAuthRequired: false,
    isAdminOnly: true,
  },
] as const;
