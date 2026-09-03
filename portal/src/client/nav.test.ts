import { existsSync, readFileSync, readdirSync, statSync } from "fs";
import { dirname, join } from "path";
import { describe, expect, it } from "vitest";
import {
  allNavItems,
  navPath,
  navRoute,
  NAV_SECTIONS,
  ROUTES_OFF_THE_SIDEBAR,
  visibleSections,
} from "./nav";

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

/**
 * Every route the Wasp spec declares under `/app/:orgSlug` or `/admin`, read
 * out of the spec files themselves so a route added tomorrow shows up here
 * without anyone remembering to edit a list.
 */
function declaredRoutes(): string[] {
  const specs = [join(PORTAL_ROOT, "main.wasp.ts"), ...waspSpecsUnder(join(PORTAL_ROOT, "src"))];
  const routes = new Set<string>();

  for (const spec of specs) {
    const source = readFileSync(spec, "utf8");
    // route("Name", "/path", page(...)) - the path is the second argument,
    // and Prettier may have put it on its own line.
    const pattern = /\broute\(\s*"[^"]+"\s*,\s*"([^"]+)"/g;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(source)) !== null) {
      const path = match[1];
      if (path.startsWith("/app/:orgSlug") || path === "/admin" || path.startsWith("/admin/")) {
        routes.add(path);
      }
    }
  }

  return [...routes].sort();
}

function waspSpecsUnder(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...waspSpecsUnder(full));
    } else if (entry.endsWith(".wasp.ts")) {
      out.push(full);
    }
  }
  return out;
}

describe("the sidebar model", () => {
  const declared = declaredRoutes();

  it("reads the routes out of the Wasp spec", () => {
    // A guard on the guard: if the regex ever stopped matching, every other
    // test in this file would pass vacuously.
    expect(declared).toContain("/app/:orgSlug/overview");
    expect(declared).toContain("/admin");
    expect(declared.length).toBeGreaterThanOrEqual(10);
  });

  it("accounts for every declared route exactly once", () => {
    const inSidebar = allNavItems().map((item) => navRoute(item.to));
    const offSidebar = ROUTES_OFF_THE_SIDEBAR.map((entry) => entry.route);

    const accounted = [...new Set(inSidebar), ...offSidebar].sort();
    expect(accounted).toEqual(declared);

    // A route is either on the sidebar or deliberately off it, never both.
    for (const route of offSidebar) {
      expect(inSidebar).not.toContain(route);
    }
  });

  it("invents no route the Wasp spec does not declare", () => {
    for (const item of allNavItems()) {
      expect(declared, `${item.testId} points at a route nothing declares`).toContain(
        navRoute(item.to),
      );
    }
  });

  it("gives every route it shows exactly one sidebar item, apart from the settings tabs", () => {
    const counts = new Map<string, number>();
    for (const item of allNavItems()) {
      const route = navRoute(item.to);
      counts.set(route, (counts.get(route) ?? 0) + 1);
    }

    for (const [route, count] of counts) {
      if (route === "/app/:orgSlug/settings") {
        // The settings page holds several tabs, one sidebar item each; they
        // differ by query string, which is what makes them distinct items.
        expect(count).toBeGreaterThan(1);
      } else {
        expect(count, `${route} appears ${count} times in the sidebar`).toBe(1);
      }
    }
  });

  it("keeps every `to` and every testId unique", () => {
    const items = allNavItems();
    expect(new Set(items.map((item) => item.to)).size).toBe(items.length);
    expect(new Set(items.map((item) => item.testId)).size).toBe(items.length);
  });

  it("says why each route it leaves off the sidebar is off it", () => {
    for (const entry of ROUTES_OFF_THE_SIDEBAR) {
      expect(entry.reason.length).toBeGreaterThan(20);
    }
  });

  it("carries the sections the shell expects, in order", () => {
    expect(NAV_SECTIONS.map((section) => section.title)).toEqual([
      "Front desk",
      "Setup",
      "Account",
      "Platform",
    ]);
  });

  it("shows a staff member the front desk and the setup, and nothing else", () => {
    const sections = visibleSections({ orgSlug: "skincentrix", role: "STAFF", isAdmin: false });
    expect(sections.map((section) => section.title)).toEqual(["Front desk", "Setup"]);
  });

  it("shows an owner billing and people as well", () => {
    const sections = visibleSections({ orgSlug: "skincentrix", role: "OWNER", isAdmin: false });
    expect(sections.map((section) => section.title)).toEqual([
      "Front desk",
      "Setup",
      "Account",
    ]);
  });

  it("shows the platform section to an agency admin only", () => {
    const admin = visibleSections({ orgSlug: "skincentrix", role: "STAFF", isAdmin: true });
    expect(admin.map((section) => section.title)).toContain("Platform");

    const staff = visibleSections({ orgSlug: "skincentrix", role: "STAFF", isAdmin: false });
    expect(staff.map((section) => section.title)).not.toContain("Platform");
  });

  it("fills the organisation into a path and leaves the query alone", () => {
    expect(navPath("/app/:orgSlug/overview", "skincentrix")).toBe("/app/skincentrix/overview");
    expect(navPath("/app/:orgSlug/settings?tab=hours", "skincentrix")).toBe(
      "/app/skincentrix/settings?tab=hours",
    );
    expect(navPath("/admin/users", "skincentrix")).toBe("/admin/users");
  });

  it("gives every item something to render", () => {
    for (const item of allNavItems()) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.icon).toBeTruthy();
      expect(item.testId).toMatch(/^nav-[a-z0-9-]+$/);
    }
  });
});
