import { existsSync, readFileSync, readdirSync, statSync } from "fs";
import { dirname, join, relative } from "path";
import { describe, expect, it } from "vitest";

/**
 * One chart library, one icon set.
 *
 * The reskin moved the portal onto the shadcn chart components (Recharts) and
 * Tabler Icons. ApexCharts and Lucide are gone from `package.json`, so an
 * import of either would not resolve at all — but it would fail at build time,
 * in the founder's terminal, and only for whoever happened to open that page.
 * This test fails here instead, and it fails on a *specifier*, so a file that
 * merely names one of these packages in prose is not an offender.
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

const PORTAL_ROOT = findPortalRoot();
const SRC_ROOT = join(PORTAL_ROOT, "src");

/** The packages R3 removed, with what took each one's place. */
const RETIRED: Record<string, string> = {
  "lucide-react": "@tabler/icons-react",
  "react-apexcharts": "the shadcn chart components in src/client/charts",
  apexcharts: "recharts, through src/client/components/ui/chart.tsx",
};

/**
 * This file, which has to write the retired names out to be able to look for
 * them. Nothing else under `src` is exempt.
 */
const ALLOWED = new Set(
  [join("src", "client", "no-legacy-ui.test.ts")].map((p) =>
    p.split("\\").join("/"),
  ),
);

const CODE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"];

/**
 * Every module specifier in a source file: `from "x"`, a bare `import "x"`, a
 * dynamic `import("x")` and a CommonJS `require("x")`.
 */
const SPECIFIER = /(?:from|import|require)\s*\(?\s*["']([^"']+)["']/g;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (CODE_EXTENSIONS.some((ext) => entry.endsWith(ext))) {
      out.push(full);
    }
  }
  return out;
}

function posix(path: string): string {
  return path.split("\\").join("/");
}

/** The retired package a specifier names, if it names one. */
function retiredPackage(specifier: string): string | null {
  for (const name of Object.keys(RETIRED)) {
    if (specifier === name || specifier.startsWith(`${name}/`)) return name;
  }
  return null;
}

describe("no file under src imports a retired UI package", () => {
  const files = walk(SRC_ROOT).filter(
    (file) => !ALLOWED.has(posix(relative(PORTAL_ROOT, file))),
  );

  it("finds source files to check", () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it.each(Object.keys(RETIRED))("nothing imports %s", (name) => {
    const offenders: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      const lines = source.split("\n");
      lines.forEach((line, index) => {
        for (const match of line.matchAll(SPECIFIER)) {
          if (retiredPackage(match[1]) === name) {
            offenders.push(
              `${posix(relative(PORTAL_ROOT, file))}:${index + 1}: ${line.trim()}`,
            );
          }
        }
      });
    }

    expect(
      offenders,
      `${name} was removed from package.json; use ${RETIRED[name]} instead`,
    ).toEqual([]);
  });

  it("names no package that is still a dependency", () => {
    const pkg = JSON.parse(
      readFileSync(join(PORTAL_ROOT, "package.json"), "utf8"),
    ) as { dependencies?: Record<string, string> };
    const declared = Object.keys(pkg.dependencies ?? {});
    const survivors = Object.keys(RETIRED).filter((name) =>
      declared.includes(name),
    );

    expect(
      survivors,
      "these are still in package.json, so removing the imports proved nothing",
    ).toEqual([]);
  });
});
