import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "vitest";

/**
 * The portal's two containers and the Caddy routes in front of them
 * (portal plan, Task C9).
 *
 * The failable check for this task is running it — `docker compose build
 * portal-server portal-web`, then `docker compose up` and a request to each
 * host. That needs a Docker daemon, several minutes and a database, so it is
 * not a unit test; it is recorded in `docs/reports/tasks/portal-C9.md` and it
 * runs in CI.
 *
 * What is asserted here is the part that silently rots between those runs: the
 * two images build the app the way Wasp builds it, the server migrates itself
 * and listens where Caddy expects it, the web image is the built client with an
 * SPA fallback, Compose wires both to the database and to nothing else, and the
 * runbook tells a person the same story the files do.
 */

const REPO = join(__dirname, "..", "..", "..");
const DOCKERFILE_SERVER = join(REPO, "portal", "Dockerfile.server");
const DOCKERFILE_WEB = join(REPO, "portal", "Dockerfile.web");
const DOCKERIGNORE = join(REPO, "portal", ".dockerignore");
const COMPOSE = join(REPO, "runtime", "docker-compose.yml");
const CADDYFILE = join(REPO, "runtime", "Caddyfile");
const RUNTIME_ENV_EXAMPLE = join(REPO, "runtime", ".env.example");
const WORKFLOW = join(REPO, ".github", "workflows", "ci.yml");
const DEPLOY_RUNBOOK = join(REPO, "docs", "runbooks", "deploy.md");

function read(path: string): string {
  return readFileSync(path, "utf8");
}

/** A Dockerfile without its comment lines: comments must not satisfy a test. */
function instructions(path: string): string {
  return read(path)
    .split("\n")
    .filter((line) => !/^\s*#/.test(line))
    .join("\n");
}

/**
 * The lines of one Compose service: everything from `  <name>:` down to the
 * next line indented by exactly two spaces, which is the next service.
 */
function service(name: string): string {
  const lines = read(COMPOSE).split("\n");
  const start = lines.findIndex((line) => line === `  ${name}:`);
  expect(start, `docker-compose.yml has no service \`${name}\``).toBeGreaterThan(-1);
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => /^ {2}\S/.test(line));
  return (end === -1 ? rest : rest.slice(0, end)).join("\n");
}

/** The body of one Caddy site block, addressed by its site name. */
function site(address: string): string {
  const text = read(CADDYFILE);
  const start = text.indexOf(`${address} {`);
  expect(start, `the Caddyfile has no site \`${address}\``).toBeGreaterThan(-1);
  return text.slice(start, text.indexOf("\n}", start));
}

/** The lines of the `portal` job in the CI workflow. */
function portalJob(): string {
  const lines = read(WORKFLOW).split("\n");
  const start = lines.findIndex((line) => line === "  portal:");
  expect(start, "the workflow has no job `portal`").toBeGreaterThan(-1);
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => /^ {2}\S/.test(line));
  return (end === -1 ? rest : rest.slice(0, end)).join("\n");
}

