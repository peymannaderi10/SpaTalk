import { describe, expect, it } from "vitest";
import {
  LOGO_MAX_BYTES,
  LOGO_TOO_LARGE,
  LOGO_WRONG_TYPE,
  validateBranding,
} from "./branding";

/**
 * What `updateOrganizationBranding` lets onto the organisation row. The
 * checks are a pure function so they can be driven here without Wasp: the
 * operation itself only adds the owner check and the write.
 */

function pngOf(bytes: number): string {
  return `data:image/png;base64,${Buffer.alloc(bytes, 7).toString("base64")}`;
}

function accepted(input: Parameters<typeof validateBranding>[0]) {
  const result = validateBranding(input);
  if (!result.ok) throw new Error(`refused: ${result.message}`);
  return result.value;
}

function refused(input: Parameters<typeof validateBranding>[0]): string {
  const result = validateBranding(input);
  if (result.ok) throw new Error("accepted, but a refusal was expected");
  return result.message;
}

describe("validateBranding", () => {
  it("accepts nothing at all, which is the kit's own look", () => {
    expect(
      accepted({ logoDataUrl: null, themePreset: null, accentHex: null }),
    ).toEqual({ logoDataUrl: null, themePreset: null, accentHex: null });
    // An empty string is how a form says "unset"; it is stored as null.
    expect(
      accepted({ logoDataUrl: "", themePreset: "", accentHex: "" }),
    ).toEqual({ logoDataUrl: null, themePreset: null, accentHex: null });
  });

  it("takes a preset from the list and nothing else", () => {
    for (const id of ["clinic", "slate", "rose", "sand", "forest"]) {
      expect(accepted({ themePreset: id }).themePreset).toBe(id);
    }
    expect(refused({ themePreset: "neon" })).toMatch(/preset/);
    expect(refused({ themePreset: "Rose" })).toMatch(/preset/);
    expect(refused({ themePreset: 3 })).toMatch(/preset/);
  });

  it("takes an accent as #rrggbb, stored lowercase", () => {
    expect(accepted({ accentHex: "#1A2B3C" }).accentHex).toBe("#1a2b3c");
    expect(refused({ accentHex: "1a2b3c" })).toMatch(/#1a2b3c/);
    expect(refused({ accentHex: "#xyz" })).toMatch(/#1a2b3c/);
    expect(refused({ accentHex: "#1a2b3c " })).toMatch(/#1a2b3c/);
    expect(refused({ accentHex: "red" })).toMatch(/#1a2b3c/);
  });

  it("takes a logo as a base64 data URL of a PNG, SVG or JPEG", () => {
    const png = pngOf(1024);
    expect(accepted({ logoDataUrl: png }).logoDataUrl).toBe(png);
    const svg = `data:image/svg+xml;base64,${Buffer.from(
      "<svg xmlns='http://www.w3.org/2000/svg'/>",
    ).toString("base64")}`;
    expect(accepted({ logoDataUrl: svg }).logoDataUrl).toBe(svg);
    const jpeg = `data:image/jpeg;base64,${Buffer.alloc(300, 1).toString(
      "base64",
    )}`;
    expect(accepted({ logoDataUrl: jpeg }).logoDataUrl).toBe(jpeg);

    expect(
      refused({
        logoDataUrl: `data:image/gif;base64,${Buffer.alloc(8).toString(
          "base64",
        )}`,
      }),
    ).toBe(LOGO_WRONG_TYPE);
    expect(
      refused({
        logoDataUrl: `data:text/html;base64,${Buffer.from("<script>").toString(
          "base64",
        )}`,
      }),
    ).toBe(LOGO_WRONG_TYPE);
    expect(refused({ logoDataUrl: "https://cdn.example/logo.png" })).toBe(
      LOGO_WRONG_TYPE,
    );
  });

  it("refuses a logo over 200 KB by its decoded size, not the string's", () => {
    expect(LOGO_MAX_BYTES).toBe(200 * 1024);
    expect(
      accepted({ logoDataUrl: pngOf(LOGO_MAX_BYTES) }).logoDataUrl,
    ).toHaveLength(pngOf(LOGO_MAX_BYTES).length);
    expect(refused({ logoDataUrl: pngOf(LOGO_MAX_BYTES + 1) })).toBe(
      LOGO_TOO_LARGE,
    );
    expect(refused({ logoDataUrl: pngOf(300 * 1024) })).toBe(LOGO_TOO_LARGE);
  });

  it("refuses a data URL that is not base64, or not a string", () => {
    expect(
      refused({ logoDataUrl: "data:image/png;base64,not base64!" }),
    ).toMatch(/could not be read/);
    expect(refused({ logoDataUrl: "data:image/png,rawbytes" })).toMatch(
      /could not be read/,
    );
    expect(refused({ logoDataUrl: 42 })).toMatch(/could not be read/);
  });

  it("names the first thing wrong and leaves the rest alone", () => {
    expect(
      refused({
        logoDataUrl: pngOf(10),
        themePreset: "neon",
        accentHex: "#xyz",
      }),
    ).toMatch(/preset/);
  });
});
