/**
 * The theme presets a clinic can choose for its own dashboard, and the
 * resolver that turns a choice into the CSS custom properties the clinic
 * shell sets inline on its root element.
 *
 * The tokens are the dashboard kit's (`Main.css`, its `:root` and `.dark`
 * blocks): the names Tailwind's `@theme inline` block maps `bg-primary`,
 * `text-foreground`, `border-border` and the rest onto, so a value set here
 * reaches every control the kit draws. `clinic` is the kit's own palette,
 * value for value — `themes.test.ts` reads `Main.css` and checks — so choosing
 * it changes nothing, and a clinic that never opened the Branding page wears
 * it.
 *
 * Every preset is complete for both modes. The shell resolves for the mode the
 * viewer is in (`useBrandingStyle`), because an inline palette would otherwise
 * override the kit's `.dark` values with light ones.
 *
 * Branding is portal-only data on the organisation, never part of the runtime
 * tenant config: nothing here is versioned with the settings, and the runtime
 * never sees it.
 */

/** The kit's colour tokens a preset sets, in `Main.css`'s spelling. */
export const CSS_VARS = [
  "--background",
  "--foreground",
  "--card",
  "--card-foreground",
  "--primary",
  "--primary-foreground",
  "--secondary",
  "--secondary-foreground",
  "--muted",
  "--muted-foreground",
  "--accent",
  "--accent-foreground",
  "--border",
  "--input",
  "--ring",
  "--sidebar",
  "--sidebar-foreground",
  "--sidebar-primary",
  "--sidebar-primary-foreground",
  "--sidebar-accent",
  "--sidebar-accent-foreground",
  "--sidebar-border",
  "--sidebar-ring",
] as const;

export type CssVar = (typeof CSS_VARS)[number];

/** One mode's worth of tokens: a value for every `CssVar`. */
export type ThemeTokens = Record<CssVar, string>;

export type ThemePreset = {
  id: string;
  label: string;
  light: ThemeTokens;
  dark: ThemeTokens;
};

/** What the organisation stores; `null` all round is the kit's own look. */
export type Branding = {
  logoDataUrl: string | null;
  themePreset: string | null;
  accentHex: string | null;
};

/** The preset a clinic wears until it chooses one. */
export const DEFAULT_PRESET = "clinic";

type SidebarVar = Extract<CssVar, `--sidebar${string}`>;

/**
 * The kit's sidebar tokens follow the page's, by reference. A preset that
 * wants the sidebar a shade apart from the page overrides `--sidebar` alone.
 */
const SIDEBAR_FROM_PAGE: Record<SidebarVar, string> = {
  "--sidebar": "var(--background)",
  "--sidebar-foreground": "var(--foreground)",
  "--sidebar-primary": "var(--primary)",
  "--sidebar-primary-foreground": "var(--primary-foreground)",
  "--sidebar-accent": "var(--accent)",
  "--sidebar-accent-foreground": "var(--accent-foreground)",
  "--sidebar-border": "var(--border)",
  "--sidebar-ring": "var(--ring)",
};

function tokens(
  page: Omit<ThemeTokens, SidebarVar>,
  sidebar: Partial<Record<SidebarVar, string>> = {},
): ThemeTokens {
  return { ...page, ...SIDEBAR_FROM_PAGE, ...sidebar };
}

