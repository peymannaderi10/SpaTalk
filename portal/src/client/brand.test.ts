import { existsSync, readFileSync, readdirSync, statSync } from "fs";
import { dirname, join, relative } from "path";
import { describe, expect, it } from "vitest";
import { BRAND } from "./brand";

/**
 * `portal/`, found by walking up from wherever the runner started, so the test
 * does not depend on the working directory Vitest happens to use.
 */
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

const PORTAL_ROOT = findPortalRoot();
const SRC_ROOT = join(PORTAL_ROOT, "src");

/**
 * The two places Wasp needs a constant, so they hold the name as a literal and
 * these tests keep them honest. Anywhere else in `portal/src`, the name is read
 * from `BRAND`.
 */
const WASP_LITERALS = {
  appTitle: {
    file: "main.wasp.ts",
    /** `title: "<name>",` in the app spec. */
    pattern: /\btitle:\s*"([^"]+)"/,
  },
  mailFromName: {
    file: join("src", "server", "mailFrom.ts"),
    /** The fallback in `MAIL_FROM_NAME = process.env.MAIL_FROM_NAME ?? "<name>"`. */
    pattern: /MAIL_FROM_NAME\s*=\s*process\.env\.MAIL_FROM_NAME\s*\?\?\s*"([^"]+)"/,
  },
} as const;

/**
 * Files under `src` allowed to write the name out. `brand.ts` is where it
 * lives; `mailFrom.ts` is one of the two Wasp literals above; this test names
 * the exceptions and so must be able to talk about them.
 */
const ALLOWED = new Set(
  [
    join("src", "client", "brand.ts"),
    join("src", "server", "mailFrom.ts"),
    join("src", "client", "brand.test.ts"),
  ].map((p) => p.split("\\").join("/")),
);

const TEXT_EXTENSIONS = [
  ".ts",
  ".tsx",
  ".js",
  ".jsx",
  ".mjs",
  ".cjs",
  ".css",
  ".json",
  ".html",
  ".md",
  ".svg",
  ".txt",
  ".yaml",
  ".yml",
];

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (TEXT_EXTENSIONS.some((ext) => entry.endsWith(ext))) {
      out.push(full);
    }
  }
  return out;
}

function posix(path: string): string {
  return path.split("\\").join("/");
}

function readLiteral(file: string, pattern: RegExp): string {
  const source = readFileSync(join(PORTAL_ROOT, file), "utf8");
  const match = source.match(pattern);
  expect(
    match,
    `${posix(file)} no longer matches ${pattern}; the test cannot check the literal it holds`,
  ).not.toBeNull();
  return match![1];
}

describe("the product name lives in BRAND", () => {
  it("the Wasp app title is the brand name", () => {
    const { file, pattern } = WASP_LITERALS.appTitle;
    expect(readLiteral(file, pattern)).toBe(BRAND.name);
  });

  it("the auth email sender name is the brand name", () => {
    const { file, pattern } = WASP_LITERALS.mailFromName;
    expect(readLiteral(file, pattern)).toBe(BRAND.name);
  });

  it("no other file under src writes the product name as a literal", () => {
    const offenders: string[] = [];

    for (const file of walk(SRC_ROOT)) {
      const rel = posix(relative(PORTAL_ROOT, file));
      if (ALLOWED.has(rel)) continue;
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        if (line.includes(BRAND.name)) {
          offenders.push(`${rel}:${index + 1}: ${line.trim()}`);
        }
      });
    }

    expect(
      offenders,
      "read the name from BRAND in src/client/brand.ts instead of writing it out",
    ).toEqual([]);
  });

  it("names something for every field a page will need", () => {
    expect(BRAND.name.length).toBeGreaterThan(0);
    expect(BRAND.shortName.length).toBeGreaterThan(0);
    expect(BRAND.tagline.length).toBeGreaterThan(0);
    expect(BRAND.supportEmail).toMatch(/^[^@\s]+@[^@\s]+\.[^@\s]+$/);
    expect(BRAND.logo.light).toMatch(/^\//);
    expect(BRAND.logo.dark).toMatch(/^\//);
    expect(BRAND.logo.mark).toMatch(/^\//);
    expect(BRAND.colors.primary.length).toBeGreaterThan(0);
  });
});
