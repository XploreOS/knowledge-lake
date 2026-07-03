"""
Knowledge Lake storage package (FOUND-03, FOUND-04).

Provides a single boto3-based S3-compatible storage abstraction that works
against both MinIO (dev, endpoint_url set) and AWS S3 (prod, endpoint_url=None)
via a single code path.

Sub-modules:
    s3         — StorageBackend wrapping one boto3 S3 client
    bootstrap  — ensure_buckets() creates the raw bucket with WORM protections
"""
