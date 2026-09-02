import { execFileSync } from "child_process";
import { writeFileSync } from "fs";
import {
  RUNTIME_DIR,
  RUNTIME_URL,
  SEED_FILE,
  seedCommand,
} from "./tests/runtime";

/**
 * Puts one tenant and its fixtures into the runtime, then waits for a runtime
 * to answer, before any test runs.
 *
 * The seeding is a runtime-side script (`seed_runtime.py`) using the runtime's
 * own models: the portal has no connection to the `runtime` schema and must not
 * grow one (CLAUDE.md non-negotiable 7).
 */

async function waitForRuntime(timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "no attempt made";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${RUNTIME_URL}/healthz`);
      if (response.ok) {
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (caught) {
      lastError = String(caught);
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(
    `No runtime answered ${RUNTIME_URL}/healthz within ${timeoutMs}ms (${lastError}). ` +
      `Start one with \`INTERNAL_API_KEY=<the portal's RUNTIME_INTERNAL_KEY> uv run spatalk serve\` ` +
      `from runtime/, or point RUNTIME_INTERNAL_URL at a running one. ` +
      `See e2e-tests/README.md.`,
  );
}

export default async function globalSetup(): Promise<void> {
  const [command, ...args] = seedCommand();
  const output = execFileSync(command, args, {
    cwd: RUNTIME_DIR,
    encoding: "utf8",
  });
  const lines = output.trim().split("\n");
  const summary = lines[lines.length - 1];
  writeFileSync(SEED_FILE, summary + "\n", "utf8");
  console.log(`seeded the runtime: ${summary}`);

  await waitForRuntime();
}
