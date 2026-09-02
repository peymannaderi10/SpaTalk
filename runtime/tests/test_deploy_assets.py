"""Task 16's failable check that does not need a VPS.

The real failable check in the plan is the first call from a mobile (deploy runbook,
"First real call"), which needs a bought number, DNS and a deployed VPS -- all founder
steps. These tests check the half an agent can check: that the deployment artefacts are
present, internally consistent, and carry no secrets.
"""

from __future__ import annotations

import re
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
    assert set(services) == {"db", "app", "caddy"}
    app = services["app"]
    assert app["build"] == "."
    assert app["env_file"] == ".env"
    # Inside the compose network the database is `db:5432`, never the host mapping.
    assert app["environment"]["DATABASE_URL"] == "postgresql+asyncpg://spatalk:spatalk@db:5432/spatalk"
    assert app["depends_on"]["db"]["condition"] == "service_healthy"
    assert app["restart"] == "unless-stopped"
    caddy = services["caddy"]
    assert caddy["ports"] == ["80:80", "443:443"]
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]
    # Caddy substitutes {$API_HOST} and {$MEDIA_HOST} from its own environment.
    assert caddy["env_file"] == ".env"
    assert caddy["depends_on"] == ["app"]
    assert services["db"]["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U spatalk"]


def test_caddyfile_proxies_both_hosts_to_the_app_container():
    text = (RUNTIME / "Caddyfile").read_text(encoding="utf-8")
    assert "{$API_HOST}" in text and "{$MEDIA_HOST}" in text
    assert len(re.findall(r"reverse_proxy app:8000", text)) == 2
    env_example = (RUNTIME / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^API_HOST=", env_example, re.M)
    assert re.search(r"^MEDIA_HOST=", env_example, re.M)


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
