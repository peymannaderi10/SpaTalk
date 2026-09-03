/**
 * Everything the product is called, in one place.
 *
 * The rule the tests enforce: no file under `portal/src` writes the product
 * name as a literal. Two places may not read this module, because Wasp
 * evaluates them before any of it exists and needs a constant:
 *
 *   - `main.wasp.ts`, the app `title`;
 *   - `src/server/mailFrom.ts`, the fallback sender name Wasp bakes into the
 *     generated app and into the auth `fromField`.
 *
 * `brand.test.ts` reads both files and fails if either literal drifts from
 * `BRAND.name`.
 *
 * This module deliberately imports nothing. The Wasp compiler evaluates
 * `src/client/head.wasp.ts` in Node, and that file reads `BRAND`, so anything
 * this file imported - an asset, a client-only API - would have to survive
 * being loaded by the compiler. Hence the logos are public URLs, not bundler
 * asset imports, and the colour is the token, not a literal that would be a
 * second place to change the palette.
 */
export const BRAND = {
  /** The product's full name, as it appears to a person. */
  name: "SpaTalk",
  /** For places too narrow for the full name: a tab, a collapsed sidebar. */
  shortName: "SpaTalk",
  /** One line, used under the name in the sidebar and on the auth pages. */
  tagline: "The AI front desk for your clinic",
  /** Where a person writes when the portal cannot help them. */
  supportEmail: "support@spatalk.ca",
  /**
   * Served from `portal/public/brand`, so a string is enough and no module
   * needs a bundler to resolve it. `light` and `dark` are the same mark
   * today; they are separate fields so a future wordmark can differ per
   * theme without another code hunt.
   */
  logo: {
    light: "/brand/logo.svg",
    dark: "/brand/logo.svg",
    mark: "/brand/logo.svg",
  },
  /**
   * The brand colour as the stylesheet holds it. `--primary` is defined once,
   * in `Main.css`, for light and for dark; naming the token here rather than a
   * hex keeps the palette in one file.
   */
  colors: {
    primary: "var(--primary)",
  },
} as const;

export type Brand = typeof BRAND;
