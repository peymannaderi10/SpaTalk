import { execFileSync } from "child_process";
import { readFileSync } from "fs";
import { join } from "path";
import { Client } from "pg";

/**
 * The runtime side of the end-to-end suite.
 *
 * The portal owns no tenant, conversation, item or usage data, so its client
 * pages are only testable against a *running runtime* with something in it.
 * This module says where that runtime is, how the fixtures got there, and how a
 * test checks what the runtime recorded — an audit row, an item's state — which
 * no portal table can answer.
 */

export const RUNTIME_URL = (
  process.env.RUNTIME_INTERNAL_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export const RUNTIME_KEY =
  process.env.RUNTIME_INTERNAL_KEY ?? "dummy-internal-key";

export const RUNTIME_DIR = join(__dirname, "..", "..", "..", "runtime");

export const SEED_SCRIPT = join("..", "portal", "e2e-tests", "seed_runtime.py");

export const SEED_FILE = join(__dirname, "..", ".seed.json");

export const DATABASE_URL =
  process.env.RUNTIME_DATABASE_URL ??
  "postgresql://spatalk:spatalk@localhost:5434/spatalk";

export type Seed = {
  tenant: string;
  config_version: number;
  conversations: {
    handled: string;
    to_a_person: string;
    texted: string;
    chatted: string;
  };
  item_ids: number[];
};

/** The fixtures `global-setup.ts` put in the runtime, as it recorded them. */
export function seed(): Seed {
  return JSON.parse(readFileSync(SEED_FILE, "utf8")) as Seed;
}

/**
 * `uv` on a Linux box; `uv.exe` from WSL, where the runtime's virtualenv is a
 * Windows one because Wasp and Playwright are the only halves of this toolchain
 * that live inside WSL.
 */
export function uvBinary(): string {
  for (const candidate of ["uv", "uv.exe"]) {
    try {
      execFileSync(candidate, ["--version"], { stdio: "ignore" });
      return candidate;
    } catch {
      // try the next one
    }
  }
  throw new Error(
    "Neither `uv` nor `uv.exe` is on PATH, so the runtime fixtures cannot be " +
      "seeded. Install uv, or set RUNTIME_SEED_COMMAND to a command that runs " +
      "portal/e2e-tests/seed_runtime.py against the runtime's database.",
  );
}

export function seedCommand(): string[] {
  const override = process.env.RUNTIME_SEED_COMMAND;
  if (override) {
    return override.split(" ").filter(Boolean);
  }
  return [uvBinary(), "run", "python", SEED_SCRIPT];
}

export async function runtimeGet<T = any>(path: string): Promise<T> {
  const response = await fetch(`${RUNTIME_URL}${path}`, {
    headers: { "X-Internal-Key": RUNTIME_KEY },
  });
  if (!response.ok) {
    throw new Error(
      `GET ${path} on the runtime answered ${response.status}: ${await response.text()}`,
    );
  }
  return (await response.json()) as T;
}

export async function healthz(): Promise<{
  ok: boolean;
  tenants: string[];
  config_versions: Record<string, number>;
  commit: string;
}> {
  const response = await fetch(`${RUNTIME_URL}/healthz`);
  return response.json();
}

/** Polls `/healthz` until the tenant is on `version`, or gives up. */
export async function waitForConfigVersion(
  tenantId: string,
  version: number,
  timeoutMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let last: number | undefined;
  while (Date.now() < deadline) {
    const body = await healthz();
    last = body.config_versions?.[tenantId];
    if (last === version) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    `/healthz still reports config version ${last} for ${tenantId}, not ${version}, after ${timeoutMs}ms`,
  );
}

/**
 * The audit log is the runtime's, and nothing in the portal mirrors it, so the
 * only honest way to assert that reading a transcript was audited is to look at
 * the row the runtime wrote.
 */
export async function auditRows(
  recordType: string,
  recordId: string,
): Promise<{ actor: string; action: string }[]> {
  const client = new Client({ connectionString: DATABASE_URL });
  await client.connect();
  try {
    const { rows } = await client.query<{ actor: string; action: string }>(
      "select actor, action from runtime.audit_log " +
        "where record_type = $1 and record_id = $2 order by id",
      [recordType, recordId],
    );
    return rows;
  } finally {
    await client.end();
  }
}

export async function itemState(itemId: number): Promise<{
  state: string;
  acknowledged_by: string | null;
  resolved_by: string | null;
}> {
  const client = new Client({ connectionString: DATABASE_URL });
  await client.connect();
  try {
    const { rows } = await client.query(
      "select state, acknowledged_by, resolved_by from runtime.items where id = $1",
      [itemId],
    );
    return rows[0];
  } finally {
    await client.end();
  }
}