describe("the portal server image", () => {
  test("builds the app with wasp in a builder stage", () => {
    const dockerfile = instructions(DOCKERFILE_SERVER);
    expect(dockerfile).toMatch(/^FROM .+ AS \S*builder/mi);
    // The same CLI version Task C1 built the app with; a floating version would
    // mean the image and the developer machine can disagree about the output.
    expect(dockerfile).toMatch(/@wasp\.sh\/wasp-cli@0\.25\.0/);
    expect(dockerfile).toMatch(/wasp build/);
  });

  test("bundles the Wasp server and starts it from that bundle", () => {
    const dockerfile = instructions(DOCKERFILE_SERVER);
    expect(dockerfile).toMatch(/npm run bundle/);
    // The production stage runs from the generated server directory, so
    // `npm run start` is Wasp's own start script over the bundle it just built.
    expect(dockerfile).toMatch(/WORKDIR \/portal\/\.wasp\/out\/server/);
    expect(dockerfile).toMatch(/npm run start/);
  });

  test("applies migrations with prisma migrate deploy on start", () => {
    const dockerfile = instructions(DOCKERFILE_SERVER);
    expect(dockerfile).toMatch(/prisma migrate deploy --schema=\.\.\/db\/schema\.prisma/);
    // `migrate-dev` prompts, and its answer to drift is to reset every schema
    // it can see — including the runtime's, which shares this database.
    expect(dockerfile).not.toMatch(/migrate-dev/);
    expect(dockerfile).not.toMatch(/migrate reset|db push/);
  });

  test("listens on port 3001, which is where Caddy sends the api host", () => {
    const dockerfile = instructions(DOCKERFILE_SERVER);
    expect(dockerfile).toMatch(/ENV PORT=3001/);
    expect(dockerfile).toMatch(/EXPOSE 3001/);
  });

  test("never copies a dotenv file into the image", () => {
    // The server's environment arrives at run time through Compose's
    // `env_file`. An image that carried `.env.server` would carry the Stripe
    // key and the internal key in a layer.
    expect(instructions(DOCKERFILE_SERVER)).not.toMatch(/COPY[^\n]*\.env/);
    expect(instructions(DOCKERFILE_WEB)).not.toMatch(/COPY[^\n]*\.env/);
    const ignored = read(DOCKERIGNORE);
    expect(ignored).toMatch(/^\.env$/m);
    expect(ignored).toMatch(/^\.env\.\*$/m);
    expect(ignored).toMatch(/^!\.env\.\*\.example$/m);
  });

  test("sends neither node_modules nor .wasp as build context", () => {
    // Both are generated inside the image; shipping the host's copies would be
    // gigabytes of context and a Linux image full of Windows binaries.
    const ignored = read(DOCKERIGNORE);
    expect(ignored).toMatch(/^node_modules\/?$/m);
    expect(ignored).toMatch(/^\.wasp\/?$/m);
    expect(ignored).toMatch(/^e2e-tests\/node_modules\/?$/m);
  });
});

describe("the portal web image", () => {
  test("builds the client against the api host given as a build argument", () => {
    const dockerfile = instructions(DOCKERFILE_WEB);
    expect(dockerfile).toMatch(/^ARG REACT_APP_API_URL/m);
    expect(dockerfile).toMatch(/ENV REACT_APP_API_URL=\$\{?REACT_APP_API_URL\}?/);
    expect(dockerfile).toMatch(/vite build/);
    // The client is a Vite build over Wasp's generated SDK, so the SDK has to
    // exist first: `wasp build` in the same stage.
    expect(dockerfile).toMatch(/wasp build/);
  });

  test("contains the built client, not its source", () => {
    const dockerfile = instructions(DOCKERFILE_WEB);
    expect(dockerfile).toMatch(/FROM caddy:/);
    // Wasp forces this output directory (`build.outDir` in its Vite plugin).
    expect(dockerfile).toMatch(/COPY --from=\S+ \/portal\/\.wasp\/out\/web-app\/build/);
  });

  test("serves it with an SPA fallback and the prerendered pages", () => {
    const dockerfile = instructions(DOCKERFILE_WEB);
    // Wasp's Vite SSR plugin writes the SPA shell to `200.html` and prerenders
    // `/privacy` and `/pricing` as directories with an `index.html`. Both have
    // to be served: `{path}` first, the shell last.
    expect(dockerfile).toMatch(/try_files \{path\} \{path\}\/index\.html \/200\.html/);
    expect(dockerfile).toMatch(/file_server/);
    expect(dockerfile).toMatch(/EXPOSE 80/);
  });
});

