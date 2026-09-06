import {
  isHex,
  THEME_PRESET_IDS,
  type Branding,
} from "../client/branding/themes";

/**
 * What may be stored as an organisation's branding, checked the same way on
 * the server (`updateOrganizationBranding`) as the Branding page checks a
 * file before it reads one. Pure: no Wasp, no Prisma, so the rules are a unit
 * test's to drive, and the page can import the bounds without pulling in the
 * server.
 *
 * Branding is portal-only data on the organisation. It is never part of the
 * runtime tenant config, so nothing here is versioned with the settings and
 * the runtime never sees a logo or a colour.
 */

/** The most image a logo may carry, once decoded. */
export const LOGO_MAX_BYTES = 200 * 1024;
export const LOGO_MIME_TYPES = ["image/png", "image/svg+xml", "image/jpeg"];
export const LOGO_TOO_LARGE = "Keep the logo under 200 KB";
export const LOGO_WRONG_TYPE = "Use a PNG, SVG or JPEG";
const LOGO_UNREADABLE = "That logo could not be read.";
const PRESET_UNKNOWN = "That theme is not one of the presets.";
const ACCENT_NOT_A_COLOUR = "An accent is a colour like #1a2b3c.";

export type BrandingCheck =
  | { ok: true; value: Branding }
  | { ok: false; message: string };

const DATA_URL =
  /^data:(image\/png|image\/svg\+xml|image\/jpeg);base64,([A-Za-z0-9+/]*={0,2})$/;

/** How many bytes a base64 body decodes to, without decoding it. */
function decodedLength(base64: string): number {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return (base64.length * 3) / 4 - padding;
}

function checkLogo(
  value: unknown,
): { ok: true; value: string | null } | { ok: false; message: string } {
  if (value === null || value === undefined || value === "") {
    return { ok: true, value: null };
  }
  if (typeof value !== "string") {
    return { ok: false, message: LOGO_UNREADABLE };
  }
  // A base64 logo of `LOGO_MAX_BYTES` is under 275 000 characters with its
  // prefix; anything far past that is too large before it is worth parsing.
  if (value.length > 300_000) {
    return { ok: false, message: LOGO_TOO_LARGE };
  }
  if (!value.startsWith("data:")) {
    return { ok: false, message: LOGO_WRONG_TYPE };
  }
  // The type runs to the first `;` or `,`, whichever comes first.
  const end = value.search(/[;,]/);
  const mime = end < 0 ? "" : value.slice("data:".length, end).toLowerCase();
  if (!LOGO_MIME_TYPES.includes(mime)) {
    return { ok: false, message: LOGO_WRONG_TYPE };
  }
  const match = DATA_URL.exec(value);
  if (!match || match[2].length % 4 !== 0) {
    return { ok: false, message: LOGO_UNREADABLE };
  }
  if (decodedLength(match[2]) > LOGO_MAX_BYTES) {
    return { ok: false, message: LOGO_TOO_LARGE };
  }
  return { ok: true, value };
}

/**
 * The three fields as they may be written: a logo that is a base64 data URL
 * of an allowed type and size, a preset from the list, an accent as
 * `#rrggbb` lowercased. An empty string means "unset" and is stored as null.
 * The first thing wrong is named; nothing is written when anything is.
 */
export function validateBranding(input: {
  logoDataUrl?: unknown;
  themePreset?: unknown;
  accentHex?: unknown;
}): BrandingCheck {
  const logo = checkLogo(input.logoDataUrl);
  if (!logo.ok) {
    return logo;
  }

  let themePreset: string | null = null;
  if (
    input.themePreset !== null &&
    input.themePreset !== undefined &&
    input.themePreset !== ""
  ) {
    if (
      typeof input.themePreset !== "string" ||
      !THEME_PRESET_IDS.includes(input.themePreset)
    ) {
      return { ok: false, message: PRESET_UNKNOWN };
    }
    themePreset = input.themePreset;
  }

  let accentHex: string | null = null;
  if (
    input.accentHex !== null &&
    input.accentHex !== undefined &&
    input.accentHex !== ""
  ) {
    if (!isHex(input.accentHex)) {
      return { ok: false, message: ACCENT_NOT_A_COLOUR };
    }
    accentHex = input.accentHex.toLowerCase();
  }

  return {
    ok: true,
    value: { logoDataUrl: logo.value, themePreset, accentHex },
  };
}