export const THEME_PRESETS: ThemePreset[] = [
  {
    // The kit's palette exactly (`Main.css`): the look every clinic starts with.
    id: "clinic",
    label: "Clinic",
    light: tokens({
      "--background": "oklch(1 0 0)",
      "--foreground": "oklch(0.129 0.042 264.695)",
      "--card": "oklch(1 0 0)",
      "--card-foreground": "oklch(0.129 0.042 264.695)",
      "--primary": "oklch(0.208 0.042 265.755)",
      "--primary-foreground": "oklch(0.984 0.003 247.858)",
      "--secondary": "oklch(0.968 0.007 247.896)",
      "--secondary-foreground": "oklch(0.208 0.042 265.755)",
      "--muted": "oklch(0.968 0.007 247.896)",
      "--muted-foreground": "oklch(0.554 0.046 257.417)",
      "--accent": "oklch(0.968 0.007 247.896)",
      "--accent-foreground": "oklch(0.208 0.042 265.755)",
      "--border": "oklch(0.929 0.013 255.508)",
      "--input": "oklch(0.929 0.013 255.508)",
      "--ring": "oklch(0.704 0.04 256.788)",
    }),
    dark: tokens({
      "--background": "oklch(0.129 0.042 264.695)",
      "--foreground": "oklch(0.984 0.003 247.858)",
      "--card": "oklch(0.14 0.04 259.21)",
      "--card-foreground": "oklch(0.984 0.003 247.858)",
      "--primary": "oklch(0.929 0.013 255.508)",
      "--primary-foreground": "oklch(0.208 0.042 265.755)",
      "--secondary": "oklch(0.279 0.041 260.031)",
      "--secondary-foreground": "oklch(0.984 0.003 247.858)",
      "--muted": "oklch(0.279 0.041 260.031)",
      "--muted-foreground": "oklch(0.704 0.04 256.788)",
      "--accent": "oklch(0.279 0.041 260.031)",
      "--accent-foreground": "oklch(0.984 0.003 247.858)",
      "--border": "oklch(1 0 0 / 10%)",
      "--input": "oklch(1 0 0 / 15%)",
      "--ring": "oklch(0.551 0.027 264.364)",
    }),
  },
  {
    id: "slate",
    label: "Slate",
    light: tokens(
      {
        "--background": "oklch(0.985 0.004 250)",
        "--foreground": "oklch(0.21 0.03 262)",
        "--card": "oklch(1 0 0)",
        "--card-foreground": "oklch(0.21 0.03 262)",
        "--primary": "oklch(0.47 0.09 250)",
        "--primary-foreground": "oklch(0.985 0.004 250)",
        "--secondary": "oklch(0.95 0.01 250)",
        "--secondary-foreground": "oklch(0.3 0.04 258)",
        "--muted": "oklch(0.95 0.01 250)",
        "--muted-foreground": "oklch(0.52 0.03 255)",
        "--accent": "oklch(0.92 0.02 250)",
        "--accent-foreground": "oklch(0.3 0.04 258)",
        "--border": "oklch(0.9 0.012 250)",
        "--input": "oklch(0.9 0.012 250)",
        "--ring": "oklch(0.6 0.08 250)",
      },
      { "--sidebar": "oklch(0.955 0.008 250)" },
    ),
    dark: tokens(
      {
        "--background": "oklch(0.17 0.025 258)",
        "--foreground": "oklch(0.97 0.006 250)",
        "--card": "oklch(0.2 0.028 258)",
        "--card-foreground": "oklch(0.97 0.006 250)",
        "--primary": "oklch(0.74 0.1 245)",
        "--primary-foreground": "oklch(0.17 0.025 258)",
        "--secondary": "oklch(0.27 0.03 258)",
        "--secondary-foreground": "oklch(0.97 0.006 250)",
        "--muted": "oklch(0.27 0.03 258)",
        "--muted-foreground": "oklch(0.72 0.03 252)",
        "--accent": "oklch(0.3 0.035 258)",
        "--accent-foreground": "oklch(0.97 0.006 250)",
        "--border": "oklch(1 0 0 / 10%)",
        "--input": "oklch(1 0 0 / 15%)",
        "--ring": "oklch(0.6 0.08 250)",
      },
      { "--sidebar": "oklch(0.145 0.022 258)" },
    ),
  },
  {
    id: "rose",
    label: "Rose",
    light: tokens(
      {
        "--background": "oklch(0.99 0.006 15)",
        "--foreground": "oklch(0.23 0.03 20)",
        "--card": "oklch(1 0 0)",
        "--card-foreground": "oklch(0.23 0.03 20)",
        "--primary": "oklch(0.6 0.17 12)",
        "--primary-foreground": "oklch(0.99 0.006 15)",
        "--secondary": "oklch(0.96 0.014 15)",
        "--secondary-foreground": "oklch(0.33 0.05 15)",
        "--muted": "oklch(0.96 0.014 15)",
        "--muted-foreground": "oklch(0.53 0.04 15)",
        "--accent": "oklch(0.93 0.03 12)",
        "--accent-foreground": "oklch(0.33 0.05 15)",
        "--border": "oklch(0.91 0.018 15)",
        "--input": "oklch(0.91 0.018 15)",
        "--ring": "oklch(0.72 0.12 12)",
      },
      { "--sidebar": "oklch(0.965 0.012 15)" },
    ),
    dark: tokens(
      {
        "--background": "oklch(0.17 0.02 15)",
        "--foreground": "oklch(0.97 0.008 15)",
        "--card": "oklch(0.2 0.022 15)",
        "--card-foreground": "oklch(0.97 0.008 15)",
        "--primary": "oklch(0.74 0.13 12)",
        "--primary-foreground": "oklch(0.17 0.02 15)",
        "--secondary": "oklch(0.27 0.03 15)",
        "--secondary-foreground": "oklch(0.97 0.008 15)",
        "--muted": "oklch(0.27 0.03 15)",
        "--muted-foreground": "oklch(0.72 0.03 15)",
        "--accent": "oklch(0.31 0.04 12)",
        "--accent-foreground": "oklch(0.97 0.008 15)",
        "--border": "oklch(1 0 0 / 10%)",
        "--input": "oklch(1 0 0 / 15%)",
        "--ring": "oklch(0.65 0.11 12)",
      },
      { "--sidebar": "oklch(0.145 0.018 15)" },
    ),
  },
  {
    id: "sand",
    label: "Sand",
    light: tokens(
      {
        "--background": "oklch(0.985 0.008 85)",
        "--foreground": "oklch(0.25 0.03 55)",
        "--card": "oklch(0.995 0.005 90)",
        "--card-foreground": "oklch(0.25 0.03 55)",
        "--primary": "oklch(0.56 0.12 45)",
        "--primary-foreground": "oklch(0.985 0.008 85)",
        "--secondary": "oklch(0.95 0.018 85)",
        "--secondary-foreground": "oklch(0.35 0.04 55)",
        "--muted": "oklch(0.95 0.018 85)",
        "--muted-foreground": "oklch(0.53 0.035 60)",
        "--accent": "oklch(0.92 0.03 80)",
        "--accent-foreground": "oklch(0.35 0.04 55)",
        "--border": "oklch(0.9 0.022 80)",
        "--input": "oklch(0.9 0.022 80)",
        "--ring": "oklch(0.7 0.08 55)",
      },
      { "--sidebar": "oklch(0.96 0.014 85)" },
    ),
    dark: tokens(
      {
        "--background": "oklch(0.19 0.018 60)",
        "--foreground": "oklch(0.96 0.01 85)",
        "--card": "oklch(0.22 0.02 60)",
        "--card-foreground": "oklch(0.96 0.01 85)",
        "--primary": "oklch(0.76 0.11 60)",
        "--primary-foreground": "oklch(0.19 0.018 60)",
        "--secondary": "oklch(0.29 0.025 60)",
        "--secondary-foreground": "oklch(0.96 0.01 85)",
        "--muted": "oklch(0.29 0.025 60)",
        "--muted-foreground": "oklch(0.72 0.03 70)",
        "--accent": "oklch(0.33 0.03 60)",
        "--accent-foreground": "oklch(0.96 0.01 85)",
        "--border": "oklch(1 0 0 / 10%)",
        "--input": "oklch(1 0 0 / 15%)",
        "--ring": "oklch(0.65 0.08 60)",
      },
      { "--sidebar": "oklch(0.16 0.016 60)" },
    ),
  },
  {
    id: "forest",
    label: "Forest",
    light: tokens(
      {
        "--background": "oklch(0.985 0.006 150)",
        "--foreground": "oklch(0.22 0.03 155)",
        "--card": "oklch(1 0 0)",
        "--card-foreground": "oklch(0.22 0.03 155)",
        "--primary": "oklch(0.46 0.1 155)",
        "--primary-foreground": "oklch(0.985 0.006 150)",
        "--secondary": "oklch(0.95 0.014 150)",
        "--secondary-foreground": "oklch(0.32 0.05 155)",
        "--muted": "oklch(0.95 0.014 150)",
        "--muted-foreground": "oklch(0.52 0.035 155)",
        "--accent": "oklch(0.92 0.025 150)",
        "--accent-foreground": "oklch(0.32 0.05 155)",
        "--border": "oklch(0.9 0.018 150)",
        "--input": "oklch(0.9 0.018 150)",
        "--ring": "oklch(0.65 0.08 155)",
      },
      { "--sidebar": "oklch(0.96 0.011 150)" },
    ),
    dark: tokens(
      {
        "--background": "oklch(0.17 0.022 155)",
        "--foreground": "oklch(0.97 0.008 150)",
        "--card": "oklch(0.2 0.025 155)",
        "--card-foreground": "oklch(0.97 0.008 150)",
        "--primary": "oklch(0.73 0.12 155)",
        "--primary-foreground": "oklch(0.17 0.022 155)",
        "--secondary": "oklch(0.27 0.03 155)",
        "--secondary-foreground": "oklch(0.97 0.008 150)",
        "--muted": "oklch(0.27 0.03 155)",
        "--muted-foreground": "oklch(0.72 0.03 152)",
        "--accent": "oklch(0.31 0.035 155)",
        "--accent-foreground": "oklch(0.97 0.008 150)",
        "--border": "oklch(1 0 0 / 10%)",
        "--input": "oklch(1 0 0 / 15%)",
        "--ring": "oklch(0.6 0.09 155)",
      },
      { "--sidebar": "oklch(0.145 0.02 155)" },
    ),
  },
];

