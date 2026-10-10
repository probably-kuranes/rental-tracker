"""Where original PDFs are kept, by content hash.

In the database by default, so the web app and the mail job (separate
Railway services, which cannot share a volume) see the same files. A
statement PDF is under 200 KB, so a few thousand of them are a few hundred MB.
Set BLOB_DIR to keep them in a directory instead, or BLOB_BUCKET (plus
BLOB_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) for S3 or
Cloudflare R2.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DbStore:
    def put(self, digest: str, data: bytes, session=None) -> None:
        from . import db
        own = session is None
        s = session or db.session()
        try:
            if s.get(db.Blob, digest) is None:
                s.add(db.Blob(sha256=digest, data=data))
                if own:
                    s.commit()
        finally:
            if own:
                s.close()

    def get(self, digest: str) -> bytes:
        from . import db
        with db.session() as s:
            blob = s.get(db.Blob, digest)
            if blob is None:
                raise FileNotFoundError(digest)
            return blob.data


class LocalStore:
    def __init__(self, root: str):
        self.root = Path(root)

    def put(self, digest: str, data: bytes, session=None) -> None:
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

    def put(self, digest: str, data: bytes, session=None) -> None:
        self.client.put_object(Bucket=self.bucket, Key=f"documents/{digest}.pdf", Body=data,
                               ContentType='application/pdf')

    def get(self, digest: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=f"documents/{digest}.pdf")['Body'].read()


def store():
    if os.getenv('BLOB_BUCKET'):
        return S3Store(os.environ['BLOB_BUCKET'])
    if os.getenv('BLOB_DIR'):
        return LocalStore(os.environ['BLOB_DIR'])
    return DbStore()
