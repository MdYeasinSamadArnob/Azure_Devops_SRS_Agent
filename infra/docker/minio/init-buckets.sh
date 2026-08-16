#!/bin/sh
set -eu

mc alias set local "http://minio:9000" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

for bucket in srs-source-assets srs-templates srs-generated-documents srs-previews srs-snapshots srs-temporary; do
  mc mb --ignore-existing "local/${bucket}"
done

# Dev-only: buckets stay private; presigned URLs are the only external access path.
echo "MinIO buckets ready."
