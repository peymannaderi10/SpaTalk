import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "vitest";

/**
 * The portal's continuous integration and the contract drift check
 * (portal plan, Task C8).
 *
 * Two things are asserted here, and neither of them can be asserted by running
 * the portal:
 *
 * 1. The CI workflow really contains a portal job shaped the way the plan
 *    describes — a Postgres, a runtime on port 8000 with a seeded tenant, a
 *    build, Playwright against both, and a drift check of its own.
 * 2. The generated runtime client and the committed OpenAPI contract still
 *    agree. CI proves that by regenerating the client and diffing it, which
 *    needs the generator; this proves the same thing offline, on every test
 *    run, by comparing what the two files declare.
 */

const REPO = join(__dirname, "..", "..", "..");
const WORKFLOW = join(REPO, ".github", "workflows", "ci.yml");
const CONTRACT = join(REPO, "docs", "contracts", "runtime-internal.openapi.json");
const CONTRACT_README = join(REPO, "docs", "contracts", "README.md");
const CLIENT = join(REPO, "portal", "src", "runtime", "client.ts");
const PACKAGE_JSON = join(REPO, "portal", "package.json");

/**
 * The lines of one job in the workflow: everything from `  <name>:` down to the
 * next line indented by exactly two spaces, which is the next job.
 */
function job(name: string): string {
  const lines = readFileSync(WORKFLOW, "utf8").split("\n");
  const start = lines.findIndex((line) => line === `  ${name}:`);
  expect(start, `the workflow has no job \`${name}\``).toBeGreaterThan(-1);
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => /^ {2}\S/.test(line));
  return (end === -1 ? rest : rest.slice(0, end)).join("\n");
}

function scripts(): Record<string, string> {
  return JSON.parse(readFileSync(PACKAGE_JSON, "utf8")).scripts ?? {};
}

describe("the portal CI job", () => {
  test("starts a Postgres for the runtime and the portal to share", () => {
    const portal = job("portal");
    expect(portal).toMatch(/image:\s*postgres:/);
    expect(portal).toMatch(/POSTGRES_USER:\s*spatalk/);
    expect(portal).toMatch(/pg_isready/);
  });

  test("runs the runtime with uv on port 8000", () => {
    const portal = job("portal");
    expect(portal).toMatch(/uv venv --python 3\.12/);
    expect(portal).toMatch(/uv run spatalk serve[^\n]*--port 8000/);
    expect(portal).toMatch(/localhost:8000\/healthz/);
    // The runtime's own schema has to exist before it serves anything.
    expect(portal).toMatch(/uv run alembic upgrade head/);
  });

  test("seeds a tenant into that runtime before the browser tests", () => {
    const portal = job("portal");
    expect(portal).toMatch(/RUNTIME_SEED_COMMAND:[^\n]*seed_runtime\.py/);
    // The seed talks to the database with the runtime's async driver, and the
    // portal talks to the same database with Prisma's plain one.
    expect(portal).toMatch(/RUNTIME_SEED_COMMAND:[^\n]*postgresql\+asyncpg:/);
  });

  test("builds the portal", () => {
    expect(job("portal")).toMatch(/wasp build/);
  });

  test("runs Playwright against the portal and the runtime", () => {
    const portal = job("portal");
    expect(portal).toMatch(/playwright install/);
    expect(portal).toMatch(/npm run e2e|npx playwright test/);
    expect(portal).toMatch(/RUNTIME_INTERNAL_URL:\s*http:\/\/localhost:8000/);
    // The key the portal presents and the key the runtime accepts are one value.
    const key = /RUNTIME_INTERNAL_KEY: +(\S+)/.exec(portal)?.[1];
    expect(key, "the portal job sets no RUNTIME_INTERNAL_KEY").toBeTruthy();
    expect(portal).toContain(`INTERNAL_API_KEY: ${key}`);
  });

  test("runs the rest of the portal's suite, not only the browser tests", () => {
    const portal = job("portal");
    expect(portal).toMatch(/npm run test:unit/);
    expect(portal).toMatch(/wasp test client run/);
    expect(portal).toMatch(/tsc -p tsconfig\.src\.json --noEmit/);
  });

  test("never pins the Dummy email provider, so the build is the production one", () => {
    // Wasp bakes the provider in at compile time and refuses Dummy for a
    // production build; Playwright pins Dummy itself for the server it starts.
    expect(job("portal")).not.toMatch(/^\s*PORTAL_EMAIL_PROVIDER:/m);
  });
});

