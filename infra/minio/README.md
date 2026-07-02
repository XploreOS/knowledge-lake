# MinIO Setup Notes

MinIO runs as an S3-compatible object store for development.
In production, replace with AWS S3 (same boto3 code, no endpoint_url override).

## Bucket Creation

The `klake-data` bucket is created automatically on first `docker compose up`
via the `minio-init` service in docker-compose.yml.

The raw zone bucket (`raw/` prefix within `klake-data`) is configured with:
- **Versioning enabled** (required for object-lock)
- **Object lock in GOVERNANCE mode** (WORM — raw zone immutability, FOUND-04)
- **Delete-deny bucket policy** for the raw/ prefix (defense-in-depth against app bugs)

## Why Not `If-None-Match: '*'`

AWS S3 supports the `*` wildcard for conditional writes (refuse overwrite).
**MinIO does not** (minio/minio#20346 — MinIO expects an exact ETag, rejects `*`).

The application enforces raw-zone immutability through:
1. Content-addressed SHA256 keys (`raw/{source_id}/{sha256}.{ext}`)
2. Registry hash lookup before any write (if hash exists, it's a no-op — FOUND-04)
3. `head_object` guard before the actual put (defense-in-depth)
4. MinIO versioning + object-lock (this file)
5. Bucket policy denying `s3:DeleteObject` on the raw/ prefix

## Credentials

Development credentials are in `.env` (gitignored). See `.env.example` for placeholders.
The docker-compose.yml sets MINIO_ROOT_USER / MINIO_ROOT_PASSWORD from those env vars.

## Production Migration

Change `KLAKE_STORAGE__ENDPOINT_URL` from the MinIO URL to empty (or remove it).
boto3 will then route to AWS S3 using the same credential chain (IAM role or environment).
