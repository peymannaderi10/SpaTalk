import { type App } from "@wasp.sh/spec";

import { BRAND } from "./brand";

export const head: App["head"] = [
  "<link rel='icon' href='/favicon.ico' />",

  `<meta name='description' content='The control panel for the ${BRAND.name} AI front desk.' />`,
  "<meta name='robots' content='noindex' />",
];