describe("the contract drift check", () => {
  test("is a step of its own in the portal job", () => {
    const portal = job("portal");
    expect(portal).toMatch(/name:[^\n]*contract drift/i);
    expect(portal).toMatch(/npm run check:client/);
  });

  test("regenerates the client from the committed contract and compares", () => {
    const check = scripts()["check:client"];
    expect(check, "portal/package.json has no `check:client` script").toBeTruthy();
    expect(check).toContain("openapi-typescript");
    expect(check).toContain("runtime-internal.openapi.json");
    expect(check).toMatch(/diff/);
    // Whatever it compares, it must not overwrite the committed file: the check
    // reports drift, it never silently fixes it.
    expect(check).not.toMatch(/-o\s+src\/runtime\/client\.ts/);
  });

  test("generates the client the same way the check regenerates it", () => {
    const { "gen:client": gen, "check:client": check } = scripts() as Record<string, string>;
    const version = (script: string) => /openapi-typescript@([\d.]+)/.exec(script)?.[1];
    expect(version(gen)).toBeTruthy();
    expect(version(check)).toBe(version(gen));
    expect(gen).toContain("../docs/contracts/runtime-internal.openapi.json");
    expect(check).toContain("../docs/contracts/runtime-internal.openapi.json");
  });

  test("has the other direction covered by the runtime job", () => {
    // `runtime/tests/test_contract_snapshot.py` fails when the runtime's routes
    // and the committed contract disagree; the runtime job runs the whole suite.
    expect(job("test")).toMatch(/uv run pytest/);
  });

  test("is documented in docs/contracts/README.md with both commands", () => {
    const readme = readFileSync(CONTRACT_README, "utf8");
    expect(readme).toContain("runtime-internal.openapi.json");
    expect(readme).toContain("make openapi");
    expect(readme).toContain("npm run gen:client");
    expect(readme).toContain("npm run check:client");
  });
});

describe("the committed runtime client", () => {
  const contract = JSON.parse(readFileSync(CONTRACT, "utf8"));
  const client = readFileSync(CLIENT, "utf8");

  const declared = (pattern: RegExp): string[] => {
    const found = new Set<string>();
    for (const match of client.matchAll(pattern)) {
      found.add(match[1]);
    }
    return [...found].sort();
  };

  test("declares exactly the paths the contract declares", () => {
    expect(declared(/^ {4}"(\/internal\/[^"]*)":/gm)).toEqual(
      Object.keys(contract.paths).sort(),
    );
  });

  test("declares exactly the operations the contract declares", () => {
    const ids: string[] = [];
    for (const methods of Object.values(contract.paths) as Record<string, any>[]) {
      for (const [method, operation] of Object.entries(methods)) {
        if (["get", "put", "post", "delete", "patch"].includes(method)) {
          ids.push(operation.operationId);
        }
      }
    }
    expect(declared(/\boperations\["([^"]+)"\]/g)).toEqual([...new Set(ids)].sort());
  });

  test("declares exactly the schemas the contract declares", () => {
    // `export interface components { schemas: { <name>: … } }`: the names sit at
    // eight spaces, the properties inside each schema deeper than that.
    const block = /^ {4}schemas: \{$([\s\S]*?)^ {4}\};$/m.exec(client);
    expect(block, "no `schemas` block in the generated client").toBeTruthy();
    const names = new Set<string>();
    for (const match of block![1].matchAll(/^ {8}([A-Za-z_][\w]*):/gm)) {
      names.add(match[1]);
    }
    expect([...names].sort()).toEqual(Object.keys(contract.components.schemas).sort());
  });
});