/** The preset ids, for the server's validation and the page's cards. */
export const THEME_PRESET_IDS: string[] = THEME_PRESETS.map(
  (preset) => preset.id,
);

/** The preset by id; `clinic` for null, and for an id nothing knows. */
export function presetById(id: string | null | undefined): ThemePreset {
  return (
    THEME_PRESETS.find((preset) => preset.id === id) ??
    THEME_PRESETS.find((preset) => preset.id === DEFAULT_PRESET)!
  );
}

/** A six-digit `#rrggbb`, the one form an accent is stored in. */
export function isHex(value: unknown): value is string {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
}

/**
 * Black or white, whichever reads on the accent: the WCAG relative luminance
 * of the colour, against the point where its contrast with black equals its
 * contrast with white.
 */
export function contrastForeground(hex: string): "#000000" | "#ffffff" {
  const channel = (offset: number) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928
      ? value / 12.92
      : Math.pow((value + 0.055) / 1.055, 2.4);
  };
  const luminance =
    0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  return luminance > 0.179 ? "#000000" : "#ffffff";
}

/**
 * The tokens the shell sets for one mode: the preset's, with the primary —
 * and the ring and the sidebar's primary, which follow it — replaced by the
 * accent when there is one, and the text on it picked to read.
 */
export function resolveTheme(
  preset: string | null,
  accentHex: string | null,
  mode: "light" | "dark",
): ThemeTokens {
  const resolved: ThemeTokens = { ...presetById(preset)[mode] };
  if (isHex(accentHex)) {
    const accent = accentHex.toLowerCase();
    const onAccent = contrastForeground(accent);
    resolved["--primary"] = accent;
    resolved["--primary-foreground"] = onAccent;
    resolved["--ring"] = accent;
    resolved["--sidebar-primary"] = accent;
    resolved["--sidebar-primary-foreground"] = onAccent;
  }
  return resolved;
}

/**
 * Whether there is a look to wear at all. A logo alone changes no colour, and
 * a clinic with neither a preset nor an accent gets the kit's own tokens from
 * `Main.css`, with nothing set inline.
 */
export function themeChosen(
  branding: Pick<Branding, "themePreset" | "accentHex"> | null | undefined,
): boolean {
  return Boolean(branding && (branding.themePreset || branding.accentHex));
}
