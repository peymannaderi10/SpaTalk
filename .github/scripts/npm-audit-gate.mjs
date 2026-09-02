#!/usr/bin/env node
// `npm audit` with an allowlist (operations plan, Task E8).
//
// `npm audit --audit-level=high` on its own cannot pass in this repository: the portal's
// committed lockfile carries the Wasp-generated development server, whose nodemon chain has
// three high advisories with no non-breaking fix. A gate that is permanently red stops being
// read, so this wrapper fails on any high or critical advisory that is *not* in
// `.github/npm-audit-allow.json`, and prints — without failing — the accepted ones and any
// allowlist entry that no longer matches anything.
//
// Usage: node .github/scripts/npm-audit-gate.mjs <project-dir> [allowlist.json]

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FAIL_ON = new Set(["high", "critical"]);
const here = dirname(fileURLToPath(import.meta.url));
const projectDir = resolve(process.argv[2] ?? ".");
const allowPath = resolve(process.argv[3] ?? resolve(here, "..", "npm-audit-allow.json"));

// `--package-lock-only` is what makes this deterministic: it audits the committed lockfile,
// so the answer does not depend on whether anyone ran `npm ci` or `wasp build` first.
const audit = spawnSync("npm", ["audit", "--json", "--package-lock-only"], {
  cwd: projectDir,
  encoding: "utf8",
  maxBuffer: 64 * 1024 * 1024,
  // Node refuses to spawn a `.cmd` shim without a shell, and npm on Windows is one.
  shell: process.platform === "win32",
});
if (audit.error) {
  console.error(`npm audit could not be run in ${projectDir}: ${audit.error.message}`);
  process.exit(2);
}

let report;
try {
  report = JSON.parse(audit.stdout);
} catch {
  console.error(`npm audit did not return JSON in ${projectDir}:`);
  console.error(audit.stdout.slice(0, 4000) || audit.stderr.slice(0, 4000));
  process.exit(2);
}
if (report.error) {
  console.error(`npm audit failed in ${projectDir}: ${report.error.summary ?? "unknown error"}`);
  process.exit(2);
}

const allow = JSON.parse(readFileSync(allowPath, "utf8"));
for (const entry of allow.advisories ?? []) {
  if (!entry.id || !entry.package || !entry.reason) {
    console.error(`allowlist entry needs id, package and reason: ${JSON.stringify(entry)}`);
    process.exit(2);
  }
}
// An entry may name the project it belongs to, so the worker's run does not report the
// portal's accepted findings as stale.
const projectKey = (process.argv[2] ?? ".").replace(/\\/g, "/").replace(/\/+$/, "");
const accepted = new Set(
  (allow.advisories ?? [])
    .filter((e) => !e.workspace || e.workspace === projectKey)
    .map((e) => `${e.package}::${e.id}`),
);
const used = new Set();

// What each vulnerability is blamed on: a GHSA id when npm has the advisory itself, and the
// name of the dependency when the package only inherits one.
const causesOf = (vulnerability) =>
  (vulnerability.via ?? []).map((via) =>
    typeof via === "string" ? via : (via.url ?? "").split("/").pop() || String(via.source),
  );

const blocking = [];
const carried = [];
for (const [name, vulnerability] of Object.entries(report.vulnerabilities ?? {})) {
  if (!FAIL_ON.has(vulnerability.severity)) continue;
  const causes = causesOf(vulnerability);
  const unaccepted = causes.filter((cause) => !accepted.has(`${name}::${cause}`));
  for (const cause of causes) used.add(`${name}::${cause}`);
  (unaccepted.length ? blocking : carried).push({ name, vulnerability, causes, unaccepted });
}

console.log(`npm audit (${projectDir})`);
for (const { name, vulnerability, causes } of carried) {
  console.log(`  accepted  ${vulnerability.severity} ${name} [${causes.join(", ")}]`);
}
for (const key of accepted) {
  if (!used.has(key)) console.log(`  stale     allowlist entry no longer reported: ${key}`);
}
for (const { name, vulnerability, unaccepted } of blocking) {
  console.log(`  BLOCKING  ${vulnerability.severity} ${name} [${unaccepted.join(", ")}]`);
  for (const via of vulnerability.via ?? []) {
    if (typeof via !== "string") console.log(`            ${via.title} — ${via.url}`);
  }
}

if (blocking.length) {
  console.error(
    `\n${blocking.length} high or critical advisory not in ${allowPath}. Upgrade the ` +
      "dependency, or add it with a reason once you have read it.",
  );
  process.exit(1);
}
console.log(`  ok        no unaccepted high or critical advisory`);
