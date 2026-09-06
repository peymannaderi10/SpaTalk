"""Task 16's failable check that does not need a VPS.

The real failable check in the plan is the first call from a mobile (deploy runbook,
"First real call"), which needs a bought number, DNS and a deployed VPS -- all founder
steps. These tests check the half an agent can check: that the deployment artefacts are
present, internally consistent, and carry no secrets.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import yaml

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent


def _compose() -> dict:
    return yaml.safe_load((RUNTIME / "docker-compose.yml").read_text(encoding="utf-8"))


def test_dockerfile_runs_the_cli_entry_point():
    text = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12" in text
    assert 'CMD ["spatalk", "serve", "--host", "0.0.0.0", "--port", "8000"]' in text
    assert "EXPOSE 8000" in text
    # The wheel cache must not survive into the final layer (5.1 GB of it, measured).
    assert "uv pip install --system --no-cache ." in text
    scripts = tomllib.loads((RUNTIME / "pyproject.toml").read_text(encoding="utf-8"))
    assert scripts["project"]["scripts"]["spatalk"] == "spatalk.cli:app"


def test_dockerignore_keeps_the_local_venv_and_env_out_of_the_image():
    ignored = {
        line.strip()
        for line in (RUNTIME / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {".venv", ".env"} <= ignored


def test_compose_has_db_app_and_caddy_wired_together():
    services = _compose()["services"]
    # The portal's two containers joined the project in portal plan Task C9; the
    # detail of how they are built is asserted from the portal's own suite
    # (`portal/src/ops/containers.server.test.ts`). The restore drill's MinIO joined
    # in operations Task E2 behind the `drill` profile, so it is not one of the
    # services `docker compose up` starts; `tests/test_ops_backup_drill.py` owns it.
    assert {name for name, svc in services.items() if not svc.get("profiles")} == {
        "db",
        "app",
        "portal-server",
        "portal-web",
        "caddy",
    }
    app = services["app"]
    assert app["build"]["context"] == "."
    # `.env` must be optional or `docker compose config` / `up -d db` fail on a clean
    # checkout before anyone has copied `.env.example` (QA gate A, minor finding).
    assert app["env_file"] == [{"path": ".env", "required": False}]
    # Inside the compose network the database is `db:5432`, never the host mapping.
    assert app["environment"]["DATABASE_URL"] == (
        "postgresql+asyncpg://spatalk:${POSTGRES_PASSWORD:-spatalk}@db:5432/spatalk"
    )
    assert app["depends_on"]["db"]["condition"] == "service_healthy"
    assert app["restart"] == "unless-stopped"
    caddy = services["caddy"]
    assert caddy["ports"] == ["80:80", "443:443"]
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]
    # Caddy substitutes {$API_HOST} and {$MEDIA_HOST} from its own environment.
    assert caddy["env_file"] == [{"path": ".env", "required": False}]
    assert caddy["depends_on"] == ["app", "portal-web", "portal-server"]
    assert services["db"]["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U spatalk"]


def test_caddyfile_proxies_both_hosts_to_the_app_container():
    text = (RUNTIME / "Caddyfile").read_text(encoding="utf-8")
    assert "{$API_HOST}" in text and "{$MEDIA_HOST}" in text
    assert len(re.findall(r"reverse_proxy app:8000", text)) == 2
    # The portal is two more sites on the same Caddy (portal plan, Task C9).
    assert "{$APP_HOST}" in text and "{$APP_API_HOST}" in text
    assert "reverse_proxy portal-web:80" in text
    assert "reverse_proxy portal-server:3001" in text
    env_example = (RUNTIME / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^API_HOST=", env_example, re.M)
    assert re.search(r"^MEDIA_HOST=", env_example, re.M)
    assert re.search(r"^APP_HOST=", env_example, re.M)
    assert re.search(r"^APP_API_HOST=", env_example, re.M)


def test_no_secret_is_baked_into_a_deployment_artefact():
    for name in ("Dockerfile", "docker-compose.yml", "Caddyfile"):
        text = (RUNTIME / name).read_text(encoding="utf-8")
        for var in ("TELNYX_API_KEY", "GOOGLE_API_KEY", "SECRET_KEY", "SLACK_SIGNING_SECRET"):
            assert var not in text, f"{name} must reference secrets only through env_file"


def test_deploy_runbook_carries_the_first_call_checklist():
    text = (ROOT / "docs" / "runbooks" / "deploy.md").read_text(encoding="utf-8")
    for needed in (
        "alembic upgrade head",
        "spatalk tenant import tenants/skincentrix",
        "spatalk numbers add",
        '{"ok":true,"tenants":["skincentrix"]}',
        "docs/research/costmodel.py",
    ):
        assert needed in text, f"deploy runbook is missing {needed!r}"
    checklist = text.split("## First real call")[1]
    # One numbered line per check in the plan's step 6.
    assert len(re.findall(r"^\d+\. ", checklist, re.M)) >= 9
    assert "p95" in checklist and "cancelled" in checklist


# --- production hardening (2026-09-06, deploy prep) -------------------------------------------


def _running_services() -> dict:
    return {name: svc for name, svc in _compose()["services"].items() if not svc.get("profiles")}


def test_compose_keeps_every_log_bounded_and_every_container_restarting():
    # Docker's json-file driver keeps logs forever by default; a chatty runtime fills an
    # 80 GB disk in a season. And a database without a restart policy stays down after
    # the VPS reboots while everything in front of it comes back and fails.
    for name, svc in _running_services().items():
        assert svc.get("restart") == "unless-stopped", name
        assert svc["logging"]["driver"] == "json-file", name
        options = svc["logging"]["options"]
        assert options["max-size"] and options["max-file"], name


def test_compose_publishes_postgres_on_loopback_and_takes_its_password_from_the_environment():
    services = _compose()["services"]
    db = services["db"]
    # `5434:5432` on a VPS is Postgres on the public internet with the password below.
    assert db["ports"] == ["${DB_BIND:-127.0.0.1}:5434:5432"]
    assert db["environment"]["POSTGRES_PASSWORD"] == "${POSTGRES_PASSWORD:-spatalk}"
    for name, scheme in (("app", "postgresql+asyncpg"), ("portal-server", "postgresql")):
        assert services[name]["environment"]["DATABASE_URL"] == (
            f"{scheme}://spatalk:${{POSTGRES_PASSWORD:-spatalk}}@db:5432/spatalk"
        ), name
    example = (RUNTIME / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^POSTGRES_PASSWORD=", example, re.M)
    assert re.search(r"^DB_BIND=", example, re.M)


def test_compose_health_checks_every_container_caddy_fronts():
    services = _compose()["services"]
    app_check = services["app"]["healthcheck"]
    assert app_check["test"][0] == "CMD" and "healthz" in " ".join(app_check["test"])
    assert app_check["start_period"]
    server_check = services["portal-server"]["healthcheck"]
    assert "auth/me" in " ".join(server_check["test"])
    assert services["portal-web"]["healthcheck"]["test"][0] == "CMD"
    # The deployed revision reaches /healthz through the build argument the deploy script sets.
    assert services["app"]["build"]["args"]["GIT_COMMIT"] == "${GIT_COMMIT:-}"
    # `env_file` overrides the image's ENV, so the `GIT_COMMIT=` line every copied example
    # carries would blank what the build baked in (seen 2026-09-06). The image therefore
    # also writes the revision beside the package, where `Settings` reads it back.
    dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
    assert "with_name('GIT_COMMIT')" in dockerfile


def test_env_example_never_puts_a_note_where_a_value_goes():
    # python-dotenv and Compose both read `KEY=   # note` as the note (2026-09-05,
    # TELNYX_PUBLIC_KEY); the example must not teach the shape, and must say why.
    example = (RUNTIME / ".env.example").read_text(encoding="utf-8")
    assert not re.findall(r"^[A-Z_]+=[ 	]*#.*$", example, re.M)
    assert "own line" in example


def test_deploy_script_pulls_builds_migrates_then_restarts_and_waits_for_health():
    script = RUNTIME / "scripts" / "deploy.sh"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    steps = (
        "git pull --ff-only",
        "GIT_COMMIT=",
        "docker compose build",
        "alembic upgrade head",
        "docker compose up -d --remove-orphans",
        "healthz",
    )
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions), "the deploy runs in the wrong order"
    # The schema changes before the new code serves, never on start-up.
    assert "docker compose run --rm" in text
    # LF only: the VPS runs it, and a CR ends `set -euo pipefail` with a stray character.
    assert "\r" not in text
    if shutil.which("bash"):
        check = subprocess.run(["bash", "-n"], input=text.encode(), capture_output=True)
        assert check.returncode == 0, check.stderr
    runbook = (ROOT / "docs" / "runbooks" / "deploy.md").read_text(encoding="utf-8")
    assert "scripts/deploy.sh" in runbook
    assert "ufw" in runbook and "POSTGRES_PASSWORD" in runbook
