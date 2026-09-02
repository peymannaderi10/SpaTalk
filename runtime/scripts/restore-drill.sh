#!/usr/bin/env bash
# Restore drill: prove that what WAL-G put in the object store comes back.
#
# Starts a throwaway container from the same image the database runs, on a fresh
# volume, fetches the latest base backup, replays the archived WAL on top of it, and
# reads the two numbers that say whether the clinic's ledger survived. Nothing here
# touches the source database: it only reads one timestamp from it, for the RPO
# check, and the clone is started with archiving off so it can never push over the
# backups it just restored.
#
#   bash scripts/restore-drill.sh --walg-env scripts/db/walg.env \
#        --source-url postgresql://spatalk:spatalk@localhost:5434/spatalk
#
# Fails (non-zero) when the restore takes longer than MAX_SECONDS, when the newest
# recovered message is older than RPO_MINUTES relative to the moment the drill
# started, or when --expect-items is given and the count does not match. The RPO
# check is skipped with a warning when the source has written nothing recent: an
# idle clinic has nothing to lose and that is not a backup failure.
#
# See docs/runbooks/backups.md.
set -euo pipefail

# Git Bash rewrites arguments that look like absolute POSIX paths into Windows paths
# before they reach docker.exe, so `/var/lib/postgresql/data` arrives inside the
# container as `C:/Program Files/Git/var/lib/postgresql/data`. Harmless on Linux.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

IMAGE=${IMAGE:-spatalk-db:16}
NETWORK=${NETWORK:-runtime_default}
MAX_SECONDS=${MAX_SECONDS:-900}      # 15 minutes; longer than this is not a restore, it is an outage
RPO_MINUTES=${RPO_MINUTES:-10}       # archive_timeout is 60s, so 10 minutes is generous
WALG_ENV=""
SOURCE_URL=""
TARGET_TIME=""
EXPECT_ITEMS=""
KEEP=0

usage() {
    sed -n '2,20p' "$0"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --walg-env)     WALG_ENV=$2; shift 2 ;;
        --source-url)   SOURCE_URL=$2; shift 2 ;;
        --image)        IMAGE=$2; shift 2 ;;
        --network)      NETWORK=$2; shift 2 ;;
        --target-time)  TARGET_TIME=$2; shift 2 ;;
        --expect-items) EXPECT_ITEMS=$2; shift 2 ;;
        --max-seconds)  MAX_SECONDS=$2; shift 2 ;;
        --rpo-minutes)  RPO_MINUTES=$2; shift 2 ;;
        --keep)         KEEP=1; shift ;;
        -h|--help)      usage ;;
        *) echo "restore-drill: unknown argument $1" >&2; usage ;;
    esac
done

if [ -z "$WALG_ENV" ] || [ ! -r "$WALG_ENV" ]; then
    echo "restore-drill: --walg-env must point at a readable WAL-G environment file" >&2
    exit 1
fi

STAMP=$(date +%Y%m%d%H%M%S)
NAME="spatalk-restore-drill-$STAMP"
VOLUME="spatalk-restore-drill-$STAMP"
DATA_DIR=/var/lib/postgresql/data

cleanup() {
    local status=$?
    if [ "$KEEP" = "1" ]; then
        echo "restore-drill: --keep given, leaving container $NAME and volume $VOLUME"
        return $status
    fi
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME" >/dev/null 2>&1 || true
    return $status
}
trap cleanup EXIT

psql_source() {
    # psql comes from the database image, so the drill needs no client on the host.
    docker run --rm --network "$NETWORK" --entrypoint psql "$IMAGE" "$1" -tAc "$2"
}

in_clone() {
    docker exec -u postgres "$NAME" "$@"
}

started_at=$(date +%s)
rpo_floor=$(( started_at - RPO_MINUTES * 60 ))

# --- what the source thinks the latest message is, before anything is restored ---
source_latest=0
if [ -n "$SOURCE_URL" ]; then
    # The runtime writes its URL with the asyncpg driver in it; psql wants libpq's form.
    plain_url=${SOURCE_URL/+asyncpg/}
    source_latest=$(psql_source "$plain_url" \
        "select coalesce(extract(epoch from max(created_at))::bigint, 0) from runtime.messages" \
        | tr -d '[:space:]') || {
        echo "restore-drill: could not read the source at $plain_url" >&2
        exit 1
    }
fi

echo "restore-drill: image=$IMAGE network=$NETWORK volume=$VOLUME"
docker volume create "$VOLUME" >/dev/null

