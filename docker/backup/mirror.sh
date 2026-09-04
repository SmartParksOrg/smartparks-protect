#!/bin/sh
# Mirrors every MinIO bucket to the remote backup bucket (architecture 28.5), or back on
# restore. Runs in the minio/mc image as the compose service `object-mirror`. Incremental: only
# new or changed objects are copied. Objects deleted locally stay on the remote (no --remove), so
# a wrong deletion can be recovered; the remote bucket keeps versions where the provider supports
# them. MIRROR_DIRECTION=restore copies the remote copy back into the local buckets.
set -eu
scheme=https
[ "${BACKUP_S3_SECURE:-true}" = "true" ] || scheme=http
mc --quiet alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc --quiet alias set remote "${scheme}://${BACKUP_S3_ENDPOINT}" "$BACKUP_S3_KEY" "$BACKUP_S3_KEY_SECRET"
prefix="${BACKUP_OBJECT_PREFIX:-objects}"
status=0
for bucket in ${MIRROR_BUCKETS:-uploads exports device-log-files}; do
    remote="remote/${BACKUP_S3_BUCKET}/${prefix}/${bucket}"
    if [ "${MIRROR_DIRECTION:-backup}" = "restore" ]; then
        echo "restore ${remote} -> local/${bucket}"
        mc mb --ignore-existing "local/${bucket}"
        if ! mc ls "$remote" > /dev/null 2>&1; then
            echo "nothing under ${remote}: the bucket was empty when it was mirrored"
            continue
        fi
        mc mirror --overwrite --preserve --retry --summary "$remote" "local/${bucket}" || status=1
    else
        echo "mirror local/${bucket} -> ${remote}"
        mc mirror --overwrite --preserve --retry --summary "local/${bucket}" "$remote" || status=1
    fi
done
exit $status