describe("the compose services", () => {
  test("build the portal images from the portal directory", () => {
    expect(service("portal-server")).toMatch(/context:\s*\.\.\/portal/);
    expect(service("portal-server")).toMatch(/dockerfile:\s*Dockerfile\.server/);
    expect(service("portal-web")).toMatch(/context:\s*\.\.\/portal/);
    expect(service("portal-web")).toMatch(/dockerfile:\s*Dockerfile\.web/);
  });

  test("bake the api host into the client at build time", () => {
    // `REACT_APP_*` is compiled into the bundle; it cannot be an env_file value.
    expect(service("portal-web")).toMatch(/REACT_APP_API_URL:\s*https:\/\/\$\{APP_API_HOST/);
  });

  test("give the portal server its environment from portal/.env.server", () => {
    const portalServer = service("portal-server");
    expect(portalServer).toMatch(/env_file:/);
    expect(portalServer).toMatch(/\.\.\/portal\/\.env\.server/);
    // Inside the Compose network Postgres is `db:5432`; the host mapping on the
    // db service is for the developer machine, and `.env.server` carries it.
    expect(portalServer).toMatch(/DATABASE_URL:\s*postgresql:\/\/spatalk:spatalk@db:5432\/spatalk/);
  });

  test("wait for the database and come back after a reboot", () => {
    const portalServer = service("portal-server");
    expect(portalServer).toMatch(/depends_on:[\s\S]*db:\s*\{\s*condition:\s*service_healthy\s*\}/);
    expect(portalServer).toMatch(/restart:\s*unless-stopped/);
    expect(service("portal-web")).toMatch(/restart:\s*unless-stopped/);
  });

  test("publish no port of their own: Caddy is the only way in", () => {
    expect(service("portal-server")).not.toMatch(/^\s*ports:/m);
    expect(service("portal-web")).not.toMatch(/^\s*ports:/m);
    const caddy = service("caddy");
    expect(caddy).toMatch(/portal-web/);
    expect(caddy).toMatch(/portal-server/);
  });
});

describe("the Caddy routes", () => {
  test("send the app host to the web container", () => {
    expect(site("{$APP_HOST}")).toMatch(/reverse_proxy portal-web:80/);
  });

  test("send the app-api host to the Wasp server", () => {
    expect(site("{$APP_API_HOST}")).toMatch(/reverse_proxy portal-server:3001/);
  });

  test("leave the runtime's own two sites alone", () => {
    expect(site("{$API_HOST}")).toMatch(/reverse_proxy app:8000/);
    expect(site("{$MEDIA_HOST}")).toMatch(/reverse_proxy app:8000/);
  });

  test("read both host names from the environment the runbook fills in", () => {
    const example = read(RUNTIME_ENV_EXAMPLE);
    expect(example).toMatch(/^APP_HOST=/m);
    expect(example).toMatch(/^APP_API_HOST=/m);
  });
});

describe("continuous integration", () => {
  test("builds both portal images", () => {
    const portal = portalJob();
    expect(portal).toMatch(/docker compose build[^\n]*portal-server[^\n]*portal-web/);
    expect(portal).toMatch(/APP_API_HOST:/);
  });
});

describe("the deploy runbook", () => {
  test("names the two new hosts and their DNS records", () => {
    const runbook = read(DEPLOY_RUNBOOK);
    expect(runbook).toMatch(/app\.<domain>/);
    expect(runbook).toMatch(/app-api\.<domain>/);
    expect(runbook).toMatch(/APP_HOST=app\.<domain>/);
    expect(runbook).toMatch(/APP_API_HOST=app-api\.<domain>/);
  });

  test("says the portal server migrates itself, unlike the runtime", () => {
    const runbook = read(DEPLOY_RUNBOOK);
    expect(runbook).toMatch(/prisma migrate deploy/);
    expect(runbook).toMatch(/migrate-dev/);
  });

  test("points Stripe and Google at the app-api host", () => {
    const runbook = read(DEPLOY_RUNBOOK);
    expect(runbook).toMatch(/https:\/\/app-api\.<domain>\/payments-webhook/);
    expect(runbook).toMatch(/https:\/\/app-api\.<domain>\/auth\/google\/callback/);
  });
});
