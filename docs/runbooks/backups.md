# Backups and restore

The clinic's ledger lives in one Postgres on one VPS. This is how it survives that box
being deleted, and how you find out — every week, automatically, and every month by
hand — that it really would.

Operations plan Task E2. Spec §10 weakness 6.

## What is backed up

| | |
|---|---|
| What | The whole `spatalk` cluster: the `runtime` schema (conversations, messages, items, usage, jobs, audit log) and the portal's `public` schema, in one physical backup. |
| How | WAL-G in the database container. Every WAL segment is pushed as it closes (`archive_command`), and `archive_timeout = 60` closes an idle one every minute. A base backup goes up nightly at 03:30 UTC. |
| Where | Cloudflare R2, bucket `spatalk-backups`, prefix `pg`. Same account as the Turnstile keys; see `docs/runbooks/accounts-and-env.md` step 1. |
| Kept | The last 7 base backups and the WAL they need. Pruned Sundays at 04:30 UTC (`wal-g delete retain FULL 7 --confirm`). |
| Costs | Under a dollar a month at this size. R2 has no egress charge, which is the reason it is R2. |
| RPO | One minute of writes, worst case. RTO: the restore drill's budget is 15 minutes. |
| Not backed up | Recordings (none exist), `.env`, `walg.env`, tenant bundles. Those live in the repository and in your password manager. |

The database container is built from `runtime/scripts/db`: stock `postgres:16-bookworm`
plus a pinned WAL-G. Nothing else in the stack changes.

One caveat for a machine that already has a `pgdata` volume: it was initialised by
`postgres:16-alpine`, whose musl sorts `en_US.utf8` differently from this image's glibc.
The cluster starts and reads correctly on the new image (checked against a copy of the
development volume), but indexes on text columns were built under the other ordering, so
either recreate the volume — local data is disposable — or run
`docker compose exec db psql -U spatalk -c "reindex database spatalk"` once after the
switch. A VPS that starts on this image is unaffected.

## Turning it on (once, on the VPS)

1. Get the R2 values from `docs/runbooks/accounts-and-env.md` step 1: `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET=spatalk-backups`.
2. `cp runtime/scripts/db/walg.env.example runtime/scripts/db/walg.env` and fill it in.
   The R2 values go under their AWS names — WAL-G speaks S3 and R2 is S3-compatible.
   `walg.env` is gitignored; it must never be committed.
3. `docker compose up -d --build db`. The first build downloads WAL-G and verifies its
   checksum.
4. Check the archiver has somewhere to put things:

   ```bash
   docker compose exec db psql -U spatalk -tAc \
     "select archived_count, failed_count, last_archived_wal from pg_stat_archiver"
   ```

   `failed_count` must stay 0. If it climbs, `docker compose exec db cat /var/log/walg.log`.
5. Take the first base backup by hand instead of waiting for 03:30:

   ```bash
   docker compose exec -u postgres db walg-run backup-push /var/lib/postgresql/data
   docker compose exec -u postgres db wal-g backup-list
   ```

With no `walg.env` the archive command and both cron jobs are successful no-ops: the
database runs, and nothing is backed up. That is the developer-machine default and it is
deliberate — `archive_mode` cannot be turned off without a restart, so the alternative is
a machine whose WAL piles up forever. It is also why step 4 is not optional.

## Run the drill locally

No cloud account needed: MinIO stands in for R2 inside Compose.

```bash
cd runtime
docker compose --profile drill up -d minio minio-setup      # object store + bucket
cp scripts/db/walg.env.example scripts/db/walg.env
# point it at MinIO instead of R2:
#   AWS_ACCESS_KEY_ID=spatalkdrill
#   AWS_SECRET_ACCESS_KEY=spatalkdrill
#   AWS_ENDPOINT=http://minio:9000
docker compose up -d --build db
docker compose exec -u postgres db walg-run backup-push /var/lib/postgresql/data
bash scripts/restore-drill.sh \
  --walg-env scripts/db/walg.env \
  --source-url postgresql://spatalk:spatalk@db:5432/spatalk
```

Tear the drill down with `docker compose --profile drill rm -sf minio minio-setup`. Never
`docker compose down` for this: it would take the clinic's database and the portal with
it.

On Windows run the script from Git Bash. It exports `MSYS_NO_PATHCONV=1` for you, because
Git Bash otherwise rewrites `/var/lib/postgresql/data` into a Windows path on its way to
`docker.exe` and WAL-G refuses it.

