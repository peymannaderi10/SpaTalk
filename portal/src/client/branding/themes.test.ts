import { existsSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { describe, expect, it } from "vitest";
import {
  contrastForeground,
  CSS_VARS,
  isHex,
  resolveTheme,
  THEME_PRESETS,
  themeChosen,
} from "./themes";

/**
 * The presets and the resolver. `clinic` is held to the kit's own palette by
 * reading `Main.css` here, so a token the kit changes and the preset does not
 * fails this test rather than quietly re-colouring every clinic that chose
 * the default.
 */

/** `portal/`, found by walking up from wherever the runner started. */
function findPortalRoot(): string {
  let dir = process.cwd();
  for (let hop = 0; hop < 8; hop += 1) {
    if (existsSync(join(dir, "main.wasp.ts"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(`could not find the portal root above ${process.cwd()}`);
}

/** The `--name: value;` declarations inside one `selector {` block of `Main.css`. */
function cssBlock(selector: string): Record<string, string> {
  const css = readFileSync(
    join(findPortalRoot(), "src", "client", "Main.css"),
    "utf8",
  );
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block in Main.css`);
  const body = css.slice(start, css.indexOf("\n  }", start));
  const declarations: Record<string, string> = {};
  for (const match of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
    declarations[match[1]] = match[2].trim();
  }
  return declarations;
}

describe("the theme presets", () => {
  it("are the five, clinic first", () => {
    expect(THEME_PRESETS.map((preset) => preset.id)).toEqual([
      "clinic",
      "slate",
      "rose",
      "sand",
      "forest",
    ]);
  });

  it("each define every token, for both modes", () => {
    for (const preset of THEME_PRESETS) {
      for (const mode of ["light", "dark"] as const) {
        for (const name of CSS_VARS) {
          expect(
            preset[mode][name],
            `${preset.id} ${mode} is missing ${name}`,
          ).toMatch(/\S/);
        }
      }
    }
  });

  it("start with clinic, which is the kit's own palette value for value", () => {
    const root = cssBlock(":root");
    const dark = cssBlock(".dark");
    const clinic = THEME_PRESETS[0];

    for (const name of CSS_VARS) {
      expect(clinic.light[name], `light ${name}`).toBe(root[name]);
      // `.dark` leaves the sidebar tokens to `:root`, which follow the page.
      expect(clinic.dark[name], `dark ${name}`).toBe(dark[name] ?? root[name]);
    }
  });
});

describe("resolveTheme", () => {
  it("hands back the preset's tokens for the mode asked, clinic when none is chosen", () => {
    expect(resolveTheme(null, null, "light")).toEqual(THEME_PRESETS[0].light);
    expect(resolveTheme("rose", null, "dark")).toEqual(
      THEME_PRESETS.find((preset) => preset.id === "rose")!.dark,
    );
    expect(resolveTheme("no-such-preset", null, "light")).toEqual(
      THEME_PRESETS[0].light,
    );
  });

  it("replaces the primary, the ring and the sidebar's primary with the accent", () => {
    const resolved = resolveTheme("slate", "#1A2B3C", "light");
    expect(resolved["--primary"]).toBe("#1a2b3c");
    expect(resolved["--ring"]).toBe("#1a2b3c");
    expect(resolved["--sidebar-primary"]).toBe("#1a2b3c");
    // Everything else is still the preset's.
    expect(resolved["--background"]).toBe(
      THEME_PRESETS.find((preset) => preset.id === "slate")!.light[
        "--background"
      ],
    );
  });

  it("picks a foreground that reads on the accent", () => {
    expect(resolveTheme(null, "#1a2b3c", "light")["--primary-foreground"]).toBe(
      "#ffffff",
    );
    expect(
      resolveTheme(null, "#1a2b3c", "light")["--sidebar-primary-foreground"],
    ).toBe("#ffffff");
    expect(resolveTheme(null, "#f5e6c8", "dark")["--primary-foreground"]).toBe(
      "#000000",
    );
    expect(contrastForeground("#000000")).toBe("#ffffff");
    expect(contrastForeground("#ffffff")).toBe("#000000");
  });

  it("ignores an accent that is not a colour", () => {
    expect(resolveTheme("sand", "#xyz", "light")).toEqual(
      THEME_PRESETS.find((preset) => preset.id === "sand")!.light,
    );
  });
});

describe("isHex", () => {
  it("accepts #rrggbb only", () => {
    expect(isHex("#1a2b3c")).toBe(true);
    expect(isHex("#1A2B3C")).toBe(true);
    expect(isHex("1a2b3c")).toBe(false);
    expect(isHex("#xyz")).toBe(false);
    expect(isHex("#1a2b3c ")).toBe(false);
    expect(isHex("#1a2b")).toBe(false);
    expect(isHex(null)).toBe(false);
  });
});

describe("themeChosen", () => {
  it("is false until a preset or an accent is set; a logo alone colours nothing", () => {
    expect(themeChosen(null)).toBe(false);
    expect(themeChosen({ themePreset: null, accentHex: null })).toBe(false);
    expect(themeChosen({ themePreset: "clinic", accentHex: null })).toBe(true);
    expect(themeChosen({ themePreset: null, accentHex: "#1a2b3c" })).toBe(true);
  });
});
