#!/bin/sh
# `protect-pgbackrest`: pgBackRest with the environment docker-compose.yml provides. It is the
# archive_command (`... archive-push %p`) and what scripts/backup.sh, scripts/restore.sh and
# scripts/restore-verify.sh call. Three things pgBackRest itself would refuse are handled here:
# an archive-push while backups are not enabled is acknowledged and dropped (a development
# machine); an option that compose had to leave empty is removed; S3 options are removed when
# the repository is not S3. The log and spool directories live in the pgbackrest-state volume.
if [ "${BACKUP_ENABLED:-false}" != "true" ]; then
    for arg in "$@"; do
        [ "$arg" = "archive-push" ] && exit 0
    done
fi
for name in $(env | sed -n 's/^\(PGBACKREST_[A-Z0-9_]*\)=$/\1/p'); do
    unset "$name"
done
if [ "${PGBACKREST_REPO1_TYPE:-s3}" != "s3" ]; then
    for name in $(env | sed -n 's/^\(PGBACKREST_REPO1_S3_[A-Z0-9_]*\)=.*/\1/p'); do
        unset "$name"
    done
fi
mkdir -p /home/postgres/pgdata/backup/log /home/postgres/pgdata/backup/spool /tmp/pgbackrest
exec pgbackrest "$@"
