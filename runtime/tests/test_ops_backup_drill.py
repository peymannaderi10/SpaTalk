"""Task E2's failable checks for the backup artefacts.

The real check is the drill itself, and it needs Docker: `scripts/restore-drill.sh`
against the MinIO in `docker compose --profile drill`, weekly in
`.github/workflows/backup-drill.yml`, monthly by hand against R2
(`docs/runbooks/backups.md`). None of that can run inside pytest.

What pytest can hold is everything the drill depends on being true of the artefacts:
that the image pins a WAL-G it verifies, that Postgres is told to archive every
segment, that the wrapper the archive command calls really is a no-op until R2 is
configured (executed here, not read), that the drill script fetches the latest base
backup and replays WAL on top of it, and that no credential is committed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent
DB = RUNTIME / "scripts" / "db"
DRILL = RUNTIME / "scripts" / "restore-drill.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "backup-drill.yml"
RUNBOOK = ROOT / "docs" / "runbooks" / "backups.md"

def _shell() -> str | None:
    """A real POSIX shell. Git's `sh.exe` is bash; `C:\\Windows\\System32\\bash.exe` is
    the WSL launcher, which cannot open a Windows path and must not be picked."""
    for candidate in ("bash", "sh"):
        found = shutil.which(candidate)
        if found and "system32" not in found.lower():
            return found
    return None


SH = _shell()

# The bucket half of WALG_S3_PREFIX. Every artefact has to agree on it or a restore
# looks in the wrong place.
BUCKET = "spatalk-backups"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _compose() -> dict:
    return yaml.safe_load(_read(RUNTIME / "docker-compose.yml"))


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


# --------------------------------------------------------------------------- image


def test_db_image_installs_a_wal_g_it_pins_and_verifies():
    text = _read(DB / "Dockerfile")
    assert re.search(r"^FROM postgres:16", text, re.M), "the database stays Postgres 16"
    version = re.search(r"WALG_VERSION=(v\d+\.\d+\.\d+)", text)
    assert version, "the WAL-G version must be pinned, never 'latest'"
    assert re.search(r"WALG_SHA256=[0-9a-f]{64}", text), "the download must be checksummed"
    assert "sha256sum" in text, "the checksum must actually be verified"
    assert "releases/download/" in text and "${WALG_VERSION}" in text
    # The stock entrypoint still runs; ours only wraps it so cron starts beside Postgres.
    assert "entrypoint-walg.sh" in text
    assert "docker-entrypoint.sh" in _read(DB / "entrypoint-walg.sh")
    assert "config_file=/etc/postgresql/postgresql.conf" in text


def test_postgresql_conf_archives_every_segment_within_a_minute():
    conf = {}
    for raw in _read(DB / "postgresql.conf").splitlines():
        line = "" if raw.strip().startswith("#") else raw.split("#", 1)[0].strip()
        if "=" in line:
            key, _, value = line.partition("=")
            conf[key.strip()] = value.strip().strip("'")
    assert conf["archive_mode"] == "on"
    assert conf["archive_timeout"] == "60", "an idle clinic still loses at most a minute"
    assert conf["wal_level"] in {"replica", "logical"}
    # The wrapper is what makes an unconfigured machine survive archive_mode=on; it
    # delegates to `wal-g wal-push` the moment walg.env exists.
    assert conf["archive_command"] == "/usr/local/bin/walg-run wal-push %p"
    assert "exec wal-g" in _read(DB / "walg-run")
    assert conf["listen_addresses"] == "*", "a replaced config file must still listen"


def test_backup_cron_pushes_a_base_backup_daily_and_prunes_weekly():
    raw = _read(DB / "backup-cron")
    lines = [
        line
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" not in line.split()[0]
    ]
    daily = [line for line in lines if "backup-push" in line]
    weekly = [line for line in lines if "delete retain" in line]
    assert len(daily) == 1 and len(weekly) == 1
    minute, hour, dom, month, dow, user = daily[0].split()[:6]
    assert (minute, hour, dom, month, dow) == ("30", "3", "*", "*", "*"), "daily at 03:30"
    assert user == "postgres", "wal-g must read the data directory as its owner"
    assert "/var/lib/postgresql/data" in daily[0]
    assert "delete retain FULL 7 --confirm" in weekly[0]
    assert weekly[0].split()[4] != "*", "the prune is weekly, not daily"
    assert raw.endswith("\n"), "cron ignores a file with no final newline"


# ------------------------------------------------------------------- the wrapper


def _fake_wal_g(tmp_path: Path) -> tuple[Path, Path]:
    """A `wal-g` on PATH that records the arguments it was called with."""
    called = tmp_path / "called"
    fake = tmp_path / "bin"
    fake.mkdir()
    script = fake / "wal-g"
    script.write_text(
        '#!/bin/sh\necho "$@" > "' + _posix(called) + '"\n', encoding="utf-8", newline="\n"
    )
    script.chmod(0o755)
    return fake, called


@pytest.mark.skipif(SH is None, reason="needs a POSIX shell to execute the wrapper")
def test_the_archive_wrapper_is_a_silent_no_op_until_r2_is_configured(tmp_path):
    """archive_mode cannot be turned off without a restart, so an unconfigured
    machine must still return 0 for every segment or the archiver wedges."""
    fake, called = _fake_wal_g(tmp_path)
    env = {
        "PATH": _posix(fake) + ":/usr/bin:/bin",
        "WALG_ENV_SNAPSHOT": _posix(tmp_path / "absent"),
    }
    done = subprocess.run(
        [SH, _posix(DB / "walg-run"), "wal-push", "pg_wal/000000010000000000000001"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    assert not called.exists(), "nothing may be uploaded when no store is configured"


@pytest.mark.skipif(SH is None, reason="needs a POSIX shell to execute the wrapper")
def test_the_archive_wrapper_calls_wal_g_once_walg_env_is_there(tmp_path):
    fake, called = _fake_wal_g(tmp_path)
    # Cron inherits no container environment, so the wrapper reads the snapshot the
    # entrypoint writes. This is the path the nightly backup-push takes.
    snapshot = tmp_path / "walg.env"
    snapshot.write_text("WALG_S3_PREFIX=s3://" + BUCKET + "/pg\n", encoding="utf-8", newline="\n")
    env = {"PATH": _posix(fake) + ":/usr/bin:/bin", "WALG_ENV_SNAPSHOT": _posix(snapshot)}
    done = subprocess.run(
        [SH, _posix(DB / "walg-run"), "wal-push", "pg_wal/000000010000000000000001"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    assert called.read_text(encoding="utf-8").strip() == (
        "wal-push pg_wal/000000010000000000000001"
    )


# ------------------------------------------------------------------- credentials


def test_walg_env_example_maps_the_r2_variables_and_holds_no_value():
    text = _read(DB / "walg.env.example")
    values = {}
    for line in text.splitlines():
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.split("#", 1)[0].strip()
    # WAL-G speaks S3, so R2's four values arrive under their AWS names.
    assert values["AWS_ACCESS_KEY_ID"] == "" and values["AWS_SECRET_ACCESS_KEY"] == ""
    assert values["AWS_ENDPOINT"] == ""
    assert values["AWS_S3_FORCE_PATH_STYLE"] == "true"
    assert values["WALG_S3_PREFIX"] == "s3://" + BUCKET + "/pg"
    # wal-g connects to the database to bracket a base backup, and this cluster has
    # no `postgres` role: POSTGRES_USER is `spatalk`.
    assert values["PGUSER"] == "spatalk" and values["PGDATABASE"] == "spatalk"
    for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET"):
        assert name in text, "say which R2_* value from accounts-and-env.md feeds " + name


def test_the_real_walg_env_can_never_be_committed():
    ignored = [
        line.strip()
        for line in _read(ROOT / ".gitignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "walg.env" in ignored
    tracked = subprocess.run(
        ["git", "ls-files", "runtime/scripts/db"], cwd=ROOT, capture_output=True, text=True
    )
    assert "runtime/scripts/db/walg.env\n" not in tracked.stdout


def test_no_credential_is_baked_into_a_backup_artefact():
    for path in (
        DB / "Dockerfile",
        DB / "postgresql.conf",
        DB / "walg.env.example",
        DB / "backup-cron",
        DB / "walg-run",
        DB / "entrypoint-walg.sh",
        DRILL,
        WORKFLOW,
        RUNTIME / "docker-compose.yml",
    ):
        text = _read(path)
        for line in text.splitlines():
            found = re.search(r"AWS_(?:SECRET_ACCESS_KEY|ACCESS_KEY_ID)\s*[=:]\s*(\S+)", line)
            # A value is only allowed to be a variable reference: `$SOMETHING` in a
            # workflow, `${SOMETHING}` in Compose. A literal is a committed credential.
            if found:
                assert found.group(1).startswith("$"), path.name + ": " + line.strip()
        assert not re.search(r"\bAKIA[0-9A-Z]{16}\b", text)


# ---------------------------------------------------------------------- compose


def test_compose_builds_the_database_from_scripts_db_and_takes_walg_env_optionally():
    db = _compose()["services"]["db"]
    assert db["build"]["context"] == "./scripts/db"
    # Tagged, because the drill starts a throwaway container from the same image.
    assert db["image"] == "spatalk-db:16"
    # Optional for the same reason `app`'s .env is (QA gate A): a clean checkout has
    # no credentials and `docker compose up -d db` must still work.
    assert db["env_file"] == [{"path": "./scripts/db/walg.env", "required": False}]
    # The host port and the test-database bootstrap are unchanged; the bind address is
    # loopback unless `.env` widens it (deploy prep, 2026-09-06).
    assert db["ports"] == ["${DB_BIND:-127.0.0.1}:5434:5432"]
    assert any("init-test-db.sql" in v for v in db["volumes"])
    assert "profiles" not in db, "the database is not a drill-only service"


def test_the_drill_profile_holds_minio_and_starts_with_nobody_else():
    services = _compose()["services"]
    default = {name for name, svc in services.items() if not svc.get("profiles")}
    assert default == {"db", "app", "portal-server", "portal-web", "caddy"}
    drill = {name for name, svc in services.items() if svc.get("profiles") == ["drill"]}
    assert drill == {"minio", "minio-setup"}
    minio = services["minio"]
    assert re.match(r"^minio/minio:RELEASE\.", minio["image"]), "pin the MinIO release"
    assert "server /data" in minio["command"]
    # The bucket the drill restores from is the same name R2 holds.
    assert BUCKET in yaml.safe_dump(services["minio-setup"])
    assert services["minio-setup"]["depends_on"]["minio"]["condition"] == "service_healthy"
    assert "5434" not in yaml.safe_dump(minio), "MinIO must not touch the database port"


# ------------------------------------------------------------------ drill script


@pytest.mark.skipif(SH is None, reason="needs a POSIX shell to parse the drill script")
def test_the_drill_script_parses():
    done = subprocess.run([SH, "-n", _posix(DRILL)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_drill_restores_the_latest_backup_and_replays_wal_on_top_of_it():
    text = _read(DRILL)
    assert "--source-url" in text and "--walg-env" in text
    assert "backup-fetch" in text and "LATEST" in text
    assert "recovery.signal" in text, "without it Postgres starts as if nothing was lost"
    assert "restore_command = 'wal-g wal-fetch %f %p'" in text
    assert "archive_mode = off" in text, "the clone must never push WAL over the source"
    assert "select count(*) from runtime.items" in text
    assert "select max(created_at) from runtime.messages" in text
    assert "docker rm" in text, "the throwaway container and volume are removed"
    assert "trap" in text, "cleanup has to survive a failure too"


def test_the_drill_fails_on_a_slow_restore_or_a_stale_recovery_point():
    text = _read(DRILL)
    assert re.search(r"MAX_SECONDS=\$\{MAX_SECONDS:-900\}", text), "15 minutes"
    assert re.search(r"RPO_MINUTES=\$\{RPO_MINUTES:-10\}", text)
    # An idle source has nothing recent to lose: warn, do not fail.
    assert "idle" in text.lower()
    assert text.count("exit 1") >= 3


# --------------------------------------------------------------------- workflow


def test_the_backup_drill_workflow_runs_weekly_and_on_demand_against_minio():
    spec = yaml.safe_load(_read(WORKFLOW))
    triggers = spec[True] if True in spec else spec["on"]
    assert "workflow_dispatch" in triggers
    cron = triggers["schedule"][0]["cron"].split()
    assert cron[4] != "*", "weekly, not daily"
    steps = spec["jobs"]["drill"]["steps"]
    run = "\n".join(step.get("run", "") for step in steps)
    assert "docker build" in run and "runtime/scripts/db" in run
    assert "minio/minio:RELEASE." in run
    assert "backup-push" in run, "seed, back up, then write more rows"
    assert "pg_switch_wal" in run, "the rows after the backup only survive in archived WAL"
    assert "scripts/restore-drill.sh" in run
    assert "--expect-items" in run, "the drill has to assert the counts, not print them"
    assert "alembic upgrade head" in run, "the drill restores the real runtime schema"


def test_the_backups_runbook_says_what_is_kept_and_how_to_get_it_back():
    text = _read(RUNBOOK)
    for heading in (
        "## What is backed up",
        "## Run the drill locally",
        "## Restore for real",
        "## Monthly drill against R2",
    ):
        assert heading in text, "the runbook is missing " + heading
    for needed in (
        "walg.env",
        "docker compose --profile drill",
        "scripts/restore-drill.sh",
        "wal-g backup-fetch",
        BUCKET,
        "recovery_target_time",
        "docs/runbooks/accounts-and-env.md",
    ):
        assert needed in text, "the runbook is missing " + needed
    # The two numbers the drill enforces have to be written down somewhere a human reads.
    assert "15 minutes" in text and "10 minutes" in text
    monthly = text.split("## Monthly drill against R2")[1]
    assert len(re.findall(r"^\d+\. ", monthly, re.M)) >= 4
