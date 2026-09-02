# The SpaTalk database: stock Postgres 16 plus WAL-G, which archives every WAL
# segment to Cloudflare R2 and pushes a base backup nightly (operations plan, E2).
#
# Debian ("bookworm"), not `postgres:16-alpine` as the plan wrote: WAL-G publishes
# glibc binaries only -- the release assets are `wal-g-pg-<ubuntu release>-<arch>` --
# so there is nothing to install into Alpine short of putting a Go toolchain in the
# database image. The Ubuntu 22.04 build (glibc 2.35) runs on bookworm (glibc 2.36).
FROM postgres:16-bookworm

# Pin both the release and its published checksum. `latest` in a database image is
# how a restore stops working on a Tuesday.
ARG WALG_VERSION=v3.0.9
ARG WALG_ASSET=wal-g-pg-22.04-amd64
ARG WALG_SHA256=4f03ee4679db7f660bfd1b2b8291ac5df247cd2ec48074b60c112f4897299f24

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates cron curl; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/wal-g.tar.gz \
      "https://github.com/wal-g/wal-g/releases/download/${WALG_VERSION}/${WALG_ASSET}.tar.gz"; \
    echo "${WALG_SHA256}  /tmp/wal-g.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/wal-g.tar.gz -C /tmp; \
    mv "/tmp/${WALG_ASSET}" /usr/local/bin/wal-g; \
    chmod 0755 /usr/local/bin/wal-g; \
    rm -f /tmp/wal-g.tar.gz; \
    wal-g --version

# The archive command and the cron jobs both go through this wrapper, never through
# `wal-g` directly: see the comment at the top of it.
COPY walg-run /usr/local/bin/walg-run
COPY entrypoint-walg.sh /usr/local/bin/entrypoint-walg.sh
COPY postgresql.conf /etc/postgresql/postgresql.conf
COPY backup-cron /etc/cron.d/spatalk-backup

RUN set -eux; \
    chmod 0755 /usr/local/bin/walg-run /usr/local/bin/entrypoint-walg.sh; \
    chmod 0644 /etc/postgresql/postgresql.conf /etc/cron.d/spatalk-backup; \
    chown root:root /etc/cron.d/spatalk-backup; \
    touch /var/log/walg.log; \
    chown postgres:postgres /var/log/walg.log

# `entrypoint-walg.sh` starts cron, snapshots the WAL-G environment where cron can
# read it, and then hands over to the image's own `docker-entrypoint.sh` unchanged.
ENTRYPOINT ["/usr/local/bin/entrypoint-walg.sh"]
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
