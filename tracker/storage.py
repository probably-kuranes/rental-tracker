"""Where original PDFs are kept, by content hash.

Local directory by default (a Railway volume in production). Set
BLOB_BUCKET (plus BLOB_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
to use S3 or Cloudflare R2 instead.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalStore:
    def __init__(self, root: str | None = None):
        self.root = Path(root or os.getenv('BLOB_DIR', 'data/documents'))

    def put(self, digest: str, data: bytes) -> None:
        path = self.root / digest[:2] / f"{digest}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)

    def get(self, digest: str) -> bytes:
        return (self.root / digest[:2] / f"{digest}.pdf").read_bytes()


class S3Store:
    def __init__(self, bucket: str):
        import boto3  # optional dependency
        self.bucket = bucket
        self.client = boto3.client('s3', endpoint_url=os.getenv('BLOB_ENDPOINT_URL') or None)

    def put(self, digest: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=f"documents/{digest}.pdf", Body=data,
                               ContentType='application/pdf')

    def get(self, digest: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=f"documents/{digest}.pdf")['Body'].read()


def store():
    bucket = os.getenv('BLOB_BUCKET')
    return S3Store(bucket) if bucket else LocalStore()
