#!/bin/bash
# Starts cron beside Postgres, then runs the stock entrypoint unchanged.
#
# The WAL-G sidecar the plan allows is this: one cron daemon in the database
# container, no extra service in Compose. Cron jobs inherit nothing from the
# container environment, so the WAL-G variables (which arrive through
# `env_file: walg.env`) are written to a file `walg-run` sources. The file holds
# credentials: root writes it, the postgres group reads it, nobody else.
set -euo pipefail

SNAPSHOT=/var/run/walg/env

if [ "$(id -u)" = "0" ]; then
    install -d -m 0755 /var/run/walg
    : > "$SNAPSHOT"
    chmod 0640 "$SNAPSHOT"
    chown root:postgres "$SNAPSHOT"
    for name in \
        WALG_S3_PREFIX WALG_COMPRESSION_METHOD WALG_DELTA_MAX_STEPS \
        AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_ENDPOINT AWS_REGION \
        AWS_S3_FORCE_PATH_STYLE PGHOST PGPORT PGUSER PGDATABASE PGDATA
    do
        if [ -n "${!name:-}" ]; then
            printf '%s=%s\n' "$name" "${!name}" >> "$SNAPSHOT"
        fi
    done

    if [ -x /usr/sbin/cron ]; then
        /usr/sbin/cron
    fi
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
