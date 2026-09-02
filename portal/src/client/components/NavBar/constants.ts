import { routes } from "wasp/client/router";
import type { NavigationItem } from "./NavBar";

export const appNavigationItems: NavigationItem[] = [
  { name: "Your front desk", to: routes.AppRoute.to },
  { name: "Privacy", to: routes.PrivacyRoute.to },
] as const;