# --- a throwaway container, asleep, with the backup credentials and a fresh volume ---
docker run -d --name "$NAME" --network "$NETWORK" \
    --env-file "$WALG_ENV" \
    -e PGDATA="$DATA_DIR" \
    -v "$VOLUME:$DATA_DIR" \
    --entrypoint sleep "$IMAGE" infinity >/dev/null

docker exec -u root "$NAME" sh -c "chown postgres:postgres '$DATA_DIR' && chmod 0700 '$DATA_DIR'"

echo "restore-drill: fetching the latest base backup"
in_clone wal-g backup-fetch "$DATA_DIR" LATEST

# --- replay the archived WAL on top of it ---
# postgresql.auto.conf is read after the restored postgresql.conf, so this wins.
{
    echo ""
    echo "# --- restore drill $STAMP ---"
    echo "restore_command = 'wal-g wal-fetch %f %p'"
    echo "archive_mode = off"
    echo "recovery_target_action = 'promote'"
    if [ -n "$TARGET_TIME" ]; then
        echo "recovery_target_time = '$TARGET_TIME'"
    fi
} | docker exec -i -u postgres "$NAME" sh -c "cat >> '$DATA_DIR/postgresql.auto.conf'"
in_clone sh -c "touch '$DATA_DIR/recovery.signal'"

echo "restore-drill: starting Postgres and replaying WAL"
docker exec -d -u postgres "$NAME" sh -c "postgres -D '$DATA_DIR' > /tmp/postgres.log 2>&1"

deadline=$(( started_at + MAX_SECONDS ))
while :; do
    if in_clone pg_isready -q -U spatalk 2>/dev/null; then
        in_recovery=$(in_clone psql -U spatalk -d spatalk -tAc "select pg_is_in_recovery()" \
            2>/dev/null | tr -d '[:space:]' || true)
        if [ "$in_recovery" = "f" ]; then
            break
        fi
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "restore-drill: FAIL restore did not finish within ${MAX_SECONDS}s" >&2
        docker exec "$NAME" tail -n 40 /tmp/postgres.log >&2 || true
        exit 1
    fi
    sleep 2
done

elapsed=$(( $(date +%s) - started_at ))

# --- the two numbers the clinic would ask about ---
items=$(in_clone psql -U spatalk -d spatalk -tAc \
    "select count(*) from runtime.items" | tr -d '[:space:]')
latest_message=$(in_clone psql -U spatalk -d spatalk -tAc \
    "select max(created_at) from runtime.messages" | tr -d '\r' | sed 's/^ *//;s/ *$//')
latest_message=${latest_message:-none}
restored_latest=$(in_clone psql -U spatalk -d spatalk -tAc \
    "select coalesce(extract(epoch from (select max(created_at) from runtime.messages))::bigint, 0)" \
    | tr -d '[:space:]')

echo ""
echo "restore-drill: restored in ${elapsed}s (budget ${MAX_SECONDS}s)"
echo "restore-drill: recovery point (latest recovered message, UTC): $latest_message"
echo "restore-drill: runtime.items rows: $items"

# --- the failable checks ---
if [ "$elapsed" -gt "$MAX_SECONDS" ]; then
    echo "restore-drill: FAIL restore took ${elapsed}s, budget is ${MAX_SECONDS}s" >&2
    exit 1
fi

if [ -n "$EXPECT_ITEMS" ] && [ "$items" != "$EXPECT_ITEMS" ]; then
    echo "restore-drill: FAIL expected $EXPECT_ITEMS items, restored $items" >&2
    exit 1
fi

if [ -z "$SOURCE_URL" ]; then
    echo "restore-drill: WARNING no --source-url, RPO check skipped"
elif [ "$source_latest" -lt "$rpo_floor" ]; then
    echo "restore-drill: WARNING source idle (no message in the last ${RPO_MINUTES}m)," \
         "RPO check skipped"
elif [ "$restored_latest" -lt "$rpo_floor" ]; then
    echo "restore-drill: FAIL newest recovered message is older than ${RPO_MINUTES}m;" \
         "the source had one at $(date -u -d "@$source_latest" '+%Y-%m-%d %H:%M:%S' 2>/dev/null \
         || echo "epoch $source_latest")" >&2
    exit 1
else
    echo "restore-drill: RPO ok, recovered to within ${RPO_MINUTES}m of the drill start"
fi

echo "restore-drill: PASS"
