#!/usr/bin/env bash
# One deploy of the whole stack, on the VPS, from runtime/:
#
#     bash scripts/deploy.sh
#
# Pull, build the three images, migrate the runtime schema with the new image, swap
# the containers, wait for the runtime to report healthy, print what it reports. The
# portal server migrates its own schema when it starts (portal/Dockerfile.server); the
# runtime never migrates itself, so its schema changes here, before the new code
# serves, and nowhere else. Every step is safe to run again: a deploy that stops
# half-way is finished by running it once more.
#
# The first run builds everything from scratch (Torch and ONNX for the runtime, the
# Wasp toolchain twice for the portal): allow fifteen minutes. After that the layer
# cache makes it a couple of minutes.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "runtime/.env is missing: cp .env.example .env and fill it (docs/runbooks/accounts-and-env.md)" >&2
    exit 1
fi

echo "== pull"
git pull --ff-only

# Reported by the health endpoint as `commit`, so the portal's health page and a curl
# both name the revision that is serving.
GIT_COMMIT="$(git rev-parse --short HEAD)"
export GIT_COMMIT
echo "== build $GIT_COMMIT"
docker compose build app portal-server portal-web

echo "== migrate"
docker compose up -d --wait db
docker compose run --rm --no-deps app alembic upgrade head

echo "== restart"
docker compose up -d --remove-orphans

echo "== wait for the runtime"
status="starting"
for _ in $(seq 1 24); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q app)" 2>/dev/null || echo starting)"
    if [ "$status" = "healthy" ]; then
        break
    fi
    sleep 5
done
if [ "$status" != "healthy" ]; then
    echo "the runtime is '$status' two minutes after start; read: docker compose logs --tail 100 app" >&2
    exit 1
fi
docker compose exec -T app python -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=10))
print(json.dumps({k: d.get(k) for k in ('ok', 'tenants', 'commit', 'dead_jobs', 'llm')}))
"

# Images the previous deploy left behind; the data volumes are never touched.
docker image prune -f >/dev/null
docker compose ps