`scripts/restore-drill.sh` creates a throwaway container from the same image on a fresh
volume, runs `wal-g backup-fetch` for the latest base backup, writes `recovery.signal`
with `restore_command = 'wal-g wal-fetch %f %p'`, starts Postgres, waits for recovery to
finish, then reads `count(*)` from `runtime.items` and `max(created_at)` from
`runtime.messages`. It removes the container and the volume on the way out (`--keep`
leaves them for inspection).

It exits non-zero when the restore takes more than 15 minutes (`--max-seconds`), when the
newest recovered message is more than 10 minutes older than the moment the drill started
(`--rpo-minutes`), or when `--expect-items` is given and the count does not match. If the
source has written nothing recent the RPO check is skipped with a warning: an idle clinic
has nothing to lose, and failing on that would teach you to ignore the drill.

`--target-time '2026-09-02 14:05:00+00'` restores to a point in time instead of to the end
of the archive. That is the flag you want after a bad migration or a wrong `DELETE`.

Weekly in CI: `.github/workflows/backup-drill.yml` does all of the above on a schedule,
seeding rows before the base backup and more rows after it, so a broken archive_command
fails the job rather than being discovered during an outage. It proves the tooling, not
the R2 credentials — that is what the monthly drill is for.

## Restore for real

The VPS is gone, or the data is wrong and you want it back the way it was at 14:05.

1. Bring up a machine with Docker and the repository. Put the real `walg.env` on it.
2. Stop the application so nothing writes: `docker compose stop app portal-server`.
3. Rehearse first, on the same box, with the drill script — it costs 15 minutes and
   changes nothing:

   ```bash
   bash runtime/scripts/restore-drill.sh --walg-env runtime/scripts/db/walg.env \
     --target-time '2026-09-02 14:05:00+00' --keep
   ```

   `--keep` leaves the restored container up so you can look at it
   (`docker exec -it spatalk-restore-drill-<stamp> psql -U spatalk spatalk`).
4. When the rehearsal shows the data you expected, do it for real. Keep the broken cluster
   — copy it aside, never delete it, until the clinic is answering calls again:

   ```bash
   docker compose stop db
   docker volume create pgdata-broken
   docker run --rm -v runtime_pgdata:/from:ro -v pgdata-broken:/to alpine \
     sh -c "cd /from && cp -a . /to"
   ```

   Then empty the data directory and fetch the backup into it, from a shell in a container
   that has WAL-G and the credentials already:

   ```bash
   docker compose run --rm -it --entrypoint sh -u postgres db
   # inside the container:
   rm -rf /var/lib/postgresql/data/*
   wal-g backup-fetch /var/lib/postgresql/data LATEST
   cat >> /var/lib/postgresql/data/postgresql.auto.conf <<'EOF'
   restore_command = 'wal-g wal-fetch %f %p'
   recovery_target_action = 'promote'
   EOF
   touch /var/lib/postgresql/data/recovery.signal
   exit
   ```

   For a point in time, add `recovery_target_time = '2026-09-02 14:05:00+00'` to that
   heredoc. Then start it and watch it replay:

   ```bash
   docker compose up -d db
   docker compose logs -f db          # wait for "database system is ready to accept connections"
   ```
5. `docker compose exec db psql -U spatalk -tAc "select count(*) from runtime.items"` and
   check the newest message. Then `docker compose up -d app portal-server`.
6. Take a fresh base backup immediately: the timeline changed, and the old WAL no longer
   describes the cluster you are now running.

## Monthly drill against R2

The CI drill uses MinIO, so it never proves the R2 credentials still work. Once a month,
on the VPS, against the real bucket. Put it in the calendar on the first Monday, 15
minutes.

1. `docker compose exec -u postgres db wal-g backup-list` — the newest base backup is from
   last night, and there are up to seven of them.
2. `bash runtime/scripts/restore-drill.sh --walg-env runtime/scripts/db/walg.env
   --source-url "$DATABASE_URL"` — it must print `PASS`, with the elapsed time under 15
   minutes and the recovery point within 10 minutes of the start.
3. Write the date, the elapsed time and the recovered row count in the table below.
4. If it failed: check `failed_count` in `pg_stat_archiver`, then `/var/log/walg.log` in
   the database container, then whether the R2 API token has expired (they can be scoped
   to expire; ours is not, but tokens get rotated by accident).
5. While you are there, confirm the OVH automatic backup option is still on the VPS. It is
   the second copy, and it is the one that survives a mistake in `walg.env`.

| Date | Elapsed | Recovery point | Items restored | Notes |
|---|---|---|---|---|
| | | | | first run after go-live |
