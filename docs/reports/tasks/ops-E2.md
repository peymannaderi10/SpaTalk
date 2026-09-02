# operations plan Task E2: WAL-G backups to R2 and the restore drill

Status: done with deviations
Commit: <filled in below>
Tests: `uv run pytest -q tests/test_ops_backup_drill.py tests/test_deploy_assets.py` -> 21/21;
full suite `uv run pytest -q` -> 635/636 (see "Verification run": one failure and one error,
both from two agents' suites sharing one Postgres, both green on their own)
Interfaces produced: `runtime/scripts/db/{Dockerfile, postgresql.conf, walg.env.example, backup-cron,
walg-run, entrypoint-walg.sh}`; `runtime/scripts/restore-drill.sh --walg-env --source-url
[--network --image --target-time --expect-items --max-seconds --rpo-minutes --keep]`;
compose service `db` (built, tagged `spatalk-db:16`) and the `drill` profile services
`minio`, `minio-setup`; `.github/workflows/backup-drill.yml`; `docs/runbooks/backups.md`

## What the drill actually proved, here, today

The plan's own test is "the CI workflow is the test; locally the drill completes against
MinIO in Compose". The workflow cannot run on this machine, so the local drill was run
four times against MinIO in the `drill` profile, against a throwaway source database on
the compose network (never the shared development database on 5434, and never R2).

| Run | Command | Result |
|---|---|---|
| happy path | `bash scripts/restore-drill.sh --walg-env scripts/db/walg.env --network runtime_default --source-url postgresql+asyncpg://spatalk:spatalk@spatalk-drill-source:5432/spatalk --expect-items 6` | `restored in 18s (budget 900s)`, `runtime.items rows: 6`, `RPO ok`, `PASS`, exit 0 |
| wrong count | same with `--expect-items 99` | `FAIL expected 99 items, restored 6`, exit 1 |
| stale recovery point | `--rpo-minutes 1 --target-time '2026-09-02 21:00:20+00'` while the source had a message from 21:00:30 | `FAIL newest recovered message is older than 1m; the source had one at 2026-09-02 21:00:30`, exit 1 |
| idle source | `--rpo-minutes 0` | `WARNING source idle (no message in the last 0m), RPO check skipped`, `PASS`, exit 0 |

Six items came back: four written before `wal-g backup-push` and two that existed only in
archived WAL, so the base backup and the WAL replay were both exercised. The third run is
the one that matters most: a drill that cannot fail is not a drill.

Supporting evidence from the same session:

- `docker run --rm spatalk-db:16 wal-g --version` -> `wal-g version v3.0.9 3e49318 ... PostgreSQL`
- `select archived_count, failed_count, last_archived_wal from pg_stat_archiver` on the
  source -> `5|0|000000010000000000000004`: every segment reached MinIO, none failed.
- `cat /proc/*/comm` in the container -> `1 cron`, `7 postgres`: the cron daemon runs
  beside Postgres, which is the "WAL-G sidecar in the Postgres container" the plan allows.
- `/var/run/walg/env` is `-rw-r----- root postgres`, holding only the WAL-G variables.
- With `walg.env` absent the log reads
  `walg-run: no WALG_S3_PREFIX (walg.env absent), skipping: wal-g wal-push pg_wal/00000001000000010000005D`
  and Postgres recycles the segment normally.

## Deviations

1. **Base image `postgres:16-bookworm`, not `postgres:16-alpine`.** WAL-G ships glibc
   binaries only. Evidence:
   `curl -s https://api.github.com/repos/wal-g/wal-g/releases/latest | grep -o '"name": "wal-g-pg[^"]*"'`
   -> `wal-g-pg-20.04-*`, `wal-g-pg-22.04-*`, `wal-g-pg-24.04-*` and nothing musl. The
   alternative was a Go toolchain inside the database image. The Ubuntu 22.04 build
   (glibc 2.35) runs on bookworm (glibc 2.36); `wal-g --version` above is that binary.
   *Consequence for existing machines:* a `pgdata` volume initialised by the Alpine image
   starts fine on this one — checked against a copy of this machine's development volume,
   which crash-recovered and answered `select count(*) from runtime.tenants` -> `2`,
   `datcollate = en_US.utf8`, no collation-mismatch warning (musl records no collation
   version at all, so Postgres cannot warn). But musl and glibc order `en_US.utf8`
   differently, so text indexes built under the old image should be rebuilt: the runbook
   says recreate the volume or `reindex database spatalk` once. A fresh VPS is unaffected.

2. **`archive_command = '/usr/local/bin/walg-run wal-push %p'`, not `'wal-g wal-push %p'`.**
   `archive_mode` cannot be changed without a restart, so with the plan's literal command a
   machine without `walg.env` — every developer machine, and CI — would retry the same
   segment forever and never recycle WAL. `walg-run` execs `wal-g` the moment
   `WALG_S3_PREFIX` exists and otherwise logs one line and exits 0. Both halves are
   executed in `tests/test_ops_backup_drill.py` against a fake `wal-g` on PATH, not just
   read. It is also how cron gets an environment, since cron jobs inherit none.

3. **Two files in `scripts/db` beyond the four the plan lists**: `walg-run` (above) and
   `entrypoint-walg.sh`, which snapshots the WAL-G variables where cron can read them,
   starts `cron`, and then execs the image's own `docker-entrypoint.sh` unchanged. The
   plan asks for "a cron entry" inside a container whose PID 1 is Postgres; something has
   to start the daemon.

4. **Compose takes `walg.env` through `env_file: [{path: ..., required: false}]`, not a
   bind mount.** A bind mount of a file that does not exist makes Docker create a
   directory in its place, which breaks `docker compose up -d db` on a clean checkout —
   the same failure QA gate A raised for `.env` and the same fix (commit b972e20). The
   variables reach WAL-G either way.

5. **`runtime/tests/test_deploy_assets.py` was edited**, which is not in this task's Files
   block. Its `set(services) == {...}` assertion could not survive two new Compose
   services. It now asserts the same five services are the ones with no profile, which is
   strictly stronger — it would fail if a drill service were ever startable by default.
   Evidence: before the edit,
   `assert {'app', 'caddy', 'db', 'minio', 'minio-setup', 'portal-server', 'portal-web'} == {'db', 'app', ...}`.

6. **`runtime/.env.example` gained a comment block** saying the four `R2_*` variables the
   reference lists for E2 are read by WAL-G from `scripts/db/walg.env` under their `AWS_*`
   names, not by the runtime process. `docs/reference/api-surface.md` lists them as runtime
   variables ("WAL-G reads them as AWS_* in `walg.env`"); this records where they actually
   go so nobody puts them in `.env` and wonders why nothing is backed up. No value added.

7. **`.gitignore` gained `walg.env`.** The file holds the R2 credentials.

8. **`restore-drill.sh` exports `MSYS_NO_PATHCONV=1`.** Git Bash rewrote
   `/var/lib/postgresql/data` into `C:/Program Files/Git/var/lib/postgresql/data` on the
   way to `docker.exe`; WAL-G refused it with
   `Data directory from command line 'C:/Program Files/Git/var/lib/postgresql/data' is not the same as Postgres' one`.
   Two exports, no effect on Linux.

## Notes for neighbours

- **The `db` service is now built, not pulled.** The next `docker compose up -d db` on any
  machine rebuilds it and recreates the container. It is not an in-place change: read the
  reindex note above and in `docs/runbooks/backups.md` before doing it on a machine whose
  `pgdata` matters. The development database on port 5434 was deliberately left running on
  the old image by this task; nothing about the port, the credentials or
  `scripts/init-test-db.sql` changed.
- **`docker compose down` is now more dangerous than it was**, because the drill's MinIO is
  in the same project. Tear the drill down with
  `docker compose --profile drill rm -sf minio minio-setup`.
- The drill script takes `--network` (default `runtime_default`) and starts its throwaway
  container from `spatalk-db:16`, so any task that renames the image or the compose project
  has to update `IMAGE`/`NETWORK` defaults at the top of `scripts/restore-drill.sh`.
- `.github/workflows/backup-drill.yml` is a new workflow file; it does not touch `ci.yml`,
  which tasks E5, E6 and E8 also add workflows beside.
- E3's retention job and this backup schedule are deliberately an hour apart: retention at
  03:00 UTC, base backup at 03:30 UTC, so the nightly backup is taken after the deletes.

## Verification run

| Check | Result |
|---|---|
| `uv run pytest -q tests/test_ops_backup_drill.py` (before any artefact existed) | 15 failed |
| `uv run pytest -q tests/test_ops_backup_drill.py` | 15 passed |
| `uv run pytest -q tests/test_deploy_assets.py` | 6 passed |
| `uv run ruff check spatalk tests scenarios` | All checks passed |
| `docker compose config` | exit 0 |
| `docker build -t spatalk-db:16 ./scripts/db` | exit 0 |
| `docker compose --profile drill up -d minio minio-setup` | `Bucket created successfully drill/spatalk-backups` |
| local drill, four runs | table above |
| full suite `uv run pytest -q` | 633 passed, 1 failed, 1 error, 1 skipped in 945 s |
| `uv run pytest -q tests/test_delivery.py tests/test_edge_sync.py` (the two casualties, alone) | 12 passed in 5.4 s |

The one skip is the `GOOGLE_API_KEY` live test, as always. The failure
(`test_delivery.py::test_item_delivery_enqueues_per_destination_and_sends`) and the error
(`test_edge_sync.py::test_the_text_is_the_tenants_offline_reply_script_rendered`) are the
shared-database collision the runtime QA-gate-A fix report already documented: two agents
were running the suite against the one Compose Postgres at the same time, and
`pg_stat_activity` showed `DROP TABLE runtime.jobs` waiting behind another run's
`idle in transaction` holder while the suite took 945 s instead of its usual 135 s. The
symptom is `asyncpg ... connection is closed` and `KeyError: 'unknown tenant skincentrix'`
— a registry emptied under a running test, not a defect. Both files pass on their own,
immediately afterwards, and this task changes no runtime code: its only Python is a new
test module that reads files.
